from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict

from sqlmodel import Session, select

from app.core.db import engine
from app.models.service_diag import DiscoveredService
from app.services.service_credential_service import resolve_credential
from app.services.probe_registry import render_command, PROBES
from app.services.minion_service import manager

log = logging.getLogger(__name__)


def list_minion_services(minion_id: str) -> Dict[str, Any]:
    """List services discovered on this minion. Call this first before running probes."""
    try:
        with Session(engine) as db:
            services = db.exec(
                select(DiscoveredService).where(DiscoveredService.minion_id == minion_id)
            ).all()
        return {
            "success": True,
            "data": [
                {
                    "service_type": s.service_type,
                    "install_type": s.install_type,
                    "container_name": s.container_name,
                    "port": s.port,
                    "detected_at": s.detected_at.isoformat(),
                    "overridden": s.overridden,
                    "available_probes": list(PROBES.get(s.service_type, {}).keys()),
                }
                for s in services
            ],
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def run_service_probe(minion_id: str, service_type: str, probe_name: str) -> Dict[str, Any]:
    """Run a named probe for a service on a minion. Credentials are resolved automatically."""
    try:
        with Session(engine) as db:
            service = db.exec(
                select(DiscoveredService).where(
                    DiscoveredService.minion_id == minion_id,
                    DiscoveredService.service_type == service_type,
                )
            ).first()
            if not service:
                return {
                    "success": False,
                    "data": None,
                    "error": (
                        f"No discovered service {service_type!r} on minion {minion_id!r}. "
                        "Run list_minion_services first to see what is running."
                    ),
                }
            cred = resolve_credential(minion_id, service_type, db)

        cmd = render_command(
            service_type=service_type,
            probe_name=probe_name,
            install_type=service.install_type,
            cred=cred,
            port=service.port,
            container=service.container_name or "",
        )

        if not manager.is_connected(minion_id):
            return {"success": False, "data": None, "error": f"Minion {minion_id!r} is not connected"}

        result = await manager.dispatch_job(minion_id, cmd, actor="ai", timeout=60, god_mode=True)
        return {"success": result["exit_code"] == 0, "data": result["stdout"], "error": None}
    except asyncio.TimeoutError:
        return {"success": False, "data": None, "error": "Probe timed out after 30s"}
    except ValueError as e:
        return {"success": False, "data": None, "error": str(e)}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def get_service_logs(minion_id: str, service_type: str, tail_lines: int = 150) -> Dict[str, Any]:
    """Fetch recent logs for a service. Convenience wrapper for the logs probe."""
    return await run_service_probe(minion_id, service_type, "logs")
