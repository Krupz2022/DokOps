import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.services.ai_service import AIService


def _unhealthy(error: str):
    return SimpleNamespace(healthy=False, error=error)


def _healthy():
    return SimpleNamespace(healthy=True, error=None)


@pytest.mark.asyncio
async def test_warning_event_emitted_for_unhealthy_integration():
    snapshot = {"elasticsearch": _unhealthy("connection refused")}
    mock_health = AsyncMock()
    mock_health.get_snapshot = AsyncMock(return_value=snapshot)

    with patch("app.services.integration_health_service.integration_health", mock_health):
        svc = AIService()
        warnings, _, _ = await svc._run_prerequisite_check()

    assert len(warnings) == 1
    assert warnings[0]["type"] == "warning"
    assert "elasticsearch" in warnings[0]["message"]
    assert "connection refused" in warnings[0]["message"]


@pytest.mark.asyncio
async def test_kubernetes_excluded_from_integration_filter_names():
    snapshot = {
        "elasticsearch": _unhealthy("timeout"),
        "kubernetes": _unhealthy("unreachable"),
    }
    mock_health = AsyncMock()
    mock_health.get_snapshot = AsyncMock(return_value=snapshot)

    with patch("app.services.integration_health_service.integration_health", mock_health):
        svc = AIService()
        _, unhealthy_int_names, _ = await svc._run_prerequisite_check()

    assert "elasticsearch" in unhealthy_int_names
    assert "kubernetes" not in unhealthy_int_names


@pytest.mark.asyncio
async def test_empty_snapshot_is_fail_open():
    mock_health = AsyncMock()
    mock_health.get_snapshot = AsyncMock(return_value={})

    with patch("app.services.integration_health_service.integration_health", mock_health):
        svc = AIService()
        warnings, unhealthy_int_names, block = await svc._run_prerequisite_check()

    assert warnings == []
    assert len(unhealthy_int_names) == 0
    assert block == ""


@pytest.mark.asyncio
async def test_dead_integration_tool_excluded_from_obs_registry():
    unhealthy_int_names = frozenset({"elasticsearch"})
    obs_raw = {
        "elasticsearch_search": {"description": "ES search", "inputs": []},
        "loki_query_logs": {"description": "Loki logs", "inputs": []},
    }
    filtered = {
        name: tool for name, tool in obs_raw.items()
        if not any(name.startswith(p) for p in unhealthy_int_names)
    }
    assert "elasticsearch_search" not in filtered
    assert "loki_query_logs" in filtered


@pytest.mark.asyncio
async def test_unavailability_block_contains_tool_names():
    snapshot = {
        "elasticsearch": _unhealthy("connection refused"),
        "kubernetes": _unhealthy("timeout"),
    }
    mock_health = AsyncMock()
    mock_health.get_snapshot = AsyncMock(return_value=snapshot)

    with patch("app.services.integration_health_service.integration_health", mock_health):
        svc = AIService()
        _, _, block = await svc._run_prerequisite_check()

    assert "UNAVAILABLE TOOLS" in block
    assert "elasticsearch" in block
    assert "kubernetes" in block
    assert "connection refused" in block
