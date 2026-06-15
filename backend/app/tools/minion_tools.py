import asyncio
import json
import logging
from typing import Any, Dict

from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.minion import Minion
from app.services.minion_service import is_read_allowed, manager

log = logging.getLogger(__name__)


async def minion_list() -> Dict[str, Any]:
    try:
        async with AsyncSessionLocal() as db:
            minions = (await db.exec(select(Minion))).all()
        return {
            "success": True,
            "data": [
                {
                    "id": m.id,
                    "hostname": m.hostname,
                    "status": m.status,
                    "grains_summary": _parse_grains(m.grains),
                    "last_seen": m.last_seen.isoformat() if m.last_seen else None,
                }
                for m in minions
            ],
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def minion_grains(minion_id: str) -> Dict[str, Any]:
    try:
        async with AsyncSessionLocal() as db:
            m = await db.get(Minion, minion_id)
        if not m:
            return {"success": False, "data": None, "error": f"Minion {minion_id!r} not found"}
        return {"success": True, "data": json.loads(m.grains), "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def minion_exec_read(minion_id: str, cmd: str, timeout: int = 60) -> Dict[str, Any]:
    if not is_read_allowed(cmd):
        return {
            "success": False,
            "data": None,
            "error": f"Command not allowed in read mode: {cmd!r}. Use minion_exec_write for write operations.",
        }
    return await _run_job(minion_id, cmd, actor="ai", timeout=timeout)


async def minion_exec_write(
    minion_id: str, cmd: str, reason: str, confirmed: bool = False, timeout: int = 60
) -> Dict[str, Any]:
    if not confirmed:
        return {
            "requires_confirmation": True,
            "operation": "minion_exec_write",
            "minion_id": minion_id,
            "command": cmd,
            "reason": reason,
            "warning": f"This will execute on {minion_id}: {cmd}",
        }
    return await _run_job(minion_id, cmd, actor="ai", timeout=timeout)


async def _run_job(minion_id: str, cmd: str, actor: str, timeout: int) -> Dict[str, Any]:
    if not manager.is_connected(minion_id):
        return {"success": False, "data": None, "error": f"Minion {minion_id!r} is not connected"}
    try:
        result = await manager.dispatch_job(minion_id, cmd, actor=actor, timeout=timeout)
        return {"success": result["exit_code"] == 0, "data": result["stdout"], "error": None}
    except asyncio.TimeoutError:
        return {"success": False, "data": None, "error": "Job timed out"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def _parse_grains(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        return {}
