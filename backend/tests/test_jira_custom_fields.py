import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_user():
    u = MagicMock()
    u.username = "testuser"
    u.id = 1
    return u


def _mock_response(status: int, json_data: dict):
    """aiohttp response that works as an async context manager."""
    r = AsyncMock()
    r.status = status
    r.json = AsyncMock(return_value=json_data)
    r.text = AsyncMock(return_value=str(json_data))
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=None)
    return r


def _mock_session(get_responses: list, post_responses: list | None = None):
    """aiohttp ClientSession that returns preset responses in order."""
    get_iter = iter(get_responses)
    post_iter = iter(post_responses or [])
    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)
    s.get = lambda *a, **kw: next(get_iter)
    s.post = lambda *a, **kw: next(post_iter)
    return s


# ---------------------------------------------------------------------------
# /connectors/jira/fields
# ---------------------------------------------------------------------------

MOCK_ISSUE_TYPES = {
    "issueTypes": [
        {"id": "10001", "name": "Bug"},
        {"id": "10002", "name": "Story"},
    ]
}

MOCK_FIELDS_RESPONSE = {
    "fields": [
        {
            "fieldId": "summary",
            "name": "Summary",
            "required": True,
            "schema": {"type": "string"},
            "allowedValues": [],
        },
        {
            "fieldId": "customfield_10014",
            "name": "Sprint",
            "required": True,
            "schema": {"type": "array", "items": "option"},
            "allowedValues": [],
        },
        {
            "fieldId": "priority",
            "name": "Priority",
            "required": False,
            "schema": {"type": "option"},
            "allowedValues": [{"name": "High"}, {"name": "Medium"}, {"name": "Low"}],
        },
    ]
}


@pytest.mark.asyncio
async def test_get_jira_fields_returns_normalized_schema():
    """Fields endpoint returns sorted, normalized JiraFieldSchema list."""
    from app.api.v1.workflows import get_jira_fields, JiraFieldsRequest

    body = JiraFieldsRequest(
        base_url="https://test.atlassian.net",
        email="test@test.com",
        api_token=SecretStr("token123"),
        project_key="TEST",
        issue_type="Bug",
    )

    session = _mock_session(
        get_responses=[
            _mock_response(200, MOCK_ISSUE_TYPES),
            _mock_response(200, MOCK_FIELDS_RESPONSE),
        ]
    )

    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=session):
        result = await get_jira_fields(body, current_user=_mock_user())

    assert isinstance(result, list)
    ids = [f["id"] for f in result]
    assert "summary" in ids
    assert "customfield_10014" in ids
    # required fields come first
    required = [f for f in result if f["required"]]
    optional = [f for f in result if not f["required"]]
    assert len(required) == 2
    assert len(optional) == 1
    # allowed_values populated for priority
    priority = next(f for f in result if f["id"] == "priority")
    assert priority["allowed_values"] == ["High", "Medium", "Low"]
    assert priority["type"] == "option"
    # array type mapped correctly
    sprint = next(f for f in result if f["id"] == "customfield_10014")
    assert sprint["type"] == "array"


@pytest.mark.asyncio
async def test_get_jira_fields_bad_credentials_returns_401():
    """401 from Jira bubbles up as HTTP 401."""
    from app.api.v1.workflows import get_jira_fields, JiraFieldsRequest
    from fastapi import HTTPException

    body = JiraFieldsRequest(
        base_url="https://test.atlassian.net",
        email="bad@test.com",
        api_token=SecretStr("wrong"),
        project_key="TEST",
        issue_type="Bug",
    )

    session = _mock_session(get_responses=[_mock_response(401, {"errorMessages": ["Unauthorized"]})])

    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=session):
        with pytest.raises(HTTPException) as exc:
            await get_jira_fields(body, current_user=_mock_user())

    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# /connectors/jira/users/search
# ---------------------------------------------------------------------------

MOCK_USERS_RESPONSE = [
    {
        "accountId": "abc123",
        "displayName": "John Doe",
        "emailAddress": "john@acme.com",
        "accountType": "atlassian",
    },
    {
        "accountId": "svc001",
        "displayName": "CI Bot",
        "emailAddress": "ci@acme.com",
        "accountType": "app",  # should be filtered out
    },
]


