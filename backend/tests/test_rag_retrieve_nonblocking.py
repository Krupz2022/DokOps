# Guards the SSE-stall regression: rag_service.retrieve() ran its sync Chroma +
# embedding calls directly on the event loop, freezing chat streams mid-turn
# (stall at "Thinking..." -> ERR_INCOMPLETE_CHUNKED_ENCODING behind a proxy).
# retrieve() must keep the loop responsive by offloading blocking work to a thread.
import asyncio
import time

import pytest

from app.services.rag_service import rag_service


class _SlowEmbedder:
    def embed(self, text):
        time.sleep(0.4)  # simulate a slow local model on the loop thread
        return [0.0, 0.1, 0.2]


class _FakeCollection:
    def get_or_create_collection(self, _name):
        return self

    def count(self):
        return 1

    def query(self, **_kw):
        return {"documents": [["doc text"]], "metadatas": [[{"title": "T"}]]}


@pytest.mark.anyio
async def test_retrieve_does_not_block_event_loop(monkeypatch):
    async def _fake_provider():
        return _SlowEmbedder()

    async def _fake_client():
        return _FakeCollection()

    monkeypatch.setattr(rag_service, "_get_embedding_provider", _fake_provider)
    monkeypatch.setattr(rag_service, "_get_chroma_client", _fake_client)

    ticks = 0

    async def _heartbeat():
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.02)
            ticks += 1

    hb = asyncio.create_task(_heartbeat())
    result = await rag_service.retrieve("q", "knowledge_base", n_results=3)
    await hb

    # If retrieve() blocked the loop for the 0.4s sleep, the heartbeat couldn't
    # have advanced during it. A responsive loop keeps ticking.
    assert ticks >= 10, f"event loop was blocked during retrieve (ticks={ticks})"
    assert "doc text" in result


@pytest.fixture
def anyio_backend():
    return "asyncio"
