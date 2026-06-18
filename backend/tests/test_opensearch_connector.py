from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.services.connectors.opensearch_connector import retrieve, test_connectivity


@pytest.mark.asyncio
@patch("app.services.connectors.opensearch_connector.validate_url")
@patch("app.services.connectors.opensearch_connector.httpx.AsyncClient")
async def test_retrieve_returns_source_text(mock_client_class, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hits": {"hits": [
        {"_source": {"content": "doc alpha"}}, {"_source": {"content": "doc beta"}},
    ]}}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    config = {"endpoint": "https://opensearch.example.com", "username": "admin", "password": "pass", "index_name": "kb", "top_k": 2}
    result = await retrieve(config, "pod crash")
    assert result == ["doc alpha", "doc beta"]
    mock_validate.assert_called_once_with("https://opensearch.example.com")


@pytest.mark.asyncio
@patch("app.services.connectors.opensearch_connector.validate_url")
@patch("app.services.connectors.opensearch_connector.httpx.AsyncClient")
async def test_retrieve_uses_match_query(mock_client_class, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hits": {"hits": []}}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await retrieve({"endpoint": "https://os.example.com", "username": "u", "password": "p", "index_name": "idx"}, "query text")
    body = mock_client.post.call_args[1]["json"]
    assert body["query"]["match"]["content"] == "query text"


@pytest.mark.asyncio
@patch("app.services.connectors.opensearch_connector.validate_url")
@patch("app.services.connectors.opensearch_connector.httpx.AsyncClient")
async def test_retrieve_multi_index_joins_url(mock_client_class, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hits": {"hits": []}}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await retrieve({"endpoint": "https://os.example.com", "username": "u", "password": "p", "index_name": "kb1, kb2"}, "q")
    url = mock_client.post.call_args[0][0]
    assert "kb1,kb2" in url


@pytest.mark.asyncio
@patch("app.services.connectors.opensearch_connector.validate_url")
@patch("app.services.connectors.opensearch_connector.httpx.AsyncClient")
async def test_connectivity_calls_count_endpoint(mock_client_class, mock_validate):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await test_connectivity({"endpoint": "https://os.example.com", "username": "u", "password": "p", "index_name": "kb"})
    url = mock_client.get.call_args[0][0]
    assert "/_count" in url
