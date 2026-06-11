import logging

# Suppress noisy third-party loggers
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
logging.getLogger("kubernetes.client.rest").setLevel(logging.ERROR)

def _configure_app_logging() -> None:
    """Apply LOG_LEVEL env var to all DokOps loggers. Uvicorn's own loggers are untouched."""
    from app.core.config import settings
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Ensure the root dokops logger has a console handler so messages aren't swallowed
    # (uvicorn configures its own loggers but leaves the root logger handler-less)
    _dokops_root = logging.getLogger("dokops")
    if not _dokops_root.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter("%(levelname)s  [%(name)s] %(message)s"))
        _dokops_root.addHandler(_handler)
    _dokops_root.setLevel(level)
    _dokops_root.propagate = False  # don't double-print via root

    _app_loggers = [
        "ai_service.tools",
        "ai_service.model",
        "ai_service.obs",
        "integration_manager",
        "app.services.integrations.elasticsearch",
        "app.services.integrations.prometheus",
        "app.services.integrations.loki",
        "app.services.integrations.grafana",
        "app.services.integrations.datadog",
        "app.services.ai_service",
        "app.core.db",
    ]
    for name in _app_loggers:
        logging.getLogger(name).setLevel(level)

_configure_app_logging()

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, create_engine, Session, select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core import security
from app.models.user import User
from app.models.audit import AuditLog
from app.api.api import api_router
from app.api.openai_compat import router as openai_compat_router

from app.core.db import create_db_and_tables, init_db, async_engine, _db_url as _db_url_main


def _assert_secret_changed(secret: str) -> None:
    if secret in ("changethis", "", "secret", "password"):
        raise RuntimeError(
            "AUTH_SECRET_KEY is set to a known-weak default value. "
            "Set a cryptographically random value via the AUTH_SECRET_KEY environment variable."
        )


import sys as _sys
if "pytest" not in _sys.modules and os.getenv("PYTEST_CURRENT_TEST") is None:
    _assert_secret_changed(settings.AUTH_SECRET_KEY)


async def _run_patch_migrations() -> None:
    """Idempotent ALTER TABLE statements for new columns added after initial schema creation."""
    from sqlalchemy import text

    is_postgres = not _db_url_main.startswith("sqlite")

    def _col(table: str, col: str, typedef: str) -> str:
        if is_postgres:
            return f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typedef}"
        return f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"

    migrations = [
        _col("patchpromotion", "failed_minions", "TEXT"),
        _col("patchpromotion", "excluded_minions", "TEXT"),
        _col("patchpromotion", "partial_override", "INTEGER NOT NULL DEFAULT 0"),
        _col("patchschedule", "timezone", "TEXT NOT NULL DEFAULT 'UTC'"),
        _col("patchschedule", "promote_from_previous", "INTEGER NOT NULL DEFAULT 0"),
        _col("minion", "last_patch_scan", "TIMESTAMP"),
    ]
    async with async_engine.connect() as conn:
        for sql in migrations:
            try:
                await conn.execute(text(sql))
                await conn.commit()
            except Exception:
                await conn.rollback()  # PostgreSQL: reset aborted transaction before next statement


_scheduler = AsyncIOScheduler()
scheduler = _scheduler  # public alias used by patching routes


async def _schedule_cron_workflows() -> None:
    from sqlmodel import select
    from app.core.db import AsyncSessionLocal
    from app.models.workflow import Workflow

    async with AsyncSessionLocal() as db:
        workflows = (await db.exec(
            select(Workflow).where(Workflow.trigger_type.in_(["cron", "all"]))
        )).all()

    for wf in workflows:
        if not wf.cron_schedule:
            continue
        parts = wf.cron_schedule.split()
        if len(parts) != 5:
            continue
        minute, hour, day, month, day_of_week = parts

        async def cron_job(wf_id: int = wf.id, wf_type: str = wf.workflow_type) -> None:
            # TODO(Phase 4): switch to AsyncSessionLocal once workflow_service.create_run is async
            from sqlmodel import Session
            from app.core.db import sync_engine
            from app.services import workflow_service as wf_svc
            from app.services import agent_executor_service as agent_svc
            with Session(sync_engine) as db:
                run = wf_svc.create_run(wf_id, {}, "cron", db)
            if wf_type == "agent":
                await agent_svc.run_agent_background(run.id, wf_id)
            else:
                await wf_svc.run_workflow_background(run.id, wf_id, {})

        _scheduler.add_job(
            cron_job,
            CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week),
            id=f"workflow_{wf.id}",
            replace_existing=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    await _run_patch_migrations()   # ← run AFTER create_db_and_tables; IF NOT EXISTS makes this safe on fresh DBs too
    await init_db()

    # Add backend/bin/ to PATH so installed CLI tools are discoverable
    import os
    from pathlib import Path
    _bin_dir = str(Path(__file__).resolve().parent.parent / "bin")
    if _bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _bin_dir + os.pathsep + os.environ.get("PATH", "")

    from app.services.k8s_service import k8s_service
    await k8s_service.initialize()

    from app.services.integration_health_service import integration_health
    integration_health.start()

    import asyncio

    from app.services.topology_service import topology_service
    await topology_service.start()

    from app.services.minion_service import mark_offline_loop
    _minion_offline_task = asyncio.create_task(mark_offline_loop())

    from app.services.activation_service import heartbeat_loop
    _heartbeat_task = asyncio.create_task(heartbeat_loop())

    from app.core.token_context import drain_token_queue
    _token_drain_task = asyncio.create_task(drain_token_queue())

    await _schedule_cron_workflows()
    _scheduler.start()

    from app.services.patch_service import load_schedules as _load_patch_schedules
    _load_patch_schedules(_scheduler)

    from app.services.connectors.confluence_connector import _load_confluence_schedule
    _load_confluence_schedule(_scheduler)

    _ingest_task = None

    yield

    _scheduler.shutdown(wait=False)
    _heartbeat_task.cancel()
    try:
        await _heartbeat_task
    except asyncio.CancelledError:
        pass
    _token_drain_task.cancel()
    try:
        await _token_drain_task
    except asyncio.CancelledError:
        pass
    await topology_service.stop()
    _minion_offline_task.cancel()
    try:
        await _minion_offline_task
    except asyncio.CancelledError:
        pass
    await k8s_service.close()
    await integration_health.stop()

    if _ingest_task is not None:
        _ingest_task.cancel()
        try:
            await _ingest_task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title=settings.PROJECT_NAME, 
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Middleware
from app.core.activation_middleware import ActivationMiddleware
from app.core.middleware import AuditMiddleware
app.add_middleware(AuditMiddleware)
app.add_middleware(ActivationMiddleware)

# CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(openai_compat_router, prefix="/v1")

@app.get("/")
async def root():
    return {"message": "MCP Kubernetes Server is Running"}

@app.get("/health")
async def health():
    return {"status": "ok"}

from fastapi.responses import FileResponse
from pathlib import Path as _Path

_MINION_DIR = _Path(__file__).resolve().parent.parent.parent / "minion"

@app.get("/minion/agent.py", include_in_schema=False)
async def serve_agent():
    p = _MINION_DIR / "agent.py"
    if not p.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="agent.py not bundled")
    return FileResponse(p, media_type="text/x-python")

@app.get("/minion/install.sh", include_in_schema=False)
async def serve_install_sh():
    p = _MINION_DIR / "install.sh"
    if not p.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="install.sh not bundled")
    return FileResponse(p, media_type="text/x-sh")

@app.get("/minion/uninstall.sh", include_in_schema=False)
async def serve_uninstall_sh():
    p = _MINION_DIR / "uninstall.sh"
    if not p.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="uninstall.sh not bundled")
    return FileResponse(p, media_type="text/x-sh")

@app.get("/minion/install.ps1", include_in_schema=False)
async def serve_install_ps1():
    p = _MINION_DIR / "install.ps1"
    if not p.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="install.ps1 not bundled")
    return FileResponse(p, media_type="text/plain")

@app.get("/minion/uninstall.ps1", include_in_schema=False)
async def serve_uninstall_ps1():
    p = _MINION_DIR / "uninstall.ps1"
    if not p.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="uninstall.ps1 not bundled")
    return FileResponse(p, media_type="text/plain")


@app.get("/minion/simple/{package_name}/", include_in_schema=False)
async def pypi_simple_proxy(package_name: str, request: Request):
    """Proxy PyPI simple index so pip can install through the DokOps server."""
    import re, urllib.parse, httpx
    from fastapi.responses import HTMLResponse

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(f"https://pypi.org/simple/{package_name}/")
    if resp.status_code != 200:
        from fastapi import HTTPException
        raise HTTPException(resp.status_code, "PyPI upstream error")

    base = str(request.base_url).rstrip("/")

    def rewrite(m: "re.Match") -> str:
        href = m.group(1)
        if href.startswith("http"):
            file_url = href
        else:
            file_url = urllib.parse.urljoin(f"https://pypi.org/simple/{package_name}/", href)
        url_part, _, hash_part = file_url.partition("#")
        proxied = f"{base}/minion/pypi-file/?url={urllib.parse.quote(url_part, safe='')}"
        if hash_part:
            proxied += f"#{hash_part}"
        return f'href="{proxied}"'

    html = re.sub(r'href="([^"]+)"', rewrite, resp.text)
    return HTMLResponse(content=html)


_PYPI_ALLOWED_HOSTS = {"pypi.org", "files.pythonhosted.org"}


@app.get("/minion/pypi-file/", include_in_schema=False)
async def pypi_file_proxy(url: str):
    """Stream a PyPI package file through this server (no direct PyPI access needed on client)."""
    import httpx
    from urllib.parse import urlparse
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse

    host = urlparse(url).hostname or ""
    if host not in _PYPI_ALLOWED_HOSTS:
        raise HTTPException(status_code=400, detail="URL not allowed")

    async def _stream():
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            async with client.stream("GET", url) as r:
                async for chunk in r.aiter_bytes(65536):
                    yield chunk

    filename = url.split("/")[-1].split("?")[0]
    return StreamingResponse(
        _stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
