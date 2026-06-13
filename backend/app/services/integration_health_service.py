import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.integration import IntegrationSettings
from app.services.integrations.base import build_auth_headers
from app.services.integration_manager import _SERVICE_MAP
from app.services.k8s_service import k8s_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthEntry:
    healthy: bool
    checked_at: datetime
    error: Optional[str] = None


class IntegrationHealthService:
    _INTERVAL = 60

    def __init__(self) -> None:
        self._cache: Dict[str, HealthEntry] = {}
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Call once at FastAPI lifespan startup."""
        if self._task is None:
            self._task = asyncio.create_task(self._check_loop())

    async def stop(self) -> None:
        """Cancel the background task and wait for it to finish."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def get_snapshot(self) -> Dict[str, HealthEntry]:
        """Return a shallow copy of the current health cache."""
        async with self._lock:
            return dict(self._cache)

    async def _check_loop(self) -> None:
        while True:
            await self._run_all_checks()
            await asyncio.sleep(self._INTERVAL)

    async def _run_all_checks(self) -> None:
        results = await asyncio.gather(
            self._check_integrations(),
            self._check_kubernetes(),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.error("integration_health: check sub-task failed: %s", result)

    async def _check_integrations(self) -> None:
        try:
            async with AsyncSessionLocal() as session:
                rows = (await session.exec(
                    select(IntegrationSettings).where(IntegrationSettings.is_active == True)  # noqa: E712
                )).all()
        except Exception as e:
            logger.error("integration_health: DB query failed: %s", e)
            return

        if not rows:
            return

        async def _check_one(row) -> tuple[str, bool, str]:
            svc_cls = _SERVICE_MAP.get(row.backend)
            if not svc_cls:
                return row.backend, False, f"Unknown backend: {row.backend}"
            try:
                headers = build_auth_headers(row.auth_type, row.encrypted_credentials)
                svc = svc_cls()
                ok, msg = await svc.test_connection(row.base_url, headers)
                return row.backend, ok, msg
            except Exception as exc:
                return row.backend, False, str(exc)

        results = await asyncio.gather(
            *[_check_one(r) for r in rows], return_exceptions=True
        )

        now = datetime.now(tz=timezone.utc)
        async with self._lock:
            for result in results:
                if isinstance(result, Exception):
                    continue
                name, ok, msg = result
                self._cache[name] = HealthEntry(
                    healthy=ok,
                    checked_at=now,
                    error=None if ok else msg,
                )

    async def _check_kubernetes(self) -> None:
        if k8s_service.mock_mode:
            return  # mock mode = local dev, no real cluster to ping

        now = datetime.now(tz=timezone.utc)
        try:
            await asyncio.wait_for(k8s_service.list_namespaces(), timeout=3.0)
            entry = HealthEntry(healthy=True, checked_at=now)
        except Exception as exc:
            entry = HealthEntry(healthy=False, checked_at=now, error=str(exc) or "unreachable")

        async with self._lock:
            self._cache["kubernetes"] = entry


integration_health = IntegrationHealthService()
