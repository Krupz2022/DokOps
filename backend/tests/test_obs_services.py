import base64


def test_encrypt_decrypt_roundtrip():
    from app.services.integrations.base import encrypt_credentials, decrypt_credentials
    data = {"token": "secret-value", "extra": 123}
    token = encrypt_credentials(data)
    assert isinstance(token, str)
    result = decrypt_credentials(token)
    assert result == data


def test_build_auth_headers_none():
    from app.services.integrations.base import build_auth_headers
    assert build_auth_headers("none", None) == {}


def test_build_auth_headers_bearer():
    from app.services.integrations.base import encrypt_credentials, build_auth_headers
    token = encrypt_credentials({"token": "mytoken"})
    headers = build_auth_headers("bearer", token)
    assert headers == {"Authorization": "Bearer mytoken"}


def test_build_auth_headers_basic():
    from app.services.integrations.base import encrypt_credentials, build_auth_headers
    creds = encrypt_credentials({"username": "admin", "password": "secret"})
    headers = build_auth_headers("basic", creds)
    expected = base64.b64encode(b"admin:secret").decode()
    assert headers == {"Authorization": f"Basic {expected}"}


def test_build_auth_headers_api_key():
    from app.services.integrations.base import encrypt_credentials, build_auth_headers
    creds = encrypt_credentials({"api_key": "key123", "header_name": "X-Api-Key"})
    headers = build_auth_headers("api_key", creds)
    assert headers == {"X-Api-Key": "key123"}


def test_build_auth_headers_unknown_raises():
    from app.services.integrations.base import build_auth_headers, encrypt_credentials
    creds = encrypt_credentials({"token": "x"})
    import pytest
    with pytest.raises(ValueError, match="Unsupported auth_type"):
        build_auth_headers("apikey", creds)


def test_build_auth_headers_none_creds_returns_empty():
    from app.services.integrations.base import build_auth_headers
    assert build_auth_headers("bearer", None) == {}


import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_prometheus_test_connection_success():
    from app.services.integrations.prometheus import PrometheusService
    svc = PrometheusService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, "1"]}]}}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        ok, msg = await svc.test_connection("http://prometheus:9090", {})
    assert ok is True


@pytest.mark.asyncio
async def test_prometheus_instant_query_tool():
    from app.services.integrations.prometheus import PrometheusService
    svc = PrometheusService()
    headers = {}
    registry = svc.get_tool_registry("http://prometheus:9090", headers)
    assert "prometheus_instant_query" in registry
    tool_fn = registry["prometheus_instant_query"]["function"]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {"__name__": "up"}, "value": [1, "1"]}]}}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await tool_fn(query='up', description='check up metric')
    assert result["success"] is True
    assert "data" in result


@pytest.mark.asyncio
async def test_loki_query_logs_tool():
    from app.services.integrations.loki import LokiService
    svc = LokiService()
    registry = svc.get_tool_registry("http://loki:3100", {})
    assert "loki_query_logs" in registry
    tool_fn = registry["loki_query_logs"]["function"]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "result": [
                {"stream": {"app": "myapp"}, "values": [["1716000000000000000", "error occurred"]]}
            ]
        }
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        result = await tool_fn(log_query='{app="myapp"}', limit=50)
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["log"] == "error occurred"


@pytest.mark.asyncio
async def test_grafana_list_dashboards_tool():
    from app.services.integrations.grafana import GrafanaService
    svc = GrafanaService()
    registry = svc.get_tool_registry("http://grafana:3000", {"Authorization": "Bearer token"})
    assert "grafana_list_dashboards" in registry
    tool_fn = registry["grafana_list_dashboards"]["function"]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"uid": "abc123", "title": "K8s Overview", "url": "/d/abc123/k8s-overview"}
    ]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        result = await tool_fn(search="k8s")
    assert result["success"] is True
    assert result["data"][0]["title"] == "K8s Overview"


@pytest.mark.asyncio
async def test_elasticsearch_search_tool():
    from app.services.integrations.elasticsearch import ElasticsearchService
    svc = ElasticsearchService()
    registry = svc.get_tool_registry("http://es:9200", {})
    assert "elasticsearch_search" in registry
    tool_fn = registry["elasticsearch_search"]["function"]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "hits": {
            "total": {"value": 1},
            "hits": [{"_source": {"message": "OutOfMemoryError", "level": "ERROR"}}]
        }
    }
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await tool_fn(index="logs-*", query_json='{"query":{"match":{"message":"OOM"}}}')
    assert result["success"] is True
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_datadog_query_metrics_tool():
    from app.services.integrations.datadog import DatadogService
    svc = DatadogService()
    registry = svc.get_tool_registry(
        "https://api.datadoghq.com",
        {"DD-API-KEY": "abc", "DD-APPLICATION-KEY": "def"},
    )
    assert "datadog_query_metrics" in registry
    assert "datadog_query_logs" in registry
    tool_fn = registry["datadog_query_metrics"]["function"]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "series": [{"metric": "kubernetes.cpu.usage", "pointlist": [[1716000000000, 0.42]]}]
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        result = await tool_fn(
            query="avg:kubernetes.cpu.usage{*}",
            from_ts=1716000000,
            to_ts=1716003600,
        )
    assert result["success"] is True
