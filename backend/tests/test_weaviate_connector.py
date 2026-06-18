from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.services.connectors.weaviate_connector import retrieve, test_connectivity


@pytest.mark.asyncio
@patch("app.services.connectors.weaviate_connector.validate_url")
@patch("app.services.connectors.weaviate_connector.httpx.AsyncClient")
async def test_retrieve_returns_text_property(mock_client_class, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"Get": {"CompanyDocs": [
        {"content": "chunk alpha"}, {"content": "chunk beta"},
    ]}}}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    config = {"endpoint": "https://cluster.weaviate.network", "api_key": "key", "collection_name": "CompanyDocs", "text_property": "content", "top_k": 2}
    result = await retrieve(config, "kubernetes crash")
    assert result == ["chunk alpha", "chunk beta"]
    mock_validate.assert_called_once_with("https://cluster.weaviate.network")


@pytest.mark.asyncio
@patch("app.services.connectors.weaviate_connector.validate_url")
@patch("app.services.connectors.weaviate_connector.httpx.AsyncClient")
async def test_retrieve_uses_neartext_graphql(mock_client_class, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"Get": {"Docs": []}}}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await retrieve({"endpoint": "https://x.weaviate.network", "api_key": "k", "collection_name": "Docs", "text_property": "body"}, "my query")
    call_body = mock_client.post.call_args[1]["json"]
    assert "nearText" in call_body["query"]
    assert "my query" in call_body["query"]


@pytest.mark.asyncio
@patch("app.services.connectors.weaviate_connector.validate_url")
@patch("app.services.connectors.weaviate_connector.httpx.AsyncClient")
async def test_connectivity_checks_schema(mock_client_class, mock_validate):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    await test_connectivity({"endpoint": "https://x.weaviate.network", "api_key": "k", "collection_name": "Docs"})
    url = mock_client.get.call_args[0][0]
    assert "/v1/schema/Docs" in url