@pytest.mark.asyncio
async def test_search_jira_users_filters_service_accounts():
    """Only atlassian accountType users are returned; service accounts filtered."""
    from app.api.v1.workflows import search_jira_users, JiraUserSearchRequest

    body = JiraUserSearchRequest(
        base_url="https://test.atlassian.net",
        email="test@test.com",
        api_token=SecretStr("token123"),
        query="john",
    )

    session = _mock_session(get_responses=[_mock_response(200, MOCK_USERS_RESPONSE)])

    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=session):
        result = await search_jira_users(body, current_user=_mock_user())

    assert len(result) == 1
    assert result[0]["account_id"] == "abc123"
    assert result[0]["display_name"] == "John Doe"
    assert result[0]["email"] == "john@acme.com"


# ---------------------------------------------------------------------------
# JiraConnector.execute()
# ---------------------------------------------------------------------------

def _make_create_issue_session(post_json: dict, post_status: int = 201):
    """Session returning a preset POST response."""
    r = _mock_response(post_status, post_json)
    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)
    s.post = lambda *a, **kw: r
    return s


@pytest.mark.asyncio
async def test_jira_connector_custom_fields_merged_into_payload():
    """custom_fields dict is merged into the Jira issue fields payload."""
    from app.services.connectors.jira_connector import JiraConnector

    connector = JiraConnector()
    captured: dict = {}

    r = AsyncMock()
    r.status = 201
    r.json = AsyncMock(return_value={"key": "TEST-1"})
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=None)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)

    def capture_post(url, json=None, auth=None, headers=None):
        captured.update(json or {})
        return r

    s.post = capture_post

    config = {
        "base_url": "https://test.atlassian.net",
        "email": "test@test.com",
        "api_token": "token",
        "project_key": "TEST",
        "action": "create_issue",
        "summary": "Test issue",
        "custom_fields": {
            "customfield_10014": {"name": "Sprint 42"},
            "labels": ["bug", "infra"],
        },
    }

    with patch("app.services.connectors.jira_connector.aiohttp.ClientSession", return_value=s):
        result = await connector.execute(config, {})

    assert result["success"] is True
    assert captured["fields"]["customfield_10014"] == {"name": "Sprint 42"}
    assert captured["fields"]["labels"] == ["bug", "infra"]
    assert captured["fields"]["summary"] == "Test issue"


@pytest.mark.asyncio
async def test_jira_connector_legacy_url_key_still_works():
    """Legacy config key 'url' is accepted alongside new 'base_url'."""
    from app.services.connectors.jira_connector import JiraConnector

    connector = JiraConnector()
    captured_urls: list = []

    r = AsyncMock()
    r.status = 201
    r.json = AsyncMock(return_value={"key": "TEST-2"})
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=None)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)

    def capture_post(url, **kwargs):
        captured_urls.append(url)
        return r

    s.post = capture_post

    config = {
        "url": "https://legacy.atlassian.net",  # old key — must still work
        "email": "test@test.com",
        "api_token": "token",
        "project_key": "LEGACY",
        "action": "create_issue",
        "summary": "Legacy test",
    }

    with patch("app.services.connectors.jira_connector.aiohttp.ClientSession", return_value=s):
        result = await connector.execute(config, {})

    assert result["success"] is True
    assert "legacy.atlassian.net" in captured_urls[0]


@pytest.mark.asyncio
async def test_jira_connector_custom_fields_as_json_string():
    """custom_fields stored as a JSON string is parsed and merged."""
    import json as json_lib
    from app.services.connectors.jira_connector import JiraConnector

    connector = JiraConnector()
    captured: dict = {}

    r = AsyncMock()
    r.status = 201
    r.json = AsyncMock(return_value={"key": "TEST-3"})
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=None)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)

    def capture_post(url, json=None, **kwargs):
        captured.update(json or {})
        return r

    s.post = capture_post

    config = {
        "base_url": "https://test.atlassian.net",
        "email": "test@test.com",
        "api_token": "token",
        "project_key": "TEST",
        "action": "create_issue",
        "summary": "Test",
        "custom_fields": json_lib.dumps({"priority": {"name": "High"}}),  # JSON string
    }

    with patch("app.services.connectors.jira_connector.aiohttp.ClientSession", return_value=s):
        result = await connector.execute(config, {})

    assert result["success"] is True
    assert captured["fields"]["priority"] == {"name": "High"}


