import html as _html
import json
import logging
import re
from typing import Any, Iterator, Optional
from urllib.parse import parse_qs, urlparse

import requests
from sqlmodel import Session

from app.core.db import engine
from app.models.setting import SystemSetting

logger = logging.getLogger(__name__)


# ── Settings helpers ──────────────────────────────────────────────────────────

def _get_setting(key: str) -> Optional[str]:
    with Session(engine) as session:
        row = session.get(SystemSetting, key)
        return row.value if row else None


def _save_setting(key: str, value: str) -> None:
    with Session(engine) as session:
        row = session.get(SystemSetting, key)
        if row:
            row.value = value
            session.add(row)
        else:
            session.add(SystemSetting(key=key, value=value))
        session.commit()


# ── Text extraction ───────────────────────────────────────────────────────────

def _storage_to_text(storage_xml: str) -> str:
    """Strip Confluence storage-format XML tags to plain text."""
    text = re.sub(r"<[^>]+>", " ", storage_xml)
    text = _html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_body(page_dict: dict) -> str:
    """Extract plain text from a Confluence REST API page dict."""
    storage = page_dict.get("body", {}).get("storage", {}).get("value", "")
    return _storage_to_text(storage)


# ── URL parsing ───────────────────────────────────────────────────────────────

def parse_page_id_from_url(url: str) -> str:
    """
    Extract the numeric page ID from a Confluence page URL.

    Handles:
      Cloud:  https://org.atlassian.net/wiki/spaces/ENG/pages/123456/Title
      Server: https://confluence.org/pages/viewpage.action?pageId=123456
              https://confluence.org/pages/123456/Title
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "pageId" in qs:
        page_id = qs["pageId"][0]
        if not page_id.isdigit():
            raise ValueError(f"Cannot extract page ID from URL: {url}")
        return page_id

    match = re.search(r"/pages/(\d+)", url)
    if match:
        return match.group(1)

    raise ValueError(f"Cannot extract page ID from URL: {url}")


# ── Connector ─────────────────────────────────────────────────────────────────

class ConfluenceConnector:
    """
    Fetches Confluence pages for RAG ingestion.
    Config is read from SystemSettings at call time — no constructor args needed.
    """

    def _get_config(self) -> dict:
        try:
            sync_spaces = json.loads(_get_setting("confluence_sync_spaces") or "[]")
        except json.JSONDecodeError:
            sync_spaces = []
        return {
            "instance_type": _get_setting("confluence_instance_type") or "cloud",
            "base_url": (_get_setting("confluence_base_url") or "").rstrip("/"),
            "email": _get_setting("confluence_email") or "",
            "username": _get_setting("confluence_username") or "",
            "api_token": _get_setting("confluence_api_token") or "",
            "sync_spaces": sync_spaces,
            "sync_interval_hours": int(_get_setting("confluence_sync_interval_hours") or "0"),
        }

    def _build_session(self, config: dict) -> requests.Session:
        s = requests.Session()
        s.headers.update({"Accept": "application/json"})
        instance_type = config["instance_type"]
        token = config["api_token"]
        if instance_type == "cloud":
            s.auth = (config["email"], token)
        elif instance_type == "server_basic":
            s.auth = (config["username"], token)
        elif instance_type == "server_pat":
            if not token:
                raise ValueError("confluence_api_token is required for server_pat auth")
            s.headers["Authorization"] = f"Bearer {token}"
        return s

    def test_connection(self) -> None:
        """Raises on auth failure, connection error, or non-JSON response."""
        config = self._get_config()
        session = self._build_session(config)
        resp = session.get(f"{config['base_url']}/rest/api/user/current", timeout=10)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type:
            snippet = resp.text[:200].replace("\n", " ")
            raise ValueError(
                f"Confluence returned non-JSON content-type '{content_type}'. "
                f"Check base_url (Cloud needs /wiki suffix). Response: {snippet!r}"
            )

    def get_page_by_id(self, page_id: str) -> tuple[str, str]:
        """Returns (title, plain_text). Raises requests.HTTPError on failure."""
        config = self._get_config()
        session = self._build_session(config)
        resp = session.get(
            f"{config['base_url']}/rest/api/content/{page_id}",
            params={"expand": "body.storage"},
            timeout=15,
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            snippet = resp.text[:200].replace("\n", " ")
            raise ValueError(
                f"Confluence returned non-JSON (status {resp.status_code}). "
                f"Check base_url (Cloud needs /wiki suffix). Response: {snippet!r}"
            )
        title = data.get("title", page_id)
        return title, _extract_body(data)

    def get_space_pages(self, space_key: str) -> Iterator[tuple[str, str, str, str]]:
        """
        Yields (page_id, title, plain_text, page_url) for every page in the space.
        Paginates automatically (100 per request).
        """
        config = self._get_config()
        session = self._build_session(config)
        base_url = config["base_url"]
        start = 0
        limit = 100
        while True:
            resp = session.get(
                f"{base_url}/rest/api/content",
                params={
                    "spaceKey": space_key,
                    "type": "page",
                    "expand": "body.storage",
                    "limit": limit,
                    "start": start,
                },
                timeout=30,
            )
            resp.raise_for_status()
            try:
                payload = resp.json()
            except Exception:
                snippet = resp.text[:200].replace("\n", " ")
                raise ValueError(
                    f"Confluence returned non-JSON (status {resp.status_code}). "
                    f"Check base_url (Cloud needs /wiki suffix). Response: {snippet!r}"
                )
            results = payload.get("results", [])
            for page in results:
                pid = page["id"]
                title = page.get("title", pid)
                plain_text = _extract_body(page)
                if config["instance_type"] == "cloud":
                    page_url = f"{base_url}/wiki/spaces/{space_key}/pages/{pid}"
                else:
                    page_url = f"{base_url}/pages/{pid}"
                yield pid, title, plain_text, page_url
            if len(results) < limit:
                break
            start += limit


confluence_connector = ConfluenceConnector()


# ── Scheduler helpers ─────────────────────────────────────────────────────────

def _run_confluence_sync_blocking() -> None:
    """
    Synchronous sync of all configured spaces. Runs in a thread executor
    (called from an async APScheduler job) to avoid blocking the event loop.
    """
    from app.services.rag_service import rag_service  # local import avoids circular import at module load

    config = confluence_connector._get_config()
    for space_key in config.get("sync_spaces", []):
        synced = 0
        try:
            for pid, title, text, page_url in confluence_connector.get_space_pages(space_key):
                if not text.strip():
                    continue
                rag_service.ingest_text(
                    text=text,
                    title=title,
                    source_type="confluence",
                    source_ref=page_url,
                    collection_name="knowledge_base",
                    doc_id=f"confluence_{pid}",
                )
                synced += 1
            logger.info("Confluence scheduled sync: space=%s synced=%d", space_key, synced)
        except Exception as exc:
            logger.error("Confluence scheduled sync failed for space %s: %s", space_key, exc)


def _load_confluence_schedule(scheduler: Any) -> None:
    """Register (or skip) the Confluence sync APScheduler job on startup."""
    from apscheduler.triggers.interval import IntervalTrigger
    import asyncio

    enabled = (_get_setting("confluence_enabled") or "false").lower() == "true"
    interval_hours = int(_get_setting("confluence_sync_interval_hours") or "0")
    if not enabled or interval_hours <= 0:
        return

    async def _job() -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_confluence_sync_blocking)

    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(hours=interval_hours),
        id="confluence_sync",
        replace_existing=True,
    )
    logger.info("Confluence sync scheduled every %d hours", interval_hours)

