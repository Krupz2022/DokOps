import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_async_db, get_current_user, get_db, require_god_mode
from app.core.db import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.minion import Minion, MinionJob
from app.models.patch import MinionGroupMember, MinionPatch
from app.models.service_diag import DiscoveredService
from app.models.user import User
from app.services.minion_service import (
    get_auto_accept_key_hash,
    hash_token,
    verify_token,
    is_read_allowed,
    manager,
)
from app.services.service_discovery_service import parse_discovery_output, persist_discovery, DISCOVERY_COMMANDS

log = logging.getLogger(__name__)


class ServiceOverrideCreate(BaseModel):
    service_type: str
    install_type: str = "native"
    container_name: Optional[str] = None
    port: int


router = APIRouter()


# ── REST ────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_minions(
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    return (await db.exec(select(Minion))).all()


@router.get("/{minion_id}")
async def get_minion(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    m = await db.get(Minion, minion_id)
    if not m:
        raise HTTPException(status_code=404, detail="Minion not found")
    return m


@router.post("/{minion_id}/approve")
async def approve_minion(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_god_mode),
):
    m = await db.get(Minion, minion_id)
    if not m:
        raise HTTPException(status_code=404, detail="Minion not found")
    m.status = "active"
    m.approved_by = current_user.username
    db.add(m)
    db.add(AuditLog(
        actor=current_user.username,
        action="approve_minion",
        resource=f"minion/{minion_id}",
        result="SUCCESS",
        mode="GOD",
        source="SYSTEM",
    ))
    await db.commit()
    await manager.notify_approved(minion_id)
    return {"approved": True}


@router.delete("/{minion_id}")
async def delete_minion(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_god_mode),
):
    m = await db.get(Minion, minion_id)
    if not m:
        raise HTTPException(status_code=404, detail="Minion not found")
    # Cascade: remove patches and group memberships (SQLite FK enforcement is off)
    for patch in (await db.exec(select(MinionPatch).where(MinionPatch.minion_id == minion_id))).all():
        await db.delete(patch)
    for membership in (await db.exec(select(MinionGroupMember).where(MinionGroupMember.minion_id == minion_id))).all():
        await db.delete(membership)
    await db.delete(m)
    db.add(AuditLog(
        actor=current_user.username,
        action="delete_minion",
        resource=f"minion/{minion_id}",
        result="SUCCESS",
        mode="GOD",
        source="SYSTEM",
    ))
    await db.commit()
    return {"deleted": True}


