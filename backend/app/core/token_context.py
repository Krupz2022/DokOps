from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from datetime import datetime
from typing import Optional

_log = logging.getLogger(__name__)

ai_user_id: ContextVar[Optional[int]] = ContextVar("ai_user_id", default=None)
ai_source: ContextVar[str] = ContextVar("ai_source", default="unknown")

_token_queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)


def set_token_context(user_id: Optional[int], source: str) -> None:
    ai_user_id.set(user_id)
    ai_source.set(source)


async def push_token_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    """Non-blocking enqueue. Drops the record if the queue is full rather than blocking."""
    if input_tokens == 0 and output_tokens == 0:
        return
    try:
        _token_queue.put_nowait({
            "user_id": ai_user_id.get(),
            "source": ai_source.get(),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "created_at": datetime.utcnow(),
        })
    except asyncio.QueueFull:
        _log.warning("token_context: queue full, dropping token record")


async def drain_token_queue() -> None:
    """Background coroutine: drain queue every 2 s and batch-insert into AITokenUsage."""
    from app.core.db import AsyncSessionLocal
    from app.models.analytics import AITokenUsage

    while True:
        await asyncio.sleep(2)
        batch = []
        while not _token_queue.empty():
            try:
                batch.append(_token_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not batch:
            continue
        try:
            async with AsyncSessionLocal() as db:
                for rec in batch:
                    db.add(AITokenUsage(**rec))
                await db.commit()
        except Exception as exc:
            _log.warning("drain_token_queue: DB write failed: %s", exc)
