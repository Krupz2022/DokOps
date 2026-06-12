"""
RAG ingestion and management endpoints.
"""
import json
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi import Body
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.core.db import AsyncSessionLocal
from app.core.settings_cache import invalidate as _invalidate_settings_cache
from app.models.setting import SystemSetting
from app.models.user import User
from app.services.rag_service import rag_service, _MAX_FILE_BYTES

import uuid as _uuid
from fastapi import BackgroundTasks

# In-memory job store — survives as long as the process is running
_ingest_jobs: dict = {}


async def _run_ingest_job(job_id: str, fn, *args, **kwargs) -> None:
    """Execute fn(*args, **kwargs) and update the job store with the result."""
    import inspect
    _ingest_jobs[job_id]["status"] = "processing"
    # Trim oldest entries when store exceeds 500 to prevent unbounded growth
    if len(_ingest_jobs) > 500:
        oldest = next(iter(_ingest_jobs))
        if oldest != job_id:
            _ingest_jobs.pop(oldest, None)
    try:
        if inspect.iscoroutinefunction(fn):
            doc = await fn(*args, **kwargs)
        else:
            doc = fn(*args, **kwargs)
        _ingest_jobs[job_id].update({
            "status": "indexed",
            "doc_id": doc.id,
            "title": doc.title,
            "chunk_count": doc.chunk_count,
        })
    except Exception as exc:
        _ingest_jobs[job_id].update({"status": "failed", "error": str(exc)})


router = APIRouter()


# ── Confluence config schema ───────────────────────────────────────────────────

class ConfluenceConfigIn(BaseModel):
    instance_type: str = "cloud"
    base_url: str
    email: str = ""
    username: str = ""
    api_token: str = ""          # empty string = keep existing token unchanged
    sync_spaces: list[str] = []
    sync_interval_hours: int = 24


