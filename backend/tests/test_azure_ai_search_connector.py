import pytest
from unittest.mock import MagicMock, patch


CONFIG = {
    "endpoint": "https://mysearch.search.windows.net",
    "api_key": "test-key",
    "index_name": "company-kb",
    "top_k": 3,
    "semantic_config": "",
}

CONFIG_WITH_SEMANTIC = {**CONFIG, "semantic_config": "my-semantic-config"}


@patch("app.services.connectors.azure_ai_search_connector.validate_url")
@patch("requests.post")
def test_retrieve_returns_content_chunks(mock_post, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "value": [
            {"content": "chunk one", "@search.score": 0.9},
            {"content": "chunk two", "@search.score": 0.8},
        ]
    }
    mock_resp.raise_for_status.return_value = None
    mock_post.return_value = mock_resp

    from app.services.connectors.azure_ai_search_connector import retrieve
    result = retrieve(CONFIG, "pod crashloop")

    assert result == ["chunk one", "chunk two"]


@patch("app.services.connectors.azure_ai_search_connector.validate_url")
@patch("requests.post")
def test_retrieve_sends_correct_url_and_headers(mock_post, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": []}
    mock_resp.raise_for_status.return_value = None
    mock_post.return_value = mock_resp

    from app.services.connectors.azure_ai_search_connector import retrieve
    retrieve(CONFIG, "test query")

    call_kwargs = mock_post.call_args
    url = call_kwargs[0][0]
    headers = call_kwargs[1]["headers"]
    body = call_kwargs[1]["json"]

    assert "company-kb" in url
    assert "api-version=2023-11-01" in url
    assert headers["api-key"] == "test-key"
    assert body["search"] == "test query"
    assert body["top"] == 3
    assert "queryType" not in body


@patch("app.services.connectors.azure_ai_search_connector.validate_url")
@patch("requests.post")
def test_retrieve_with_semantic_config_adds_query_type(mock_post, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": []}
    mock_resp.raise_for_status.return_value = None
    mock_post.return_value = mock_resp

    from app.services.connectors.azure_ai_search_connector import retrieve
    retrieve(CONFIG_WITH_SEMANTIC, "test")

    body = mock_post.call_args[1]["json"]
    assert body["queryType"] == "semantic"
    assert body["semanticConfiguration"] == "my-semantic-config"


@patch("app.services.connectors.azure_ai_search_connector.validate_url")
@patch("requests.post")
def test_retrieve_empty_results_returns_empty_list(mock_post, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": []}
    mock_resp.raise_for_status.return_value = None
    mock_post.return_value = mock_resp

    from app.services.connectors.azure_ai_search_connector import retrieve
    assert retrieve(CONFIG, "query") == []


@patch("app.services.connectors.azure_ai_search_connector.validate_url")
@patch("requests.post")
def test_retrieve_skips_hits_without_content(mock_post, mock_validate):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "value": [
            {"content": "good chunk"},
            {"@search.score": 0.5},  # missing content
        ]
    }
    mock_resp.raise_for_status.return_value = None
    mock_post.return_value = mock_resp

    from app.services.connectors.azure_ai_search_connector import retrieve
    result = retrieve(CONFIG, "query")
    assert result == ["good chunk"]


def test_retrieve_calls_ssrf_guard():
    with patch("app.services.connectors.azure_ai_search_connector.validate_url") as mock_validate, \
         patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"value": []}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        from app.services.connectors.azure_ai_search_connector import retrieve
        retrieve(CONFIG, "test")

        mock_validate.assert_called_once_with("https://mysearch.search.windows.net")
