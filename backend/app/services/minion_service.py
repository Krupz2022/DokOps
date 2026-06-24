"""
minion_service.py — WebSocket connection manager and helpers for the DokOps Minion feature.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re as _re
from datetime import datetime, timedelta

from app.core.datetimes import utcnow
from typing import Optional
from uuid import uuid4

from fastapi import WebSocket
from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.minion import Minion, MinionJob

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Read-only command allowlist
# ---------------------------------------------------------------------------

_READ_PREFIXES = (
    "ss -tlnp",
    "docker ps",
    "docker inspect",
    "docker logs",
    "docker stats",
    "docker info",
    "docker images",
    "docker network",
    "docker volume",
    "systemctl status",
    "systemctl list-units",
    "Get-Service ",
    "Get-Service\n",
    "journalctl",
    "df ",
    "df\n",
    "free ",
    "free\n",
    "top -bn",
    "uptime",
    "hostname",
    "ps aux",
    "ps -aux",
    "cat /etc/os-release",
    "ansible --version",
    "ansible-inventory",
    "cat /var/log/",
)


# Statement-chaining / command-substitution tokens. A safe read prefix must not be
# followed by one of these, or it could smuggle a second command past the allowlist
# (e.g. "Get-Service | x; Remove-Item ..." or "docker ps; rm -rf /"). A single pipe is
# allowed — several legitimate read commands pipe into grep/Where-Object.
_CHAIN_TOKENS = (";", "&&", "||", "`", "$(", "&\n")


def is_read_allowed(cmd: str) -> bool:
    """Return True when *cmd* starts with a safe read-only prefix and does not chain
    a second statement past it."""
    if not cmd.startswith(_READ_PREFIXES):
        return False
    return not any(tok in cmd for tok in _CHAIN_TOKENS)


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class MinionConnectionManager:
    """In-memory registry of live minion WebSocket connections with job dispatch."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._pending_jobs: dict[str, asyncio.Future] = {}
        self._job_chunks: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, minion_id: str, ws: WebSocket) -> None:
        """Accept the WebSocket and register the minion."""
        await ws.accept()
        self._connections[minion_id] = ws

    def disconnect(self, minion_id: str) -> None:
        """Remove a minion from the active connection registry."""
        self._connections.pop(minion_id, None)

    def is_connected(self, minion_id: str) -> bool:
        """Return True when the minion has an active WebSocket connection."""
        return minion_id in self._connections

    # ------------------------------------------------------------------
    # Streaming result assembly
    # ------------------------------------------------------------------

    def handle_chunk(self, job_id: str, data: str) -> None:
        """Append a stdout chunk to the in-flight job buffer."""
        if job_id in self._job_chunks:
            self._job_chunks[job_id].append(data)

    async def handle_done(self, job_id: str, exit_code: int) -> None:
        """Persist exit code to DB and resolve the pending future (if any)."""
        stdout = "".join(self._job_chunks.pop(job_id, []))
        # DB write happens regardless of whether the HTTP caller is still alive
        async with AsyncSessionLocal() as db:
            job = await db.get(MinionJob, job_id)
            if job:
                job.status = "done" if exit_code == 0 else "failed"
                job.exit_code = exit_code
                job.completed_at = utcnow()
                db.add(job)
                await db.commit()
        # Resolve future only if caller is still waiting
        if job_id in self._pending_jobs:
            self._pending_jobs.pop(job_id).set_result({"stdout": stdout, "exit_code": exit_code})

    # ------------------------------------------------------------------
    # Job dispatch
    # ------------------------------------------------------------------

    async def dispatch_job(
        self,
        minion_id: str,
        cmd: str,
        actor: str,
        timeout: int = 60,
        god_mode: bool = False,
    ) -> dict:
        """
        Send a command to a connected minion and wait for the result.

        Raises
        ------
        RuntimeError
            When no live connection exists for *minion_id*.
        asyncio.TimeoutError
            When the minion does not reply within *timeout* + 5 seconds.
        """
        ws = self._connections.get(minion_id)
        if not ws:
            raise RuntimeError(f"Minion {minion_id} is not connected")

        # Enforce read-only allowlist unless god_mode is explicitly granted.
        # Internal callers (patch, AI) that run destructive commands pass god_mode=True.
        if not god_mode and not is_read_allowed(cmd):
            raise PermissionError(
                f"Command not in safe read-only allowlist. "
                "Pass god_mode=True for destructive operations."
            )

        timeout = int(timeout)
        job_id = str(uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_jobs[job_id] = future
        self._job_chunks[job_id] = []

        async with AsyncSessionLocal() as db:
            job = MinionJob(
                id=job_id,
                minion_id=minion_id,
                command=redact_command(cmd),  # never store plaintext passwords
                actor=actor,
                status="running",
            )
            db.add(job)
            await db.commit()

        try:
            await ws.send_json(
                {"type": "job", "job_id": job_id, "cmd": cmd, "timeout": timeout}
            )
            result = await asyncio.wait_for(future, timeout=timeout + 5)
        except asyncio.TimeoutError:
            self._pending_jobs.pop(job_id, None)
            self._job_chunks.pop(job_id, None)
            async with AsyncSessionLocal() as db:
                job = await db.get(MinionJob, job_id)
                if job:
                    job.status = "failed"
                    job.stderr = "timeout"
                    job.completed_at = utcnow()
                    db.add(job)
                    await db.commit()
            raise

        # handle_done already persisted status/exit_code — no DB write needed here
        return result

    # ------------------------------------------------------------------
    # Control messages
    # ------------------------------------------------------------------

    async def send_ping(self, minion_id: str) -> None:
        """Send a keepalive ping to the minion; disconnect on any send error."""
        ws = self._connections.get(minion_id)
        if ws:
            try:
                await ws.send_json({"type": "ping"})
            except Exception:
                self.disconnect(minion_id)

    async def notify_approved(self, minion_id: str) -> None:
        """Notify a pending minion that it has been approved."""
        ws = self._connections.get(minion_id)
        if ws:
            try:
                await ws.send_json({"type": "approved"})
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Blueprint dispatch
    # ------------------------------------------------------------------

    async def dispatch_blueprint(
        self, minion_id: str, run_id: str, states: list, sources: dict, test: bool,
    ) -> None:
        """Fire-and-forget: send the blueprint to the agent; results stream back via events."""
        ws = self._connections.get(minion_id)
        if not ws:
            raise RuntimeError(f"Minion {minion_id} is not connected")
        await ws.send_json({
            "type": "blueprint", "run_id": run_id, "test": test,
            "resources": states, "sources": sources,
        })

    async def handle_blueprint_event(self, run_id: str, event: dict) -> None:
        run_hub.publish(run_id, event)
        kind = event.get("kind")
        if kind == "done":
            await self._persist_blueprint_results(run_id, event.get("results", []))
        elif kind == "error":
            await self._mark_run_failed(run_id)

    async def _persist_blueprint_results(self, run_id: str, results: list) -> None:
        import json as _json
        from app.models.blueprint import BlueprintRun, ResourceResult
        any_failed = any(r.get("result") is False for r in results)
        async with AsyncSessionLocal() as db:
            for r in results:
                db.add(ResourceResult(
                    run_id=run_id,
                    resource_id=r.get("id", "?"),
                    result=r.get("result"),
                    changes=_json.dumps(r.get("changes", {})),
                    comment=r.get("comment", ""),
                    output=r.get("output", ""),
                ))
            run = await db.get(BlueprintRun, run_id)
            if run:
                run.status = "failed" if any_failed else "done"
                run.completed_at = utcnow()
                db.add(run)
            await db.commit()

    async def _mark_run_failed(self, run_id: str) -> None:
        from app.models.blueprint import BlueprintRun
        async with AsyncSessionLocal() as db:
            run = await db.get(BlueprintRun, run_id)
            if run and run.status == "running":
                run.status = "failed"
                run.completed_at = utcnow()
                db.add(run)
                await db.commit()

    async def fail_running_blueprints(self, minion_id: str) -> None:
        from app.models.blueprint import BlueprintRun
        from sqlmodel import select
        async with AsyncSessionLocal() as db:
            runs = (await db.exec(select(BlueprintRun).where(
                BlueprintRun.minion_id == minion_id, BlueprintRun.status == "running"))).all()
            for run in runs:
                run.status = "failed"
                run.completed_at = utcnow()
                db.add(run)
                run_hub.publish(run.id, {"kind": "error", "message": "minion disconnected"})
            if runs:
                await db.commit()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

async def get_auto_accept_key_hash() -> Optional[str]:
    """Return the stored SHA-256 hash of the minion auto-accept key, or None."""
    async with AsyncSessionLocal() as db:
        from app.models.setting import SystemSetting  # local import avoids circular deps
        row = (await db.exec(
            select(SystemSetting).where(
                SystemSetting.key == "minion_auto_accept_key"
            )
        )).first()
        return row.value if row else None


import bcrypt as _bcrypt


def hash_token(token: str) -> str:
    """Return a bcrypt hash of *token*. Use verify_token() to compare.
    NOTE: produces a different hash on each call (salted). Never compare with ==."""
    return _bcrypt.hashpw(token.encode(), _bcrypt.gensalt()).decode()


def verify_token(token: str, stored_hash: str) -> bool:
    """Return True if *token* matches the stored bcrypt hash.
    Falls back to SHA-256 comparison for hashes created before the bcrypt upgrade."""
    try:
        # Modern bcrypt hashes start with $2b$
        if stored_hash.startswith("$2"):
            return _bcrypt.checkpw(token.encode(), stored_hash.encode())
        # Legacy SHA-256 fallback (allows existing tokens to keep working)
        return hashlib.sha256(token.encode()).hexdigest() == stored_hash
    except Exception:
        return False


def redact_command(cmd: str) -> str:
    """Replace credential values in a shell command string with [REDACTED].
    Prevents service passwords from being stored in the MinionJob command field."""
    result = cmd
    result = _re.sub(r"(--password=)'[^']*'", r"\1'[REDACTED]'", result)
    result = _re.sub(r"(--password )'[^']*'", r"\1'[REDACTED]'", result)
    result = _re.sub(r"(-p )'[^']*'", r"\1'[REDACTED]'", result)
    result = _re.sub(r"(PGPASSWORD=)\S+", r"\1[REDACTED]", result)
    return result


async def mark_offline_loop() -> None:
    """
    Background task: mark minions as *offline* when last_seen is older than 90 s.
    Runs every 30 seconds for life of the process.
    """
    while True:
        await asyncio.sleep(30)
        threshold = utcnow() - timedelta(seconds=90)
        async with AsyncSessionLocal() as db:
            stale = (await db.exec(
                select(Minion).where(
                    Minion.status == "active",
                    Minion.last_seen < threshold,
                )
            )).all()
            for m in stale:
                m.status = "offline"
                db.add(m)
            if stale:
                await db.commit()


# ---------------------------------------------------------------------------
# Live run event relay (blueprint streaming)
# ---------------------------------------------------------------------------

_TERMINAL = ("done", "error")


class RunHub:
    """In-memory per-run event buffer + fan-out to live SSE subscribers."""

    MAX_LOG_EVENTS = 5000
    EVICT_AFTER_S = 60

    def __init__(self) -> None:
        self._buffers: dict[str, list[dict]] = {}
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def publish(self, run_id: str, event: dict) -> None:
        buf = self._buffers.setdefault(run_id, [])
        if event.get("kind") == "log":
            log_count = sum(1 for e in buf if e.get("kind") == "log")
            if log_count < self.MAX_LOG_EVENTS:
                buf.append(event)
            elif log_count == self.MAX_LOG_EVENTS:
                buf.append({"kind": "log", "id": event.get("id"), "line": "… output truncated …"})
        else:
            buf.append(event)
        for q in list(self._subs.get(run_id, ())):
            q.put_nowait(event)
        if event.get("kind") in _TERMINAL:
            try:
                asyncio.get_running_loop().call_later(self.EVICT_AFTER_S, self._evict, run_id)
            except RuntimeError:
                pass  # no loop (sync context) — buffer stays until process exit

    async def subscribe(self, run_id: str):
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(run_id, set()).add(q)
        backlog = list(self._buffers.get(run_id, []))  # snapshot (sync, atomic vs publish)
        try:
            for event in backlog:
                yield event
                if event.get("kind") in _TERMINAL:
                    return
            while True:
                event = await q.get()
                yield event
                if event.get("kind") in _TERMINAL:
                    return
        finally:
            subs = self._subs.get(run_id)
            if subs:
                subs.discard(q)

    def _evict(self, run_id: str) -> None:
        self._buffers.pop(run_id, None)
        if not self._subs.get(run_id):
            self._subs.pop(run_id, None)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

manager = MinionConnectionManager()
run_hub = RunHub()


# ---------------------------------------------------------------------------
# Enrollment helper
# ---------------------------------------------------------------------------

async def apply_enrollment_key(minion_id: str, key_value: str) -> None:
    """Provisioning side of enrollment (auth already done): match the activation key,
    place the minion in its group, and bootstrap its blueprints ONCE."""
    from app.models.activation_key import ActivationKey
    from app.models.patch import MinionGroupMember
    from app.models.minion import Minion
    from app.models.blueprint import BlueprintRun
    from app.models.audit import AuditLog
    from app.services.blueprint_service import compile_key_blueprints

    async with AsyncSessionLocal() as db:
        candidates = (await db.exec(select(ActivationKey).where(ActivationKey.enabled == True))).all()  # noqa: E712
        key = next((k for k in candidates if verify_token(key_value, k.value_hash)), None)
        if key is None:
            _log.info("enroll: minion %s sent an unknown/disabled activation key", minion_id)
            return

        # authoritative placement (idempotent)
        if key.group_id and not await db.get(MinionGroupMember, (key.group_id, minion_id)):
            db.add(MinionGroupMember(group_id=key.group_id, minion_id=minion_id))
            await db.commit()

        minion = await db.get(Minion, minion_id)
        if not (key.run_on_attach and minion and not minion.bootstrapped):
            return

        resources, sources = await compile_key_blueprints(key.id, db)
        run = BlueprintRun(minion_id=minion_id, actor=f"enroll:{key.name}", test=False, status="running")
        db.add(run)
        db.add(AuditLog(actor=f"enroll:{key.name}", action="bootstrap_blueprint",
                        resource=f"minion/{minion_id}", result="SUCCESS", mode="GOD", source="SYSTEM"))
        minion.bootstrapped = True
        db.add(minion)
        await db.commit()
        await db.refresh(run)

    try:
        await manager.dispatch_blueprint(minion_id, run.id, resources, sources, test=False)
    except Exception as e:  # noqa: BLE001 — agent may have dropped; bootstrap is best-effort
        _log.warning("enroll bootstrap dispatch failed for %s: %s", minion_id, e)
