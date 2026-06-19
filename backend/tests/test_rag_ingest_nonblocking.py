"""
Regression guard: RAG ingestion must not block the asyncio event loop.

A large upload triggers CPU-bound work — PDF text extraction (pypdf) and
embedding (SentenceTransformer.encode). If that work runs directly on the
event loop thread it pins one core at 100%, the server stops answering
/health, and the container gets SIGKILLed and restarted (the reported bug).

These tests prove the heavy synchronous work is offloaded off the loop so
concurrent coroutines keep making progress while ingestion runs.
"""
import asyncio
import json
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import app.services.rag_service as rag_module
from app.services.rag_service import RAGService

pytestmark = [pytest.mark.asyncio]

_BLOCK_SECONDS = 0.3


class _FakeAsyncSession:
    """Minimal async-session stand-in so ingest_text's DB write is a no-op.

    Pass ``existing`` to exercise the re-ingest branch (session.get returns a
    previously-indexed document).
    """
    def __init__(self, existing=None):
        self._existing = existing

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return self._existing

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


async def _heartbeat(ticks: list) -> None:
    """Tick every 20ms; if the loop is blocked a large gap opens between ticks."""
    ticks.append(time.perf_counter())
    for _ in range(25):
        await asyncio.sleep(0.02)
        ticks.append(time.perf_counter())


def _max_gap(ticks: list) -> float:
    """Largest interval between consecutive heartbeat ticks."""
    return max(b - a for a, b in zip(ticks, ticks[1:]))


# A frozen loop produces a gap ≈ _BLOCK_SECONDS; a responsive loop never gaps
# more than one tick (a touch over 20ms, plus OS timer slack on Windows).
_MAX_ALLOWED_GAP = _BLOCK_SECONDS / 2


async def test_ingest_text_does_not_block_loop_during_embedding():
    service = RAGService()

    mock_embedder = MagicMock()

    def _slow_embed_batch(texts):
        time.sleep(_BLOCK_SECONDS)  # simulates SentenceTransformer.encode (CPU-bound, blocking)
        return [[0.1] * 384 for _ in texts]

    mock_embedder.embed_batch.side_effect = _slow_embed_batch

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = MagicMock()

    ticks: list = []
    with patch.object(service, "_get_embedding_provider", new=AsyncMock(return_value=mock_embedder)), \
         patch.object(service, "_get_chroma_client", new=AsyncMock(return_value=mock_client)), \
         patch.object(rag_module, "AsyncSessionLocal", return_value=_FakeAsyncSession()):
        hb = asyncio.create_task(_heartbeat(ticks))
        await asyncio.sleep(0.05)  # let the heartbeat establish a cadence first
        await service.ingest_text(
            text="hello world " * 500,
            title="big.txt",
            source_type="upload",
            source_ref="big.txt",
        )
        await hb

    gap = _max_gap(ticks)
    assert gap < _MAX_ALLOWED_GAP, (
        f"event loop froze for {gap:.2f}s during embedding — it is blocking the "
        f"loop instead of offloading the {_BLOCK_SECONDS}s CPU-bound encode."
    )


async def test_ingest_file_does_not_block_loop_during_extraction():
    service = RAGService()

    def _slow_extract(filename, content):
        time.sleep(_BLOCK_SECONDS)  # simulates pypdf parsing a large PDF (CPU-bound, blocking)
        return "extracted text"

    fake_doc = MagicMock()

    ticks: list = []
    with patch.object(rag_module, "_extract_file_text", side_effect=_slow_extract), \
         patch.object(service, "ingest_text", new=AsyncMock(return_value=fake_doc)):
        hb = asyncio.create_task(_heartbeat(ticks))
        await asyncio.sleep(0.05)  # let the heartbeat establish a cadence first
        await service.ingest_file("big.pdf", b"%PDF-1.4 ...")
        await hb

    gap = _max_gap(ticks)
    assert gap < _MAX_ALLOWED_GAP, (
        f"event loop froze for {gap:.2f}s during PDF extraction — it is blocking "
        f"the loop instead of offloading the {_BLOCK_SECONDS}s parse."
    )


