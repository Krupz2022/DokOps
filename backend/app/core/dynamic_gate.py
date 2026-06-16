# backend/app/core/dynamic_gate.py
"""Async concurrency limiter with a runtime-adjustable bound.

Unlike asyncio.Semaphore, the limit is not fixed at construction: it is read
from `limit_provider()` on every acquisition, so changing the underlying
setting takes effect for subsequent acquirers without recreating the gate.
Waiters queue (FIFO-ish via Condition) and are never dropped.
"""
import asyncio
from typing import Callable


class DynamicGate:
    def __init__(self, limit_provider: Callable[[], int]) -> None:
        self._limit_provider = limit_provider
        self._active = 0
        self._cond = asyncio.Condition()

    @property
    def active(self) -> int:
        return self._active

    async def acquire(self) -> None:
        async with self._cond:
            await self._cond.wait_for(lambda: self._active < max(1, self._limit_provider()))
            self._active += 1

    async def release(self) -> None:
        # release is async because acquiring the Condition lock requires awaiting it.
        # The only intended caller is __aexit__, which awaits correctly.
        # notify_all (not notify) is intentional: a runtime limit increase can open
        # several slots at once, so every waiter must re-check its predicate.
        async with self._cond:
            if self._active > 0:
                self._active -= 1
            self._cond.notify_all()

    async def __aenter__(self) -> "DynamicGate":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.release()
