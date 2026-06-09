import pytest
from unittest.mock import MagicMock, patch
from app.services.connectors.confluence_connector import (
    _storage_to_text,
    parse_page_id_from_url,
    ConfluenceConnector,
)


def test_storage_to_text_strips_tags():
    assert "Hello world" in _storage_to_text("<p>Hello <strong>world</strong></p>")


def test_storage_to_text_no_angle_brackets_in_output():
    result = _storage_to_text("<h1>Title</h1><p>Body</p>")
    assert "<" not in result
    assert ">" not in result


def test_storage_to_text_collapses_whitespace():
    result = _storage_to_text("<p>  too   many   spaces  </p>")
    assert "  " not in result.strip()


def test_storage_to_text_empty():
    assert _storage_to_text("") == ""


def test_parse_page_id_cloud_url():
    url = "https://myorg.atlassian.net/wiki/spaces/ENG/pages/123456/My+Page"
    assert parse_page_id_from_url(url) == "123456"


def test_parse_page_id_server_querystring():
    url = "https://confluence.example.com/pages/viewpage.action?pageId=654321"
    assert parse_page_id_from_url(url) == "654321"


def test_parse_page_id_server_path():
    url = "https://confluence.example.com/pages/789/Some+Title"
    assert parse_page_id_from_url(url) == "789"


def test_parse_page_id_invalid_raises():
    with pytest.raises(ValueError, match="Cannot extract page ID"):
        parse_page_id_from_url("https://confluence.example.com/display/ENG/MyPage")


def test_storage_to_text_decodes_html_entities():
    result = _storage_to_text("<p>AT&amp;T &lt;rocks&gt;</p>")
    assert "AT&T" in result
    assert "&amp;" not in result
    assert "&lt;" not in result


def test_storage_to_text_tags_only_returns_empty():
    assert _storage_to_text("<ac:structured-macro/>") == ""


def test_parse_page_id_non_numeric_querystring_raises():
    url = "https://confluence.example.com/pages/viewpage.action?pageId=abc"
    with pytest.raises(ValueError, match="Cannot extract page ID"):
        parse_page_id_from_url(url)


MOCK_CONFIG = {
    "instance_type": "cloud",
    "base_url": "https://myorg.atlassian.net",
    "email": "user@example.com",
    "username": "",
    "api_token": "test-token",
    "sync_spaces": ["ENG"],
    "sync_interval_hours": 24,
}

MOCK_PAGE = {
    "id": "111",
    "title": "Architecture Overview",
    "body": {"storage": {"value": "<p>Content here</p>"}},
}


def test_build_session_cloud_uses_basic_auth():
    connector = ConfluenceConnector()
    session = connector._build_session({**MOCK_CONFIG, "instance_type": "cloud"})
    assert session.auth == ("user@example.com", "test-token")


def test_build_session_server_basic_uses_auth():
    config = {**MOCK_CONFIG, "instance_type": "server_basic", "username": "bob", "api_token": "pass"}
    connector = ConfluenceConnector()
    session = connector._build_session(config)
    assert session.auth == ("bob", "pass")


def test_build_session_server_pat_uses_bearer():
    config = {**MOCK_CONFIG, "instance_type": "server_pat"}
    connector = ConfluenceConnector()
    session = connector._build_session(config)
    assert session.headers.get("Authorization") == "Bearer test-token"


@patch.object(ConfluenceConnector, "_get_config", return_value=MOCK_CONFIG)
@patch("requests.Session.get")
def test_get_page_by_id_returns_title_and_text(mock_get, _cfg):
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_PAGE
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    title, text = ConfluenceConnector().get_page_by_id("111")
    assert title == "Architecture Overview"
    assert "Content here" in text
    assert "<" not in text


@patch.object(ConfluenceConnector, "_get_config", return_value=MOCK_CONFIG)
@patch("requests.Session.get")
def test_get_space_pages_yields_four_tuple(mock_get, _cfg):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [MOCK_PAGE]}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    pages = list(ConfluenceConnector().get_space_pages("ENG"))
    assert len(pages) == 1
    page_id, title, text, url = pages[0]
    assert page_id == "111"
    assert title == "Architecture Overview"
    assert "Content here" in text
    assert "111" in url
    assert "ENG" in url


@patch.object(ConfluenceConnector, "_get_config", return_value=MOCK_CONFIG)
@patch("requests.Session.get")
def test_get_space_pages_paginates(mock_get, _cfg):
    """When first page is full (100 results), connector fetches a second page."""
    page = {"id": "1", "title": "P", "body": {"storage": {"value": "<p>x</p>"}}}
    first = MagicMock()
    first.json.return_value = {"results": [page] * 100}
    first.raise_for_status.return_value = None
    second = MagicMock()
    second.json.return_value = {"results": []}
    second.raise_for_status.return_value = None
    mock_get.side_effect = [first, second]

    pages = list(ConfluenceConnector().get_space_pages("ENG"))
    assert len(pages) == 100
    assert mock_get.call_count == 2


@patch.object(ConfluenceConnector, "_get_config", return_value={**MOCK_CONFIG, "instance_type": "server_basic", "username": "bob"})
@patch("requests.Session.get")
def test_get_space_pages_server_url_format(mock_get, _cfg):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [MOCK_PAGE]}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    pages = list(ConfluenceConnector().get_space_pages("ENG"))
    _, _, _, url = pages[0]
    assert "/pages/111" in url
    assert "/wiki/spaces/" not in url


def test_build_session_server_pat_empty_token_raises():
    config = {**MOCK_CONFIG, "instance_type": "server_pat", "api_token": ""}
    with pytest.raises(ValueError, match="confluence_api_token"):
        ConfluenceConnector()._build_session(config)
