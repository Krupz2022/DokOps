# backend/app/api/v1/integrations_obs.py
import json
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api import deps
from app.core.db import engine
from app.models.integration import IntegrationSettings
from app.services.integrations.base import build_auth_headers, encrypt_credentials
from app.services.integrations.prometheus import PrometheusService
from app.services.integrations.loki import LokiService
from app.services.integrations.grafana import GrafanaService
from app.services.integrations.elasticsearch import ElasticsearchService
from app.services.integrations.datadog import DatadogService

router = APIRouter()

# Keys map backend names to module-level class names (looked up dynamically so mocks work in tests)
BACKEND_SERVICE_NAMES = {
    "prometheus": "PrometheusService",
    "loki": "LokiService",
    "grafana": "GrafanaService",
    "elasticsearch": "ElasticsearchService",
    "datadog": "DatadogService",
}

import sys as _sys


def _get_service_cls(backend: str):
    """Resolve the service class at call time so test patches are honoured."""
    name = BACKEND_SERVICE_NAMES.get(backend)
    if name is None:
        return None
    module = _sys.modules[__name__]
    return getattr(module, name, None)


VALID_BACKENDS = Literal["prometheus", "loki", "grafana", "elasticsearch", "datadog"]


class ConnectRequest(BaseModel):
    backend: VALID_BACKENDS
    display_name: str
    base_url: str
    auth_type: str = "none"
    credentials: Optional[dict] = None


class IntegrationResponse(BaseModel):
    id: int
    backend: str
    display_name: str
    base_url: str
    auth_type: str
    is_active: bool
    health_status: Optional[str]
    connected_at: Optional[datetime]


@router.get("/", response_model=List[IntegrationResponse])
async def list_integrations(_user=Depends(deps.get_current_user)):
    with Session(engine) as session:
        rows = session.exec(select(IntegrationSettings)).all()
    return [IntegrationResponse(
        id=r.id, backend=r.backend, display_name=r.display_name, base_url=r.base_url,
        auth_type=r.auth_type, is_active=r.is_active,
        health_status=r.health_status, connected_at=r.connected_at,
    ) for r in rows]


@router.post("/connect", response_model=IntegrationResponse)
async def connect_integration(req: ConnectRequest, _user=Depends(deps.get_current_user)):
    from app.core.ssrf import validate_url
    try:
        validate_url(req.base_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid URL: {e}")

    svc_cls = _get_service_cls(req.backend)
    if not svc_cls:
        raise HTTPException(status_code=422, detail=f"Unknown backend: {req.backend}")

    encrypted = None
    if req.credentials:
        encrypted = encrypt_credentials(req.credentials)

    headers = build_auth_headers(req.auth_type, encrypted)
    svc = svc_cls()
    ok, msg = await svc.test_connection(req.base_url, headers)

    with Session(engine) as session:
        existing = session.exec(
            select(IntegrationSettings).where(IntegrationSettings.backend == req.backend)
        ).first()
        if existing:
            existing.display_name = req.display_name
            existing.base_url = req.base_url
            existing.auth_type = req.auth_type
            existing.encrypted_credentials = encrypted
            existing.is_active = ok
            existing.health_status = "ok" if ok else msg
            existing.connected_at = datetime.now(timezone.utc) if ok else existing.connected_at
            existing.last_checked_at = datetime.now(timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            row = existing
        else:
            row = IntegrationSettings(
                backend=req.backend,
                display_name=req.display_name,
                base_url=req.base_url,
                auth_type=req.auth_type,
                encrypted_credentials=encrypted,
                is_active=ok,
                health_status="ok" if ok else msg,
                connected_at=datetime.now(timezone.utc) if ok else None,
                last_checked_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            session.refresh(row)

    if not ok:
        raise HTTPException(status_code=400, detail=f"Connection failed: {msg}")

    return IntegrationResponse(
        id=row.id, backend=row.backend, display_name=row.display_name, base_url=row.base_url,
        auth_type=row.auth_type, is_active=row.is_active,
        health_status=row.health_status, connected_at=row.connected_at,
    )


@router.post("/{integration_id}/test")
async def test_integration(integration_id: int, _user=Depends(deps.get_current_user)):
    with Session(engine) as session:
        row = session.get(IntegrationSettings, integration_id)
        if not row:
            raise HTTPException(status_code=404, detail="Integration not found")

    svc_cls = _get_service_cls(row.backend)
    headers = build_auth_headers(row.auth_type, row.encrypted_credentials)
    svc = svc_cls()
    ok, msg = await svc.test_connection(row.base_url, headers)

    with Session(engine) as session:
        row = session.get(IntegrationSettings, integration_id)
        row.is_active = ok
        row.health_status = "ok" if ok else msg
        row.last_checked_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()

    return {"ok": ok, "message": msg}


@router.delete("/{integration_id}")
async def disconnect_integration(integration_id: int, _user=Depends(deps.get_current_user)):
    with Session(engine) as session:
        row = session.get(IntegrationSettings, integration_id)
        if not row:
            raise HTTPException(status_code=404, detail="Integration not found")
        session.delete(row)
        session.commit()
    return {"deleted": True}


@router.get("/debug/registry")
async def debug_registry(_user=Depends(deps.get_current_user)):
    """Return what tools the integration manager actually loaded — for diagnosing missing tools."""
    from app.services.integration_manager import integration_manager
    from sqlmodel import Session, select
    from app.models.integration import IntegrationSettings

    with Session(engine) as session:
        rows = session.exec(select(IntegrationSettings)).all()
        db_rows = [
            {"id": r.id, "backend": r.backend, "is_active": r.is_active,
             "has_credentials": bool(r.encrypted_credentials), "health_status": r.health_status}
            for r in rows
        ]

    registry = integration_manager.get_active_tool_registry()
    return {
        "db_integrations": db_rows,
        "loaded_tools": list(registry.keys()),
        "tool_count": len(registry),
    }
