import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import agent  # noqa: E402


class FakeWS:
    def __init__(self, inbound):
        self._inbound = inbound
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))

    def __aiter__(self):
        async def gen():
            for m in self._inbound:
                yield m
        return gen()


def test_blueprint_message_streams_events_and_done():
    msg = json.dumps({
        "type": "blueprint", "run_id": "r1", "test": False,
        "resources": [{"id": "c", "type": "cmd", "name": "echo live-output"}], "sources": {},
    })
    ws = FakeWS([msg])

    async def drive():
        await agent.handle_messages(ws)
        for _ in range(50):                # allow the background run + threadsafe sends to flush
            await asyncio.sleep(0.02)
            if any(m.get("event", {}).get("kind") == "done" for m in ws.sent):
                break

    asyncio.run(drive())
    events = [m["event"] for m in ws.sent if m.get("type") == "blueprint_event" and m.get("run_id") == "r1"]
    kinds = [e["kind"] for e in events]
    assert "resource_start" in kinds
    assert any(e["kind"] == "log" and "live-output" in e.get("line", "") for e in events)
    assert kinds[-1] == "done"
    done = events[-1]
    assert done["results"][0]["result"] is True