@router.post("/{minion_id}/jobs")
async def run_job(
    minion_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
):
    from app.services.minion_service import manager
    cmd = body.get("command", "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="command is required")

    # Probe dispatch: __probe__:service_type:probe_name
    if cmd.startswith("__probe__:"):
        parts = cmd.split(":", 2)
        if len(parts) != 3:
            raise HTTPException(status_code=400, detail="Invalid probe command format")
        _, service_type, probe_name = parts
        from app.tools.middleware_tools import run_service_probe  # lazy — avoids circular at module load time
        result = await run_service_probe(minion_id, service_type, probe_name)
        stdout = result.get("data") or result.get("error") or ""
        exit_code = 0 if result.get("success") else 1
        return {"stdout": stdout, "exit_code": exit_code}

    # Commands outside the safe read-only allowlist require God Mode
    if not is_read_allowed(cmd):
        from app.core.god_mode import is_god_mode_active
        if not is_god_mode_active(getattr(current_user, "id", 0)):
            raise HTTPException(
                status_code=403,
                detail="Command not in safe allowlist — enable God Mode to run arbitrary commands on minions",
            )

    if not manager.is_connected(minion_id):
        raise HTTPException(status_code=503, detail="Minion is not connected")
    try:
        # god_mode=True: allowlist already enforced above; pass through to avoid double-check
        result = await manager.dispatch_job(minion_id, cmd, actor=body.get("actor", "ui"), timeout=60, god_mode=True)
        return {"stdout": result["stdout"], "exit_code": result["exit_code"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{minion_id}/jobs")
async def list_jobs(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    return (await db.exec(select(MinionJob).where(MinionJob.minion_id == minion_id))).all()


@router.get("/{minion_id}/jobs/{job_id}")
async def get_job(
    minion_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    j = await db.get(MinionJob, job_id)
    if not j or j.minion_id != minion_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return j


@router.post("/patches/scan-all")
async def trigger_all_patch_scans(
    _: User = Depends(get_current_user),
):
    """Ask all connected minions to run a fresh patch scan."""
    connected = list(manager._connections.keys())
    for minion_id in connected:
        ws = manager._connections.get(minion_id)
        if ws:
            try:
                await ws.send_json({"type": "scan_patches"})
            except Exception:
                pass
    return {"triggered": len(connected)}


@router.post("/{minion_id}/patches/scan")
async def trigger_patch_scan(
    minion_id: str,
    _: User = Depends(get_current_user),
):
    """Ask the minion to run a fresh patch scan immediately."""
    if not manager.is_connected(minion_id):
        raise HTTPException(status_code=503, detail="Minion not connected")
    ws = manager._connections.get(minion_id)
    if ws:
        await ws.send_json({"type": "scan_patches"})
    return {"triggered": True}


@router.get("/{minion_id}/services")
async def list_services(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    if not await db.get(Minion, minion_id):
        raise HTTPException(status_code=404, detail="Minion not found")
    return (await db.exec(select(DiscoveredService).where(DiscoveredService.minion_id == minion_id))).all()


@router.post("/{minion_id}/services/discover")
async def trigger_discovery(
    minion_id: str,
    _: User = Depends(get_current_user),
):
    if not manager.is_connected(minion_id):
        raise HTTPException(status_code=503, detail="Minion not connected")
    ws = manager._connections.get(minion_id)
    if ws:
        await ws.send_json({"type": "discover_services"})
    return {"triggered": True}


@router.post("/{minion_id}/services")
async def add_service_override(
    minion_id: str,
    body: ServiceOverrideCreate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    svc = DiscoveredService(
        minion_id=minion_id,
        service_type=body.service_type,
        install_type=body.install_type,
        container_name=body.container_name,
        port=body.port,
        overridden=True,
    )
    db.add(svc)
    await db.commit()
    await db.refresh(svc)
    return svc


@router.delete("/{minion_id}/services/{service_id}")
async def delete_service_override(
    minion_id: str,
    service_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    svc = await db.get(DiscoveredService, service_id)
    if not svc or svc.minion_id != minion_id:
        raise HTTPException(status_code=404, detail="Service not found")
    if not svc.overridden:
        raise HTTPException(status_code=400, detail="Cannot delete auto-detected service; trigger a new discovery sweep instead")
    await db.delete(svc)
    await db.commit()
    return {"deleted": True}


# ── WebSocket ───────────────────────────────────────────────────────────────

@router.websocket("/ws/{minion_id}")
async def minion_websocket(minion_id: str, ws: WebSocket, token: Optional[str] = None):
    # Reject immediately if no token provided — prevents unauthenticated minion impersonation
    if not token:
        await ws.close(code=1008, reason="Authentication required")
        return

    async with AsyncSessionLocal() as db:
        m = await db.get(Minion, minion_id)

        # Verify token: must match the global auto-accept key hash or the minion's own stored hash
        token_valid = False
        key_hash = get_auto_accept_key_hash()
        if key_hash and verify_token(token, key_hash):
            token_valid = True
        elif m and m.token_hash and verify_token(token, m.token_hash):
            token_valid = True

        if not token_valid:
            await ws.close(code=1008, reason="Invalid token")
            return

        await manager.connect(minion_id, ws)

        if not m:
            m = Minion(id=minion_id, hostname=minion_id, status="pending")
        m.last_seen = datetime.utcnow()

        # Auto-accept if the global auto-accept key matched
        if key_hash and verify_token(token, key_hash):
            m.status = "active"
            m.token_hash = key_hash

        db.add(m)
        await db.commit()
        status = m.status

    await ws.send_json({"type": "welcome", "minion_id": minion_id, "status": status})
    if status == "active":
        await ws.send_json({"type": "discover_services"})

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "grains":
                grains_data = data.get("data", {})
                async with AsyncSessionLocal() as db:
                    m = await db.get(Minion, minion_id)
                    if m:
                        m.hostname = grains_data.get("hostname", m.hostname)
                        m.grains = json.dumps(grains_data)
                        m.last_seen = datetime.utcnow()
                        db.add(m)
                        await db.commit()
                org_name = grains_data.get("org", "").strip()
                env_name = grains_data.get("env", "").strip()
                # Only assign active (approved) minions, and only to pre-existing
                # orgs/groups — never auto-create from untrusted minion-supplied data
                if status == "active" and org_name and env_name:
                    from app.services.patch_service import find_existing_membership
                    find_existing_membership(minion_id, org_name, env_name)

            elif msg_type == "heartbeat":
                async with AsyncSessionLocal() as db:
                    m = await db.get(Minion, minion_id)
                    if m:
                        m.last_seen = datetime.utcnow()
                        if m.status == "offline":
                            m.status = "active"
                        # Merge live metrics into grains so the UI can display them
                        try:
                            g = json.loads(m.grains or "{}")
                        except Exception:
                            g = {}
                        for key in ("cpu_pct", "mem_pct", "disk_pct", "uptime_s"):
                            if key in data:
                                g[key] = data[key]
                        m.grains = json.dumps(g)
                        db.add(m)
                        await db.commit()

            elif msg_type == "chunk":
                manager.handle_chunk(data["job_id"], data.get("data", ""))

            elif msg_type == "done":
                manager.handle_done(data["job_id"], data.get("exit_code", -1))

            elif msg_type == "patches":
                from app.services.patch_service import ingest_scan
                scan_data = data.get("data", {})
                packages = scan_data.get("packages", [])
                scanned_at_str = scan_data.get("scanned_at")
                scanned_at = None
                if scanned_at_str:
                    try:
                        scanned_at = datetime.fromisoformat(scanned_at_str.replace("Z", "+00:00"))
                    except Exception:
                        pass
                ingest_scan(minion_id, packages, scanned_at)

            elif msg_type == "pong":
                async with AsyncSessionLocal() as db:
                    m = await db.get(Minion, minion_id)
                    if m:
                        m.last_seen = datetime.utcnow()
                        db.add(m)
                        await db.commit()

            elif msg_type == "discover_services_result":
                platform_name = data.get("platform", "linux")
                if platform_name == "windows":
                    from app.services.service_discovery_service import parse_discovery_output_windows
                    services = parse_discovery_output_windows(
                        minion_id,
                        data.get("netstat", ""),
                        data.get("services", ""),
                        data.get("docker", ""),
                    )
                else:
                    services = parse_discovery_output(
                        minion_id,
                        data.get("ss", ""),
                        data.get("systemctl", ""),
                        data.get("docker", ""),
                    )
                async with AsyncSessionLocal() as db:
                    await persist_discovery(minion_id, services, db)
                log.info("Minion %s discovery (%s): found %d services", minion_id, platform_name, len(services))

    except WebSocketDisconnect:
        manager.disconnect(minion_id)
        async with AsyncSessionLocal() as db:
            m = await db.get(Minion, minion_id)
            if m:
                m.status = "offline"
                db.add(m)
                await db.commit()
        log.info("Minion %s disconnected", minion_id)
