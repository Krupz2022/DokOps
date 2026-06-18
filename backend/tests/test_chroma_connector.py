from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.services.connectors.chroma_connector import retrieve, test_connectivity


def _make_mock_client(collection_id="uuid-123", docs=None):
    get_resp = MagicMock()
    get_resp.json.return_value = {"id": collection_id, "name": "kb"}
    get_resp.raise_for_status = MagicMock()

    post_resp = MagicMock()
    post_resp.json.return_value = {"documents": [docs or []]}
    post_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.post = AsyncMock(return_value=post_resp)
    return mock_client


@pytest.mark.asyncio
@patch("app.services.connectors.chroma_connector.validate_url")
@patch("app.services.connectors.chroma_connector.httpx.AsyncClient")
async def test_retrieve_returns_documents(mock_client_class, mock_validate):
    mock_client = _make_mock_client("uuid-123", ["doc one", "doc two"])
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    config = {"endpoint": "http://chroma:8000", "api_token": "", "collection_name": "kb", "top_k": 2}
    result = await retrieve(config, "crash loop")
    assert result == ["doc one", "doc two"]
    mock_validate.assert_called_once_with("http://chroma:8000")
    post_url = mock_client.post.call_args[0][0]
    assert "uuid-123" in post_url


@pytest.mark.asyncio
@patch("app.services.connectors.chroma_connector.validate_url")
@patch("app.services.connectors.chroma_connector.httpx.AsyncClient")
async def test_retrieve_with_auth_token(mock_client_class, mock_validate):
    mock_client = _make_mock_client("uuid-456", [])
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await retrieve({"endpoint": "http://chroma:8000", "api_token": "mytoken", "collection_name": "kb"}, "q")
    headers = mock_client.post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer mytoken"


@pytest.mark.asyncio
@patch("app.services.connectors.chroma_connector.validate_url")
@patch("app.services.connectors.chroma_connector.httpx.AsyncClient")
async def test_connectivity_resolves_collection(mock_client_class, mock_validate):
    mock_client = _make_mock_client()
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await test_connectivity({"endpoint": "http://chroma:8000", "api_token": "", "collection_name": "kb"})
    url = mock_client.get.call_args[0][0]
    assert "/api/v1/collections/kb" in url
