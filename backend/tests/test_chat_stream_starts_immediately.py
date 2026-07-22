"""The chat SSE stream must emit its first event before any slow AI work.

Regression: runbook auto-matching (a full LLM round-trip) ran in the endpoint
before StreamingResponse was returned, so response headers — and every step
event — were withheld until the whole agent run had finished. It only showed up
once runbooks existed in the DB, because match_runbook_logic returns early when
there are none.
"""
import asyncio
import time

import pytest

pytestmark = pytest.mark.asyncio

SLOW = 1.0  # stand-in for the runbook matcher's LLM call


async def _drain(gen, budget):
    """Collect events, recording when each arrived."""
    out = []
    start = time.perf_counter()
    async for chunk in gen:
        out.append((time.perf_counter() - start, chunk))
        if len(out) >= budget:
            break
    # Deliberately not closing the generator: its finally block opens a real DB
    # session to persist the run, which hangs with no database here. The stray
    # "coroutine aclose was never awaited" warning is the cost of that.
    return out


async def test_first_event_precedes_the_runbook_llm_call(monkeypatch):
    from app.api.v1 import chat

    def slow_match(query):
        time.sleep(SLOW)  # sync + slow, exactly like the real one
        return {"matched_runbook_id": None, "confidence": "none"}

    monkeypatch.setattr(
        "app.services.runbook_service.match_runbook_logic", slow_match, raising=False
    )

    async def fake_loop(*args, **kwargs):
        yield {"type": "result", "message": "done"}

    monkeypatch.setattr(chat.ai_service, "run_global_agentic_loop", fake_loop)

    gen = chat._stream_and_save(
        conversation_id="c1", query="why is my pod crashing",
        history=[], runbook_id=None, cluster_context=None, user_id=None,
    )
    events = await _drain(gen, budget=1)

    assert events, "stream produced nothing"
    first_at, first_chunk = events[0]
    assert first_at < SLOW / 2, (
        f"first event arrived at {first_at:.2f}s — it waited on the runbook call, "
        "so the client sees nothing until the run ends"
    )
    assert "data: " in first_chunk


async def test_event_loop_is_not_blocked_during_matching(monkeypatch):
    """to_thread, not a bare call — a sync LLM client would freeze every other request."""
    from app.api.v1 import chat

    monkeypatch.setattr(
        "app.services.runbook_service.match_runbook_logic",
        lambda q: (time.sleep(SLOW), {"matched_runbook_id": None, "confidence": "none"})[1],
        raising=False,
    )

    async def fake_loop(*args, **kwargs):
        yield {"type": "result", "message": "done"}

    monkeypatch.setattr(chat.ai_service, "run_global_agentic_loop", fake_loop)

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    gen = chat._stream_and_save(
        conversation_id="c1", query="q", history=[],
        runbook_id=None, cluster_context=None, user_id=None,
    )
    try:
        await _drain(gen, budget=2)
    finally:
        beat.cancel()

    # A blocking call inside the loop stops the heartbeat dead.
    assert ticks > 5, f"event loop only ticked {ticks} times — it was blocked"