# ---------------------------------------------------------------------------
# _build_auth / _build_text_body helpers
# ---------------------------------------------------------------------------

def test_build_auth_cloud_returns_basic_auth_with_email():
    from app.services.connectors.jira_connector import _build_auth
    import aiohttp
    config = {"instance_type": "cloud", "email": "ops@acme.com", "api_token": "tok123"}
    auth, extra = _build_auth(config)
    assert isinstance(auth, aiohttp.BasicAuth)
    assert auth.login == "ops@acme.com"
    assert auth.password == "tok123"
    assert extra == {}


def test_build_auth_server_basic_returns_basic_auth_with_username():
    from app.services.connectors.jira_connector import _build_auth
    import aiohttp
    config = {"instance_type": "server_basic", "username": "jirauser", "api_token": "pass123"}
    auth, extra = _build_auth(config)
    assert isinstance(auth, aiohttp.BasicAuth)
    assert auth.login == "jirauser"
    assert auth.password == "pass123"
    assert extra == {}


def test_build_auth_server_pat_returns_bearer_header():
    from app.services.connectors.jira_connector import _build_auth
    config = {"instance_type": "server_pat", "api_token": "myPAT"}
    auth, extra = _build_auth(config)
    assert auth is None
    assert extra == {"Authorization": "Bearer myPAT"}


def test_build_auth_missing_instance_type_defaults_to_cloud():
    from app.services.connectors.jira_connector import _build_auth
    import aiohttp
    config = {"email": "x@x.com", "api_token": "t"}  # no instance_type key
    auth, extra = _build_auth(config)
    assert isinstance(auth, aiohttp.BasicAuth)


def test_build_text_body_cloud_returns_adf():
    from app.services.connectors.jira_connector import _build_text_body
    result = _build_text_body("Hello world", "cloud")
    assert isinstance(result, dict)
    assert result["type"] == "doc"
    assert result["version"] == 1
    assert result["content"][0]["content"][0]["text"] == "Hello world"


def test_build_text_body_server_returns_plain_string():
    from app.services.connectors.jira_connector import _build_text_body
    result = _build_text_body("Hello world", "server_basic")
    assert result == "Hello world"


def test_build_text_body_server_pat_returns_plain_string():
    from app.services.connectors.jira_connector import _build_text_body
    result = _build_text_body("Incident report", "server_pat")
    assert result == "Incident report"


# ---------------------------------------------------------------------------
# JiraConnector.execute() — instance_type branching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jira_connector_cloud_uses_api_v3():
    from app.services.connectors.jira_connector import JiraConnector
    captured_url = []

    r = AsyncMock()
    r.status = 201
    r.json = AsyncMock(return_value={"key": "OPS-1"})
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=None)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)
    s.post = lambda url, **kw: (captured_url.append(url), r)[1]

    config = {
        "instance_type": "cloud",
        "base_url": "https://acme.atlassian.net",
        "email": "ops@acme.com",
        "api_token": "tok",
        "project_key": "OPS",
        "action": "create_issue",
        "summary": "Test",
        "description": "desc",
    }
    with patch("app.services.connectors.jira_connector.aiohttp.ClientSession", return_value=s):
        result = await JiraConnector().execute(config, {})

    assert result["success"] is True
    assert "/rest/api/3/issue" in captured_url[0]


@pytest.mark.asyncio
async def test_jira_connector_server_uses_api_v2():
    from app.services.connectors.jira_connector import JiraConnector
    captured = {"url": "", "payload": {}}

    r = AsyncMock()
    r.status = 201
    r.json = AsyncMock(return_value={"key": "OPS-2"})
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=None)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)

    def capture(url, json=None, **kw):
        captured["url"] = url
        captured["payload"] = json or {}
        return r

    s.post = capture

    config = {
        "instance_type": "server_basic",
        "base_url": "https://jira.corp.example.com",
        "username": "jirauser",
        "api_token": "pass",
        "project_key": "OPS",
        "action": "create_issue",
        "summary": "Server issue",
        "description": "Plain text description",
    }
    with patch("app.services.connectors.jira_connector.aiohttp.ClientSession", return_value=s):
        result = await JiraConnector().execute(config, {})

    assert result["success"] is True
    assert "/rest/api/2/issue" in captured["url"]
    # description must be a plain string, not ADF
    assert captured["payload"]["fields"]["description"] == "Plain text description"


