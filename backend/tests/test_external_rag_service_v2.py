# backend/tests/test_external_rag_service_v2.py
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from app.services.external_rag_service import _embed_query, _dispatch, ExternalRAGService


@patch("app.services.external_rag_service._get_embedding_provider_sync")
def test_embed_query_returns_vector(mock_provider_fn):
    mock_provider = MagicMock()
    mock_provider.embed.return_value = [0.1, 0.2, 0.3]
    mock_provider_fn.return_value = mock_provider
    result = _embed_query("test query")
    assert result == [0.1, 0.2, 0.3]


@patch("app.services.external_rag_service._get_embedding_provider_sync")
def test_embed_query_returns_none_on_failure(mock_provider_fn):
    mock_provider_fn.side_effect = Exception("embedding down")
    result = _embed_query("test query")
    assert result is None


@pytest.mark.asyncio
@patch("app.services.connectors.qdrant_connector.retrieve", new_callable=AsyncMock)
async def test_dispatch_qdrant(mock_retrieve):
    mock_retrieve.return_value = ["chunk"]
    result = await _dispatch("qdrant", {"collection_name": "kb"}, "q", [0.1, 0.2])
    mock_retrieve.assert_called_once_with({"collection_name": "kb"}, [0.1, 0.2])
    assert result == ["chunk"]


@pytest.mark.asyncio
@patch("app.services.connectors.pinecone_connector.retrieve", new_callable=AsyncMock)
async def test_dispatch_pinecone(mock_retrieve):
    mock_retrieve.return_value = ["chunk"]
    result = await _dispatch("pinecone", {"index_host": "h"}, "q", [0.1])
    mock_retrieve.assert_called_once_with({"index_host": "h"}, [0.1])
    assert result == ["chunk"]


@pytest.mark.asyncio
@patch("app.services.connectors.weaviate_connector.retrieve", new_callable=AsyncMock)
async def test_dispatch_weaviate(mock_retrieve):
    mock_retrieve.return_value = ["chunk"]
    result = await _dispatch("weaviate", {}, "my query", None)
    mock_retrieve.assert_called_once_with({}, "my query")
    assert result == ["chunk"]


@pytest.mark.asyncio
@patch("app.services.connectors.opensearch_connector.retrieve", new_callable=AsyncMock)
async def test_dispatch_opensearch(mock_retrieve):
    mock_retrieve.return_value = ["chunk"]
    result = await _dispatch("opensearch", {}, "query", None)
    mock_retrieve.assert_called_once_with({}, "query")
    assert result == ["chunk"]


@pytest.mark.asyncio
@patch("app.services.connectors.chroma_connector.retrieve", new_callable=AsyncMock)
async def test_dispatch_chroma(mock_retrieve):
    mock_retrieve.return_value = ["chunk"]
    result = await _dispatch("chroma", {}, "query", None)
    mock_retrieve.assert_called_once_with({}, "query")
    assert result == ["chunk"]


@pytest.mark.asyncio
async def test_dispatch_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        await _dispatch("unknown_db", {}, "q", None)


@pytest.mark.asyncio
async def test_dispatch_qdrant_without_vector_raises():
    with pytest.raises(ValueError, match="Embedding not available"):
        await _dispatch("qdrant", {}, "q", None)
