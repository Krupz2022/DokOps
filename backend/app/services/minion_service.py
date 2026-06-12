"""
minion_service.py — WebSocket connection manager and helpers for the DokOps Minion feature.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re as _re
from datetime import datetime, timedelta
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


def is_read_allowed(cmd: str) -> bool:
    """Return True when *cmd* starts with one of the safe read-only prefixes."""
    return cmd.startswith(_READ_PREFIXES)


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
                job.completed_at = datetime.utcnow()
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
                    job.completed_at = datetime.utcnow()
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
        threshold = datetime.utcnow() - timedelta(seconds=90)
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
# Module-level singleton
# ---------------------------------------------------------------------------

manager = MinionConnectionManager()