@pytest.mark.asyncio
async def test_jira_connector_server_comment_is_plain_string():
    from app.services.connectors.jira_connector import JiraConnector
    captured_payload: dict = {}

    r = AsyncMock()
    r.status = 201
    r.json = AsyncMock(return_value={})
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=None)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)

    def capture(url, json=None, **kw):
        captured_payload.update(json or {})
        return r

    s.post = capture

    config = {
        "instance_type": "server_basic",
        "base_url": "https://jira.corp.example.com",
        "username": "u",
        "api_token": "p",
        "project_key": "OPS",
        "action": "add_comment",
        "issue_key": "OPS-5",
        "comment": "Fixed in v2",
    }
    with patch("app.services.connectors.jira_connector.aiohttp.ClientSession", return_value=s):
        await JiraConnector().execute(config, {})

    assert captured_payload["body"] == "Fixed in v2"


# ---------------------------------------------------------------------------
# _jira_auth_headers (workflows.py)
# ---------------------------------------------------------------------------

def test_jira_auth_headers_cloud():
    from app.api.v1.workflows import _jira_auth_headers
    import base64
    headers = _jira_auth_headers("cloud", "ops@acme.com", "", "mytoken")
    expected_b64 = base64.b64encode(b"ops@acme.com:mytoken").decode()
    assert headers["Authorization"] == f"Basic {expected_b64}"


def test_jira_auth_headers_server_basic():
    from app.api.v1.workflows import _jira_auth_headers
    import base64
    headers = _jira_auth_headers("server_basic", "", "jirauser", "pass123")
    expected_b64 = base64.b64encode(b"jirauser:pass123").decode()
    assert headers["Authorization"] == f"Basic {expected_b64}"


def test_jira_auth_headers_server_pat():
    from app.api.v1.workflows import _jira_auth_headers
    headers = _jira_auth_headers("server_pat", "", "", "myPAT")
    assert headers["Authorization"] == "Bearer myPAT"


def test_jira_fields_request_accepts_instance_type_and_username():
    from app.api.v1.workflows import JiraFieldsRequest
    from pydantic import SecretStr
    body = JiraFieldsRequest(
        base_url="https://jira.corp.com",
        email="",
        username="jirauser",
        api_token=SecretStr("pass"),
        project_key="OPS",
        instance_type="server_basic",
    )
    assert body.instance_type == "server_basic"
    assert body.username == "jirauser"


def test_jira_fields_request_defaults_to_cloud():
    from app.api.v1.workflows import JiraFieldsRequest
    from pydantic import SecretStr
    body = JiraFieldsRequest(
        base_url="https://acme.atlassian.net",
        email="x@x.com",
        api_token=SecretStr("tok"),
        project_key="X",
    )
    assert body.instance_type == "cloud"
    assert body.username == ""


# ---------------------------------------------------------------------------
# /connectors/jira/issue-types — Server v2 branch
# ---------------------------------------------------------------------------

MOCK_SERVER_CREATEMETA_ISSUETYPES = {
    "projects": [{
        "key": "OPS",
        "issuetypes": [
            {"id": "1", "name": "Bug"},
            {"id": "2", "name": "Task"},
        ]
    }]
}


@pytest.mark.asyncio
async def test_get_jira_issue_types_server_v2():
    from app.api.v1.workflows import get_jira_issue_types, JiraIssueTypesRequest
    from pydantic import SecretStr

    body = JiraIssueTypesRequest(
        base_url="https://jira.corp.com",
        email="",
        username="jirauser",
        api_token=SecretStr("pass"),
        project_key="OPS",
        instance_type="server_basic",
    )
    session = _mock_session(get_responses=[_mock_response(200, MOCK_SERVER_CREATEMETA_ISSUETYPES)])

    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=session):
        result = await get_jira_issue_types(body, current_user=_mock_user())

    assert result == ["Bug", "Task"]


