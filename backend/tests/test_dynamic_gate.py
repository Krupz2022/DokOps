# backend/tests/test_dynamic_gate.py
import asyncio
import pytest

from app.core.dynamic_gate import DynamicGate


@pytest.mark.asyncio
async def test_gate_bounds_peak_concurrency():
    limit = 3
    gate = DynamicGate(lambda: limit)
    active = 0
    peak = 0

    async def worker():
        nonlocal active, peak
        async with gate:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)  # hold the slot
            active -= 1

    await asyncio.gather(*(worker() for _ in range(12)))
    assert peak <= limit
    assert active == 0
    assert gate.active == 0


@pytest.mark.asyncio
async def test_gate_releases_slot_on_exception():
    gate = DynamicGate(lambda: 1)

    with pytest.raises(ValueError):
        async with gate:
            raise ValueError("boom")

    # Slot must be freed despite the exception.
    assert gate.active == 0
    async with gate:
        assert gate.active == 1


@pytest.mark.asyncio
async def test_gate_honours_runtime_limit_change():
    current = {"limit": 1}
    gate = DynamicGate(lambda: current["limit"])
    active = 0
    peak = 0

    async def worker():
        nonlocal active, peak
        async with gate:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1

    tasks = [asyncio.create_task(worker()) for _ in range(6)]
    await asyncio.sleep(0.01)   # let one worker grab the only slot
    current["limit"] = 4        # widen the gate at runtime
    await asyncio.gather(*tasks)
    assert peak <= 4
    assert peak >= 2            # proves the runtime widening took effect