async def test_ingest_text_does_not_block_loop_during_upsert():
    service = RAGService()

    mock_embedder = MagicMock()
    mock_embedder.embed_batch.return_value = [[0.1] * 384]

    mock_collection = MagicMock()

    def _slow_upsert(*args, **kwargs):
        time.sleep(_BLOCK_SECONDS)  # simulates the synchronous Chroma HTTP upsert

    mock_collection.upsert.side_effect = _slow_upsert

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    ticks: list = []
    with patch.object(service, "_get_embedding_provider", new=AsyncMock(return_value=mock_embedder)), \
         patch.object(service, "_get_chroma_client", new=AsyncMock(return_value=mock_client)), \
         patch.object(rag_module, "AsyncSessionLocal", return_value=_FakeAsyncSession()):
        hb = asyncio.create_task(_heartbeat(ticks))
        await asyncio.sleep(0.05)  # let the heartbeat establish a cadence first
        await service.ingest_text(
            text="a short document",
            title="small.txt",
            source_type="upload",
            source_ref="small.txt",
        )
        await hb

    gap = _max_gap(ticks)
    assert gap < _MAX_ALLOWED_GAP, (
        f"event loop froze for {gap:.2f}s during the Chroma upsert — it is blocking "
        f"the loop instead of offloading the {_BLOCK_SECONDS}s write."
    )


async def test_ingest_text_does_not_block_loop_during_get_collection():
    service = RAGService()

    mock_embedder = MagicMock()
    mock_embedder.embed_batch.return_value = [[0.1] * 384]

    mock_collection = MagicMock()

    def _slow_get_collection(*args, **kwargs):
        time.sleep(_BLOCK_SECONDS)  # simulates the synchronous Chroma get_or_create_collection HTTP call
        return mock_collection

    mock_client = MagicMock()
    mock_client.get_or_create_collection.side_effect = _slow_get_collection

    ticks: list = []
    with patch.object(service, "_get_embedding_provider", new=AsyncMock(return_value=mock_embedder)), \
         patch.object(service, "_get_chroma_client", new=AsyncMock(return_value=mock_client)), \
         patch.object(rag_module, "AsyncSessionLocal", return_value=_FakeAsyncSession()):
        hb = asyncio.create_task(_heartbeat(ticks))
        await asyncio.sleep(0.05)  # let the heartbeat establish a cadence first
        await service.ingest_text(
            text="a short document",
            title="small.txt",
            source_type="upload",
            source_ref="small.txt",
        )
        await hb

    gap = _max_gap(ticks)
    assert gap < _MAX_ALLOWED_GAP, (
        f"event loop froze for {gap:.2f}s while opening the Chroma collection — it is "
        f"blocking the loop instead of offloading the {_BLOCK_SECONDS}s call."
    )


async def test_ingest_text_does_not_block_loop_during_delete_on_reingest():
    service = RAGService()

    mock_embedder = MagicMock()
    mock_embedder.embed_batch.return_value = [[0.1] * 384]

    mock_collection = MagicMock()

    def _slow_delete(*args, **kwargs):
        time.sleep(_BLOCK_SECONDS)  # simulates the synchronous Chroma delete of stale chunks

    mock_collection.delete.side_effect = _slow_delete

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    # A previously-indexed document drives the re-ingest branch that deletes old chunks.
    existing = MagicMock()
    existing.chroma_ids = json.dumps(["old_doc_0", "old_doc_1"])

    ticks: list = []
    with patch.object(service, "_get_embedding_provider", new=AsyncMock(return_value=mock_embedder)), \
         patch.object(service, "_get_chroma_client", new=AsyncMock(return_value=mock_client)), \
         patch.object(rag_module, "AsyncSessionLocal", return_value=_FakeAsyncSession(existing=existing)):
        hb = asyncio.create_task(_heartbeat(ticks))
        await asyncio.sleep(0.05)  # let the heartbeat establish a cadence first
        await service.ingest_text(
            text="a short document",
            title="small.txt",
            source_type="upload",
            source_ref="small.txt",
            doc_id="small",
        )
        await hb

    gap = _max_gap(ticks)
    assert gap < _MAX_ALLOWED_GAP, (
        f"event loop froze for {gap:.2f}s while deleting stale chunks — it is blocking "
        f"the loop instead of offloading the {_BLOCK_SECONDS}s delete."
    )
