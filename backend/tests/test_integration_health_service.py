import pytest
from datetime import datetime, timezone
from app.services.integration_health_service import IntegrationHealthService, HealthEntry


@pytest.mark.asyncio
async def test_empty_snapshot_before_checks_run():
    svc = IntegrationHealthService()
    snapshot = await svc.get_snapshot()
    assert snapshot == {}


@pytest.mark.asyncio
async def test_get_snapshot_returns_copy():
    svc = IntegrationHealthService()
    async with svc._lock:
        svc._cache["es"] = HealthEntry(healthy=True, checked_at=datetime.now(tz=timezone.utc))

    snapshot = await svc.get_snapshot()
    snapshot["injected"] = "should not appear"

    snapshot2 = await svc.get_snapshot()
    assert "injected" not in snapshot2


from unittest.mock import MagicMock, AsyncMock, patch


def _make_async_session_mock(rows):
    """Build an AsyncSessionLocal context-manager mock that returns given rows from exec()."""
    mock_session = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.all.return_value = rows
    mock_session.exec = AsyncMock(return_value=mock_exec_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


@pytest.mark.asyncio
async def test_healthy_integration_stored_in_cache():
    svc = IntegrationHealthService()

    mock_row = MagicMock()
    mock_row.backend = "elasticsearch"
    mock_row.base_url = "http://es:9200"
    mock_row.auth_type = "none"
    mock_row.encrypted_credentials = None

    mock_svc_instance = AsyncMock()
    mock_svc_instance.test_connection = AsyncMock(return_value=(True, "Connected"))
    mock_svc_class = MagicMock(return_value=mock_svc_instance)

    mock_cm = _make_async_session_mock([mock_row])

    with patch("app.services.integration_health_service.AsyncSessionLocal", return_value=mock_cm), \
         patch.dict("app.services.integration_health_service._SERVICE_MAP",
                    {"elasticsearch": mock_svc_class}, clear=True), \
         patch("app.services.integration_health_service.build_auth_headers", return_value={}):
        await svc._check_integrations()

    snapshot = await svc.get_snapshot()
    assert snapshot["elasticsearch"].healthy is True
    assert snapshot["elasticsearch"].error is None


@pytest.mark.asyncio
async def test_unreachable_integration_stored_in_cache():
    svc = IntegrationHealthService()

    mock_row = MagicMock()
    mock_row.backend = "loki"
    mock_row.base_url = "http://loki:3100"
    mock_row.auth_type = "none"
    mock_row.encrypted_credentials = None

    mock_svc_instance = AsyncMock()
    mock_svc_instance.test_connection = AsyncMock(return_value=(False, "connection refused"))
    mock_svc_class = MagicMock(return_value=mock_svc_instance)

    mock_cm = _make_async_session_mock([mock_row])

    with patch("app.services.integration_health_service.AsyncSessionLocal", return_value=mock_cm), \
         patch.dict("app.services.integration_health_service._SERVICE_MAP",
                    {"loki": mock_svc_class}, clear=True), \
         patch("app.services.integration_health_service.build_auth_headers", return_value={}):
        await svc._check_integrations()

    snapshot = await svc.get_snapshot()
    assert snapshot["loki"].healthy is False
    assert snapshot["loki"].error == "connection refused"


@pytest.mark.asyncio
async def test_exception_in_test_connection_marks_unhealthy():
    svc = IntegrationHealthService()

    mock_row = MagicMock()
    mock_row.backend = "datadog"
    mock_row.base_url = "http://datadog"
    mock_row.auth_type = "none"
    mock_row.encrypted_credentials = None

    mock_svc_instance = AsyncMock()
    mock_svc_instance.test_connection = AsyncMock(side_effect=RuntimeError("timeout"))
    mock_svc_class = MagicMock(return_value=mock_svc_instance)

    mock_cm = _make_async_session_mock([mock_row])

    with patch("app.services.integration_health_service.AsyncSessionLocal", return_value=mock_cm), \
         patch.dict("app.services.integration_health_service._SERVICE_MAP",
                    {"datadog": mock_svc_class}, clear=True), \
         patch("app.services.integration_health_service.build_auth_headers", return_value={}):
        await svc._check_integrations()

    snapshot = await svc.get_snapshot()
    assert snapshot["datadog"].healthy is False
    assert "timeout" in snapshot["datadog"].error


@pytest.mark.asyncio
async def test_unknown_backend_marked_unhealthy():
    svc = IntegrationHealthService()

    mock_row = MagicMock()
    mock_row.backend = "unknown_service"

    mock_cm = _make_async_session_mock([mock_row])

    with patch("app.services.integration_health_service.AsyncSessionLocal", return_value=mock_cm), \
         patch.dict("app.services.integration_health_service._SERVICE_MAP", {}, clear=True):
        await svc._check_integrations()

    snapshot = await svc.get_snapshot()
    assert snapshot["unknown_service"].healthy is False
    assert "Unknown backend" in snapshot["unknown_service"].error


import asyncio


@pytest.mark.asyncio
async def test_k8s_healthy_when_list_namespaces_succeeds():
    svc = IntegrationHealthService()

    mock_k8s = MagicMock()
    mock_k8s.mock_mode = False
    mock_k8s.list_namespaces = AsyncMock(return_value=["default", "kube-system"])

    with patch("app.services.integration_health_service.k8s_service", mock_k8s):
        await svc._check_kubernetes()

    snapshot = await svc.get_snapshot()
    assert snapshot["kubernetes"].healthy is True
    assert snapshot["kubernetes"].error is None


@pytest.mark.asyncio
async def test_k8s_unhealthy_when_timeout():
    svc = IntegrationHealthService()

    mock_k8s = MagicMock()
    mock_k8s.mock_mode = False
    mock_k8s.list_namespaces = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch("app.services.integration_health_service.k8s_service", mock_k8s):
        await svc._check_kubernetes()

    snapshot = await svc.get_snapshot()
    assert snapshot["kubernetes"].healthy is False
    assert snapshot["kubernetes"].error == "unreachable"


@pytest.mark.asyncio
async def test_k8s_skipped_in_mock_mode():
    svc = IntegrationHealthService()

    mock_k8s = MagicMock()
    mock_k8s.mock_mode = True

    with patch("app.services.integration_health_service.k8s_service", mock_k8s):
        await svc._check_kubernetes()

    snapshot = await svc.get_snapshot()
    assert "kubernetes" not in snapshot
