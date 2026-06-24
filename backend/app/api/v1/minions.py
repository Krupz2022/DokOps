import json
import logging
from datetime import datetime
from typing import Optional

from app.core.datetimes import utcnow

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_async_db, get_current_user, require_god_mode
from app.api import deps as _deps
from app.core.config import settings
from app.core.security import ALGORITHM
from app.services.blueprint_service import compile_blueprint
from app.models.blueprint import BlueprintRun, ResourceResult
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
    run_hub,
)
from app.services.service_discovery_service import parse_discovery_output, persist_discovery, DISCOVERY_COMMANDS
from app.services import live_resources

log = logging.getLogger(__name__)


class ServiceOverrideCreate(BaseModel):
    service_type: str
    install_type: str = "native"
    container_name: Optional[str] = None
    port: int


class PortainerConfigIn(BaseModel):
    base_url: str
    api_key: str
    endpoint_id: int = 1


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


@router.get("/{minion_id}/portainer")
async def get_portainer(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    cfg = await live_resources.get_portainer_config(minion_id, db)
    if not cfg:
        return {"configured": False, "base_url": None, "endpoint_id": None}
    return {"configured": True, "base_url": cfg.get("base_url"), "endpoint_id": cfg.get("endpoint_id")}


@router.put("/{minion_id}/portainer")
async def put_portainer(
    minion_id: str,
    body: PortainerConfigIn,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    await live_resources.set_portainer_config(minion_id, body.model_dump(), db)
    return {"saved": True}


@router.get("/{minion_id}/resources/services")
async def live_services(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    m = await db.get(Minion, minion_id)
    if not m:
        raise HTTPException(status_code=404, detail="Minion not found")
    if not manager.is_connected(minion_id):
        raise HTTPException(status_code=503, detail="Minion is not connected")
    try:
        grains = json.loads(m.grains or "{}")
    except (ValueError, TypeError):
        grains = {}
    os_id = grains.get("os", "")
    cmd = live_resources.services_command(os_id)
    # Trusted, code-controlled constant (not user input) — bypass the user allowlist.
    # The Windows form legitimately contains ';' inside @{N='Status';E={...}}, which the
    # allowlist's anti-chaining guard would otherwise reject.
    result = await manager.dispatch_job(minion_id, cmd, actor="ui_resources", timeout=30, god_mode=True)
    if result.get("exit_code", 0) != 0:
        raise HTTPException(status_code=502, detail=f"Service query failed: {result.get('stdout', '').strip()[:500]}")
    return {"services": live_resources.parse_services(os_id, result.get("stdout", ""))}


@router.get("/{minion_id}/resources/services/{name}/logs")
async def live_service_logs(
    minion_id: str,
    name: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    # Strict charset check: name is interpolated into the dispatched command.
    if not live_resources.valid_service_name(name):
        raise HTTPException(status_code=400, detail="Invalid service name")
    m = await db.get(Minion, minion_id)
    if not m:
        raise HTTPException(status_code=404, detail="Minion not found")
    if not manager.is_connected(minion_id):
        raise HTTPException(status_code=503, detail="Minion is not connected")
    try:
        grains = json.loads(m.grains or "{}")
    except (ValueError, TypeError):
        grains = {}
    os_id = grains.get("os", "")
    cmd = live_resources.service_logs_command(os_id, name)
    # Built from a validated name (no shell metachars) — trusted dispatch, bypasses allowlist.
    # Note: `systemctl status` exits non-zero for a stopped unit, so we don't treat exit_code
    # as an error here — the output itself is what the user wants to see.
    result = await manager.dispatch_job(minion_id, cmd, actor="ui_service_logs", timeout=30, god_mode=True)
    return {"output": result.get("stdout", "")}


@router.get("/{minion_id}/resources/docker")
async def live_docker(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    cfg = await live_resources.get_portainer_config(minion_id, db)
    if cfg:
        try:
            data = await live_resources.fetch_docker_resources(
                cfg["base_url"], cfg["api_key"], cfg["endpoint_id"]
            )
        except Exception as e:  # noqa: BLE001 — surface Portainer/network failure to UI
            raise HTTPException(status_code=502, detail=f"Portainer request failed: {e}")
        data["source"] = "portainer"
        return data

    # Fallback: no Portainer configured — query the Docker CLI directly through the agent.
    m = await db.get(Minion, minion_id)
    if not m:
        raise HTTPException(status_code=404, detail="Minion not found")
    if not manager.is_connected(minion_id):
        raise HTTPException(status_code=503, detail="Minion is not connected")
    try:
        grains = json.loads(m.grains or "{}")
    except (ValueError, TypeError):
        grains = {}
    if not grains.get("docker"):
        raise HTTPException(status_code=502, detail="Docker is not installed or not running on this host")
    # docker_cli_command() is a fixed constant (contains ';') — trusted dispatch, bypasses allowlist.
    result = await manager.dispatch_job(
        minion_id, live_resources.docker_cli_command(), actor="ui_resources", timeout=30, god_mode=True
    )
    data = live_resources.parse_docker_cli(result.get("stdout", ""))
    data["source"] = "agent"
    return data


# ── Blueprint endpoints ─────────────────────────────────────────────────────

@router.get("/blueprint/runs/{run_id}")
async def get_blueprint_run(
    run_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    run = await db.get(BlueprintRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    results = (await db.exec(select(ResourceResult).where(ResourceResult.run_id == run_id))).all()
    return {"run": run, "results": results}


@router.get("/blueprint/runs/{run_id}/stream")
async def stream_blueprint_run(run_id: str, token: Optional[str] = Query(None)):
    # EventSource can't set headers — authenticate via the token query param.
    if not token:
        raise HTTPException(status_code=401, detail="token required")
    try:
        jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="invalid token")

    import json as _json

    async def gen():
        async for event in run_hub.subscribe(run_id):
            yield f"data: {_json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{minion_id}/blueprint")
async def preview_blueprint(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    states, sources = await compile_blueprint(minion_id, db)
    return {"resources": states, "sources": sources}


@router.post("/{minion_id}/blueprint/run")
async def run_blueprint_endpoint(
    minion_id: str,
    body: dict,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    test = bool(body.get("test", True))
    if not test:
        # Apply path: enforce God Mode explicitly (dependency can't be conditional).
        if not _deps.is_god_mode_active(getattr(current_user, "id", 0)):
            raise HTTPException(status_code=403, detail="God Mode required to apply a blueprint")

    if not manager.is_connected(minion_id):
        raise HTTPException(status_code=503, detail="Minion is not connected")

    states, sources = await compile_blueprint(minion_id, db)

    # Optional: run an ordered subset of resources (UI selection + reorder).
    # Omitted/empty → run the full compiled set in compiled order (unchanged behaviour).
    only = body.get("resource_ids")
    if only:
        by_id = {s.get("id"): s for s in states}
        states = [by_id[rid] for rid in only if rid in by_id]
        if not states:
            raise HTTPException(status_code=400, detail="no matching resources to run")

    run = BlueprintRun(minion_id=minion_id, actor=current_user.username, test=test, status="running")
    db.add(run)
    if not test:
        db.add(AuditLog(
            actor=current_user.username,
            action="apply_blueprint",
            resource=f"minion/{minion_id}",
            result="SUCCESS",
            mode="GOD",
            source="SYSTEM",
        ))
    await db.commit()
    await db.refresh(run)

    try:
        await manager.dispatch_blueprint(minion_id, run.id, states, sources, test)
    except Exception as e:  # noqa: BLE001 — surface dispatch failure to caller
        raise HTTPException(status_code=500, detail=str(e))
    return {"run_id": run.id, "test": test}


@router.get("/{minion_id}/blueprint/runs")
async def list_blueprint_runs(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    return (await db.exec(select(BlueprintRun).where(BlueprintRun.minion_id == minion_id))).all()


# ── WebSocket ───────────────────────────────────────────────────────────────

@router.websocket("/ws/{minion_id}")
async def minion_websocket(minion_id: str, ws: WebSocket, token: Optional[str] = None, key: Optional[str] = None):
    # Reject immediately if no token provided — prevents unauthenticated minion impersonation
    if not token:
        await ws.close(code=1008, reason="Authentication required")
        return

    async with AsyncSessionLocal() as db:
        m = await db.get(Minion, minion_id)

        # Verify token: must match the global auto-accept key hash or the minion's own stored hash
        token_valid = False
        key_hash = await get_auto_accept_key_hash()
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
        m.last_seen = utcnow()

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

    if key and status == "active":
        from app.services.minion_service import apply_enrollment_key
        try:
            await apply_enrollment_key(minion_id, key)
        except Exception as e:  # noqa: BLE001 — provisioning must never break the connection
            log.warning("enrollment-key provisioning failed for %s: %s", minion_id, e)

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
                        m.last_seen = utcnow()
                        db.add(m)
                        await db.commit()
                org_name = grains_data.get("org", "").strip()
                env_name = grains_data.get("env", "").strip()
                # Only assign active (approved) minions, and only to pre-existing
                # orgs/groups — never auto-create from untrusted minion-supplied data
                if status == "active" and org_name and env_name:
                    from app.services.patch_service import find_existing_membership
                    await find_existing_membership(minion_id, org_name, env_name)

            elif msg_type == "heartbeat":
                async with AsyncSessionLocal() as db:
                    m = await db.get(Minion, minion_id)
                    if m:
                        m.last_seen = utcnow()
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
                await manager.handle_done(data["job_id"], data.get("exit_code", -1))

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
                await ingest_scan(minion_id, packages, scanned_at)

            elif msg_type == "pong":
                async with AsyncSessionLocal() as db:
                    m = await db.get(Minion, minion_id)
                    if m:
                        m.last_seen = utcnow()
                        db.add(m)
                        await db.commit()

            elif msg_type == "blueprint_event":
                await manager.handle_blueprint_event(data["run_id"], data.get("event", {}))

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
        await manager.fail_running_blueprints(minion_id)
        log.info("Minion %s disconnected", minion_id)
