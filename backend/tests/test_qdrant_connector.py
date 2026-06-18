from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.services.connectors.qdrant_connector import retrieve, test_connectivity


def _mock_client(post_json=None, get_status=200):
    mock_resp_post = MagicMock()
    mock_resp_post.json.return_value = post_json or {"result": []}
    mock_resp_post.raise_for_status = MagicMock()

    mock_resp_get = MagicMock()
    mock_resp_get.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp_post)
    mock_client.get = AsyncMock(return_value=mock_resp_get)
    return mock_client


@pytest.mark.asyncio
@patch("app.services.connectors.qdrant_connector.validate_url")
@patch("app.services.connectors.qdrant_connector.httpx.AsyncClient")
async def test_retrieve_returns_text_field(mock_client_class, mock_validate):
    mock_client = _mock_client({"result": [
        {"id": "1", "score": 0.9, "payload": {"content": "doc one"}},
        {"id": "2", "score": 0.8, "payload": {"content": "doc two"}},
    ]})
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    config = {"endpoint": "https://xyz.qdrant.tech", "api_key": "key", "collection_name": "kb", "top_k": 2}
    result = await retrieve(config, [0.1, 0.2, 0.3])
    assert result == ["doc one", "doc two"]
    mock_validate.assert_called_once_with("https://xyz.qdrant.tech")


@pytest.mark.asyncio
@patch("app.services.connectors.qdrant_connector.validate_url")
@patch("app.services.connectors.qdrant_connector.httpx.AsyncClient")
async def test_retrieve_multi_collection(mock_client_class, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"result": [{"id": "1", "score": 0.9, "payload": {"content": "chunk"}}]}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    config = {"endpoint": "https://xyz.qdrant.tech", "api_key": "k", "collection_name": "kb1, kb2"}
    result = await retrieve(config, [0.1])
    assert mock_client.post.call_count == 2
    assert result == ["chunk", "chunk"]


@pytest.mark.asyncio
@patch("app.services.connectors.qdrant_connector.validate_url")
@patch("app.services.connectors.qdrant_connector.httpx.AsyncClient")
async def test_retrieve_skips_missing_field(mock_client_class, mock_validate):
    mock_client = _mock_client({"result": [{"id": "1", "score": 0.9, "payload": {}}]})
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await retrieve({"endpoint": "https://x.qdrant.tech", "api_key": "k", "collection_name": "kb"}, [0.1])
    assert result == []


@pytest.mark.asyncio
@patch("app.services.connectors.qdrant_connector.validate_url")
@patch("app.services.connectors.qdrant_connector.httpx.AsyncClient")
async def test_connectivity_calls_collections_endpoint(mock_client_class, mock_validate):
    mock_client = _mock_client()
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await test_connectivity({"endpoint": "https://x.qdrant.tech", "api_key": "k", "collection_name": "kb"})
    url = mock_client.get.call_args[0][0]
    assert "/collections/kb" in url