@router.get("/documents")
async def list_documents(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    docs = await rag_service.list_documents()
    return [
        {
            "id": d.id,
            "title": d.title,
            "source_type": d.source_type,
            "source_ref": d.source_ref,
            "chunk_count": d.chunk_count,
            "status": d.status,
            "indexed_at": d.indexed_at,
        }
        for d in docs
    ]


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    ok = await rag_service.delete_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted"}


@router.post("/ingest/upload")
async def ingest_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    allowed = {".pdf", ".md", ".txt", ".markdown"}
    import os
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Allowed: {allowed}")
    content = await file.read()
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 5 MB.")
    job_id = str(_uuid.uuid4())
    _ingest_jobs[job_id] = {"status": "queued", "title": file.filename}
    background_tasks.add_task(_run_ingest_job, job_id, rag_service.ingest_file, file.filename or "upload", content)
    return {"job_id": job_id, "status": "queued", "title": file.filename}


@router.post("/ingest/url")
def ingest_url(
    background_tasks: BackgroundTasks,
    url: str = Body(..., embed=True),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    job_id = str(_uuid.uuid4())
    _ingest_jobs[job_id] = {"status": "queued", "title": url}
    background_tasks.add_task(_run_ingest_job, job_id, rag_service.ingest_url, url)
    return {"job_id": job_id, "status": "queued", "title": url}


@router.get("/jobs/{job_id}")
def get_ingest_job(
    job_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    job = _ingest_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **job}


@router.post("/ingest/runbooks")
async def ingest_runbooks(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    from app.services.runbook_service import runbook_service  # type: ignore
    runbooks = runbook_service.list_runbooks()
    results = []
    for rb in runbooks:
        rb_id = rb.get("id", "unknown")
        name = rb.get("name", rb_id)
        # Serialize the runbook as text for indexing
        text_parts = [f"# Runbook: {name}"]
        for step in rb.get("steps", []):
            step_name = step.get("name", "")
            tool = step.get("tool", "")
            text_parts.append(f"Step: {step_name} (tool: {tool})")
        text = "\n".join(text_parts)
        try:
            doc = await rag_service.ingest_text(
                text=text,
                title=name,
                source_type="runbook",
                source_ref=rb_id,
                collection_name="knowledge_base",
                doc_id=f"runbook_{rb_id}",
            )
            results.append({"id": doc.id, "title": doc.title, "status": doc.status})
        except Exception as e:
            results.append({"id": rb_id, "title": name, "status": "failed", "error": str(e)})
    return {"synced": len(results), "results": results}



@router.post("/test-connection")
async def test_connection(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    try:
        await rag_service.test_connection()
        return {"status": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Confluence endpoints ───────────────────────────────────────────────────────

_CONFLUENCE_KEYS = [
    "confluence_enabled",
    "confluence_instance_type",
    "confluence_base_url",
    "confluence_email",
    "confluence_username",
    "confluence_api_token",
    "confluence_sync_spaces",
    "confluence_sync_interval_hours",
]


@router.get("/confluence/config")
async def get_confluence_config(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    result: dict = {}
    async with AsyncSessionLocal() as session:
        for full_key in _CONFLUENCE_KEYS:
            row = await session.get(SystemSetting, full_key)
            val = row.value if row else ""
            short_key = full_key.replace("confluence_", "")
            if full_key == "confluence_api_token" and val:
                val = "••••••"
            result[short_key] = val
    return result


@router.post("/confluence/config")
async def save_confluence_config(
    config: ConfluenceConfigIn,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    async def _save(key: str, value: str) -> None:
        async with AsyncSessionLocal() as session:
            row = await session.get(SystemSetting, key)
            if row:
                row.value = value
                session.add(row)
            else:
                session.add(SystemSetting(key=key, value=value))
            await session.commit()

    await _save("confluence_enabled", "true")
    await _save("confluence_instance_type", config.instance_type)
    await _save("confluence_base_url", config.base_url.rstrip("/"))
    await _save("confluence_email", config.email)
    await _save("confluence_username", config.username)
    if config.api_token:
        await _save("confluence_api_token", config.api_token)
    await _save("confluence_sync_spaces", json.dumps(config.sync_spaces))
    await _save("confluence_sync_interval_hours", str(config.sync_interval_hours))
    _invalidate_settings_cache()

    # Re-register (or remove) the scheduler job with the new interval
    from app.main import scheduler
    from app.services.connectors.confluence_connector import _run_confluence_sync_blocking
    from apscheduler.triggers.interval import IntervalTrigger
    import asyncio

    if config.sync_interval_hours > 0:
        async def _job() -> None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _run_confluence_sync_blocking)

        scheduler.add_job(
            _job,
            trigger=IntervalTrigger(hours=config.sync_interval_hours),
            id="confluence_sync",
            replace_existing=True,
        )
    else:
        try:
            scheduler.remove_job("confluence_sync")
        except Exception:
            pass

    return {"status": "saved"}


@router.post("/confluence/test")
def test_confluence_connection(
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    from app.services.connectors.confluence_connector import confluence_connector
    try:
        confluence_connector.test_connection()
        return {"status": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/ingest/confluence/space")
async def ingest_confluence_space(
    space_key: str = Body(..., embed=True),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    from app.services.connectors.confluence_connector import confluence_connector
    synced = 0
    failed = 0
    results = []
    try:
        for pid, title, text, page_url in confluence_connector.get_space_pages(space_key):
            if not text.strip():
                continue
            try:
                doc = await rag_service.ingest_text(
                    text=text,
                    title=title,
                    source_type="confluence",
                    source_ref=page_url,
                    collection_name="knowledge_base",
                    doc_id=f"confluence_{pid}",
                    max_chars=200_000,
                )
                synced += 1
                results.append({"id": doc.id, "title": title, "status": "indexed"})
            except Exception as exc:
                failed += 1
                results.append({"id": pid, "title": title, "status": "failed", "error": str(exc)})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Confluence API error: {exc}")
    return {"synced": synced, "failed": failed, "results": results}


@router.post("/ingest/confluence/page")
async def ingest_confluence_page(
    url: str = Body(..., embed=True),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    from app.services.connectors.confluence_connector import (
        confluence_connector,
        parse_page_id_from_url,
    )
    try:
        page_id = parse_page_id_from_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        title, text = confluence_connector.get_page_by_id(page_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Confluence API error: {exc}")
    if not text.strip():
        raise HTTPException(status_code=422, detail="Page has no text content after parsing")
    try:
        doc = await rag_service.ingest_text(
            text=text,
            title=title,
            source_type="confluence",
            source_ref=url,
            collection_name="knowledge_base",
            doc_id=f"confluence_{page_id}",
            max_chars=200_000,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"id": doc.id, "title": doc.title, "chunk_count": doc.chunk_count, "status": doc.status}