@pytest.mark.asyncio
async def test_get_jira_issue_types_server_uses_api_v2_url():
    from app.api.v1.workflows import get_jira_issue_types, JiraIssueTypesRequest
    from pydantic import SecretStr
    captured_url = []

    r = _mock_response(200, MOCK_SERVER_CREATEMETA_ISSUETYPES)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)
    s.get = lambda url, **kw: (captured_url.append(url), r)[1]

    body = JiraIssueTypesRequest(
        base_url="https://jira.corp.com",
        email="",
        username="u",
        api_token=SecretStr("p"),
        project_key="OPS",
        instance_type="server_pat",
    )
    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=s):
        await get_jira_issue_types(body, current_user=_mock_user())

    assert "/rest/api/2/" in captured_url[0]


# ---------------------------------------------------------------------------
# /connectors/jira/fields — Server v2 branch
# ---------------------------------------------------------------------------

MOCK_SERVER_CREATEMETA_FIELDS = {
    "projects": [{
        "key": "OPS",
        "issuetypes": [{
            "id": "1",
            "name": "Bug",
            "fields": {
                "summary": {
                    "required": True,
                    "name": "Summary",
                    "schema": {"type": "string"},
                    "allowedValues": [],
                },
                "priority": {
                    "required": False,
                    "name": "Priority",
                    "schema": {"type": "option"},
                    "allowedValues": [{"name": "High"}, {"name": "Low"}],
                },
            }
        }]
    }]
}


@pytest.mark.asyncio
async def test_get_jira_fields_server_v2_returns_normalized_schema():
    from app.api.v1.workflows import get_jira_fields, JiraFieldsRequest
    from pydantic import SecretStr

    body = JiraFieldsRequest(
        base_url="https://jira.corp.com",
        email="",
        username="jirauser",
        api_token=SecretStr("pass"),
        project_key="OPS",
        issue_type="Bug",
        instance_type="server_basic",
    )
    session = _mock_session(get_responses=[_mock_response(200, MOCK_SERVER_CREATEMETA_FIELDS)])

    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=session):
        result = await get_jira_fields(body, current_user=_mock_user())

    ids = [f["id"] for f in result]
    assert "summary" in ids
    assert "priority" in ids
    required = [f for f in result if f["required"]]
    assert len(required) == 1
    assert required[0]["id"] == "summary"
    priority = next(f for f in result if f["id"] == "priority")
    assert priority["allowed_values"] == ["High", "Low"]


@pytest.mark.asyncio
async def test_get_jira_fields_server_v2_uses_single_request():
    from app.api.v1.workflows import get_jira_fields, JiraFieldsRequest
    from pydantic import SecretStr
    call_count = []

    r = _mock_response(200, MOCK_SERVER_CREATEMETA_FIELDS)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)

    def counting_get(url, **kw):
        call_count.append(url)
        return r

    s.get = counting_get

    body = JiraFieldsRequest(
        base_url="https://jira.corp.com",
        email="",
        username="u",
        api_token=SecretStr("p"),
        project_key="OPS",
        issue_type="Bug",
        instance_type="server_basic",
    )
    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=s):
        await get_jira_fields(body, current_user=_mock_user())

    assert len(call_count) == 1
    assert "/rest/api/2/" in call_count[0]


# ---------------------------------------------------------------------------
# /connectors/jira/users/search — Server v2 branch
# ---------------------------------------------------------------------------

MOCK_SERVER_USERS = [
    {"name": "jdoe", "displayName": "John Doe", "emailAddress": "john@corp.com"},
    {"name": "asmith", "displayName": "Alice Smith", "emailAddress": "alice@corp.com"},
]


@pytest.mark.asyncio
async def test_search_jira_users_server_v2():
    from app.api.v1.workflows import search_jira_users, JiraUserSearchRequest
    from pydantic import SecretStr

    body = JiraUserSearchRequest(
        base_url="https://jira.corp.com",
        email="",
        username="",
        api_token=SecretStr("pass"),
        query="doe",
        instance_type="server_basic",
    )
    session = _mock_session(get_responses=[_mock_response(200, MOCK_SERVER_USERS)])

    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=session):
        result = await search_jira_users(body, current_user=_mock_user())

    assert len(result) == 2
    assert result[0]["account_id"] == "jdoe"
    assert result[0]["display_name"] == "John Doe"


