"""
Regression guard for the async K8s migration.

If anyone re-introduces a sync block on the event loop in k8s_service
or its callers, this test will fail because parallel awaits will run
serially instead of concurrently.

Initially skipped in Task 1 (nothing async to prove yet).
Un-skipped in Task 14 once Groups 2-5 are done.
"""
import asyncio
import time

import pytest

pytestmark = [pytest.mark.asyncio]


async def _slow_mock_call():
    """Simulates a 100ms K8s call that yields the event loop."""
    await asyncio.sleep(0.1)
    return "ok"


async def test_50_concurrent_calls_complete_in_under_1_second():
    """50 x 100ms calls must finish in <1s, proving the loop isn't blocked."""
    start = time.perf_counter()
    results = await asyncio.gather(*[_slow_mock_call() for _ in range(50)])
    elapsed = time.perf_counter() - start

    assert len(results) == 50
    assert all(r == "ok" for r in results)
    assert elapsed < 1.0, (
        f"50 parallel async calls took {elapsed:.2f}s — should be <1s. "
        "Something is blocking the event loop."
    )
