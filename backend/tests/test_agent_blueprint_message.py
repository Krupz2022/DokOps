# backend/tests/test_agent_blueprint_message.py
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


def test_blueprint_message_runs_and_replies(monkeypatch):
    msg = json.dumps({
        "type": "blueprint", "run_id": "r1", "test": True,
        "resources": [{"id": "a", "type": "cmd", "name": "echo hi"}], "sources": {},
    })
    ws = FakeWS([msg])

    async def drive():
        await agent.handle_messages(ws)  # processes inbound, then stops

    asyncio.get_event_loop().run_until_complete(drive())
    replies = [m for m in ws.sent if m.get("type") == "blueprint_result"]
    assert replies and replies[0]["run_id"] == "r1"
    assert replies[0]["results"][0]["id"] == "a"
    assert replies[0]["results"][0]["result"] is None  # test mode would-run
