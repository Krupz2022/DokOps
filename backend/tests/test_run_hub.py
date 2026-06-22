import asyncio
import pytest
from app.services.minion_service import RunHub


def test_subscribe_replays_backlog_then_tails():
    hub = RunHub()

    async def go():
        hub.publish("r1", {"kind": "resource_start", "id": "a"})
        hub.publish("r1", {"kind": "log", "id": "a", "line": "hello"})
        seen = []

        async def reader():
            async for ev in hub.subscribe("r1"):
                seen.append(ev)
        task = asyncio.ensure_future(reader())
        await asyncio.sleep(0.05)            # let backlog drain
        hub.publish("r1", {"kind": "log", "id": "a", "line": "world"})
        hub.publish("r1", {"kind": "done", "results": []})
        await asyncio.wait_for(task, timeout=1)
        return seen

    seen = asyncio.run(go())
    kinds = [e["kind"] for e in seen]
    assert kinds == ["resource_start", "log", "log", "done"]
    assert seen[1]["line"] == "hello" and seen[2]["line"] == "world"


def test_late_subscriber_gets_full_backlog():
    hub = RunHub()

    async def go():
        for i in range(3):
            hub.publish("r2", {"kind": "log", "id": "a", "line": str(i)})
        hub.publish("r2", {"kind": "done", "results": []})
        seen = [ev async for ev in hub.subscribe("r2")]   # subscribe AFTER done
        return seen

    seen = asyncio.run(go())
    assert [e.get("line") for e in seen if e["kind"] == "log"] == ["0", "1", "2"]
    assert seen[-1]["kind"] == "done"


def test_fan_out_two_subscribers():
    hub = RunHub()

    async def go():
        a, b = [], []

        async def reader(sink):
            async for ev in hub.subscribe("r3"):
                sink.append(ev)
        ta = asyncio.ensure_future(reader(a))
        tb = asyncio.ensure_future(reader(b))
        await asyncio.sleep(0.05)
        hub.publish("r3", {"kind": "log", "id": "a", "line": "x"})
        hub.publish("r3", {"kind": "done", "results": []})
        await asyncio.wait_for(asyncio.gather(ta, tb), timeout=1)
        return a, b

    a, b = asyncio.run(go())
    assert [e["kind"] for e in a] == ["log", "done"]
    assert [e["kind"] for e in b] == ["log", "done"]