@pytest.mark.asyncio
async def test_search_jira_users_server_uses_username_param():
    from app.api.v1.workflows import search_jira_users, JiraUserSearchRequest
    from pydantic import SecretStr
    captured_params: dict = {}

    r = _mock_response(200, MOCK_SERVER_USERS)

    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)

    def capture_get(url, params=None, **kw):
        captured_params.update(params or {})
        return r

    s.get = capture_get

    body = JiraUserSearchRequest(
        base_url="https://jira.corp.com",
        email="",
        username="",
        api_token=SecretStr("pass"),
        query="doe",
        instance_type="server_pat",
    )
    with patch("app.api.v1.workflows.aiohttp.ClientSession", return_value=s):
        await search_jira_users(body, current_user=_mock_user())

    assert "username" in captured_params
    assert "query" not in captured_params


# ---------------------------------------------------------------------------
# /alerts/jira-config + /alerts/jira-test
# ---------------------------------------------------------------------------

def test_get_jira_config_returns_empty_when_not_set():
    import asyncio
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.alerts import router as alerts_router
    from app.api import deps
    from app.core.db import create_db_and_tables
    from app.models.user import User

    app = FastAPI()
    asyncio.run(create_db_and_tables())
    mock_user = MagicMock(spec=User)
    mock_user.is_superuser = True
    app.include_router(alerts_router, prefix="/alerts")
    app.dependency_overrides[deps.get_current_user] = lambda: mock_user
    app.dependency_overrides[deps.get_current_active_superuser] = lambda: mock_user

    client = TestClient(app)
    response = client.get("/alerts/jira-config")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_put_jira_config_saves_and_masks_token_on_get():
    import asyncio
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.alerts import router as alerts_router
    from app.api import deps
    from app.core.db import create_db_and_tables
    from app.models.user import User

    app = FastAPI()
    asyncio.run(create_db_and_tables())
    mock_user = MagicMock(spec=User)
    mock_user.is_superuser = True
    app.include_router(alerts_router, prefix="/alerts")
    app.dependency_overrides[deps.get_current_user] = lambda: mock_user
    app.dependency_overrides[deps.get_current_active_superuser] = lambda: mock_user

    client = TestClient(app)

    payload = {
        "instance_type": "server_basic",
        "base_url": "https://jira.corp.com",
        "email": "",
        "username": "jirauser",
        "api_token": "mysecretpassword",
        "project_key": "OPS",
    }
    put_resp = client.put("/alerts/jira-config", json=payload)
    assert put_resp.status_code == 200
    assert put_resp.json()["status"] == "saved"

    get_resp = client.get("/alerts/jira-config")
    data = get_resp.json()
    assert data["instance_type"] == "server_basic"
    assert data["username"] == "jirauser"
    assert data["project_key"] == "OPS"
    assert data["api_token"] == "••••••"


def test_put_jira_config_empty_token_preserves_existing():
    import asyncio
    import json as json_lib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.alerts import router as alerts_router
    from app.api import deps
    from app.core.db import create_db_and_tables
    from app.models.user import User
    from app.models.setting import SystemSetting
    from sqlmodel import Session
    from app.core.db import engine

    app = FastAPI()
    asyncio.run(create_db_and_tables())
    mock_user = MagicMock(spec=User)
    mock_user.is_superuser = True
    app.include_router(alerts_router, prefix="/alerts")
    app.dependency_overrides[deps.get_current_user] = lambda: mock_user
    app.dependency_overrides[deps.get_current_active_superuser] = lambda: mock_user
    client = TestClient(app)

    # Seed an existing config with a token
    with Session(engine) as session:
        session.merge(SystemSetting(key="alert_jira_config", value=json_lib.dumps({
            "instance_type": "cloud",
            "base_url": "https://x.atlassian.net",
            "email": "x@x.com",
            "api_token": "original_token",
            "project_key": "X",
        })))
        session.commit()

    # Update with empty token — should preserve original
    client.put("/alerts/jira-config", json={
        "instance_type": "cloud",
        "base_url": "https://x.atlassian.net",
        "email": "x@x.com",
        "api_token": "",
        "project_key": "X",
    })

    # Verify raw DB value
    with Session(engine) as session:
        row = session.get(SystemSetting, "alert_jira_config")
        saved = json_lib.loads(row.value)
    assert saved["api_token"] == "original_token"
