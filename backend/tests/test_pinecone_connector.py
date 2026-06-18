from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.services.connectors.pinecone_connector import retrieve, test_connectivity


def _mock_ctx(json_data):
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


@pytest.mark.asyncio
@patch("app.services.connectors.pinecone_connector.validate_url")
@patch("app.services.connectors.pinecone_connector.httpx.AsyncClient")
async def test_retrieve_returns_metadata_text(mock_client_class, mock_validate):
    mock_client = _mock_ctx({"matches": [
        {"id": "v1", "score": 0.95, "metadata": {"text": "chunk one"}},
        {"id": "v2", "score": 0.88, "metadata": {"text": "chunk two"}},
    ]})
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await retrieve({"index_host": "https://idx.svc.pinecone.io", "api_key": "k", "top_k": 2}, [0.1, 0.2])
    assert result == ["chunk one", "chunk two"]
    mock_validate.assert_called_once_with("https://idx.svc.pinecone.io")


@pytest.mark.asyncio
@patch("app.services.connectors.pinecone_connector.validate_url")
@patch("app.services.connectors.pinecone_connector.httpx.AsyncClient")
async def test_retrieve_custom_metadata_field(mock_client_class, mock_validate):
    mock_client = _mock_ctx({"matches": [{"id": "v1", "score": 0.9, "metadata": {"body": "hello"}}]})
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await retrieve({"index_host": "https://idx.svc.pinecone.io", "api_key": "k", "metadata_text_field": "body"}, [0.1])
    assert result == ["hello"]


@pytest.mark.asyncio
@patch("app.services.connectors.pinecone_connector.validate_url")
@patch("app.services.connectors.pinecone_connector.httpx.AsyncClient")
async def test_retrieve_skips_missing_metadata(mock_client_class, mock_validate):
    mock_client = _mock_ctx({"matches": [{"id": "v1", "score": 0.9, "metadata": {}}]})
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await retrieve({"index_host": "https://idx.svc.pinecone.io", "api_key": "k"}, [0.1])
    assert result == []


@pytest.mark.asyncio
@patch("app.services.connectors.pinecone_connector.validate_url")
@patch("app.services.connectors.pinecone_connector.httpx.AsyncClient")
async def test_connectivity_calls_stats_endpoint(mock_client_class, mock_validate):
    mock_client = _mock_ctx({})
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await test_connectivity({"index_host": "https://idx.svc.pinecone.io", "api_key": "k"})
    url = mock_client.get.call_args[0][0]
    assert "describe_index_stats" in url
