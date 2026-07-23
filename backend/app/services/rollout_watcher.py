"""rollout_watcher.py — background watchers that resolve rollout Notifications.

A rollout-triggering write inserts a Notification(status="watching") and spawns a
watcher here. The watcher polls the namespace's rollout state until it is healthy or
failed (Kubernetes enforces the real deadline by flipping a Deployment to
ProgressDeadlineExceeded, which _rollout_state reports as "failed"), then resolves the
row and appends the outcome as a persisted assistant message. WATCH_MAX_SECONDS is
only a backstop above the cluster's own progressDeadlineSeconds."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Set

from app.core.datetimes import utcnow
from app.core.db import AsyncSessionLocal
from app.models.chat import ChatMessage
from app.models.notification import Notification
from app.services.k8s_service import k8s_service
from app.services.presweep import _rollout_state

logger = logging.getLogger(__name__)

WATCH_INTERVAL: float = 5.0
WATCH_MAX_SECONDS: float = 900.0

_tasks: Set[asyncio.Task] = set()
_watching_ids: Set[int] = set()


async def spawn(notification_id: int) -> None:
    """Idempotently start a background watcher for a notification row."""
    if notification_id in _watching_ids:
        return
    _watching_ids.add(notification_id)
    task = asyncio.create_task(watch(notification_id))
    _tasks.add(task)
    task.add_done_callback(lambda t: (_tasks.discard(t), _watching_ids.discard(notification_id)))


async def _resolve(notification_id: int, status: str, message: str) -> None:
    """Persist the terminal state on the row and append the outcome to the chat."""
    async with AsyncSessionLocal() as db:
        row = await db.get(Notification, notification_id)
        if not row:
            return
        row.status = status
        row.message = message
        row.resolved_at = utcnow()
        db.add(row)
        db.add(ChatMessage(
            conversation_id=row.conversation_id, role="assistant",
            content=message, message_type="text", token_count=len(message) // 4,
        ))
        await db.commit()


async def watch(notification_id: int) -> None:
    """Poll the rollout until healthy/failed, then resolve the row. Never raises."""
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(Notification, notification_id)
        if not row:
            return
        namespace, target = row.namespace, row.target

        core = k8s_service._get_api("CoreV1Api")
        apps = k8s_service._get_api("AppsV1Api")
        if core is None or apps is None:
            # mock mode / no cluster — nothing to watch, the write already happened
            await _resolve(notification_id, "succeeded", f"✅ {target} applied (no cluster to watch).")
            return

        deadline = time.monotonic() + WATCH_MAX_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(WATCH_INTERVAL)
            state, detail = await _rollout_state(core, apps, namespace)
            if state == "healthy":
                await _resolve(notification_id, "succeeded", f"✅ {target} is up — rollout complete.")
                return
            if state == "failed":
                reason = "; ".join(d.strip() for d in detail) or "rollout failed"
                await _resolve(notification_id, "failed", f"❌ {target} rollout failed: {reason}")
                return
        await _resolve(notification_id, "timed_out",
                       f"⏳ {target} is still not ready after {int(WATCH_MAX_SECONDS)}s — check it manually.")
    except Exception as e:  # a watcher failure must never crash the loop
        logger.warning("rollout_watcher.watch(%s) failed: %s", notification_id, e)
        try:
            await _resolve(notification_id, "failed", f"⚠️ Could not confirm the rollout: {e}")
        except Exception:
            pass


async def resume_pending() -> int:
    """Re-spawn a watcher for every notification still in 'watching' (call on startup)."""
    from sqlmodel import select
    async with AsyncSessionLocal() as db:
        rows = (await db.exec(
            select(Notification).where(Notification.status == "watching")
        )).all()
    for row in rows:
        await spawn(row.id)
    logger.info("rollout_watcher: resumed %d pending watcher(s)", len(rows))
    return len(rows)
