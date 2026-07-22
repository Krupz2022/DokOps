import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


def _pod(name, namespace, phase):
    p = MagicMock()
    p.metadata.name = name
    p.metadata.namespace = namespace
    p.spec.node_name = "node-1"
    p.status.phase = phase
    p.status.container_statuses = []
    return p


def _core_api(pods):
    api = MagicMock()
    result = MagicMock()
    result.items = pods
    api.list_namespaced_pod = AsyncMock(return_value=result)
    api.list_pod_for_all_namespaces = AsyncMock(return_value=result)
    return api


async def _search(pods, **kwargs):
    from app.tools import k8s_tools
    with patch.object(k8s_tools.k8s_service, "_get_api", return_value=_core_api(pods)):
        return await k8s_tools.search_pods(**kwargs)


async def test_no_keyword_lists_all_pods_including_healthy():
    """The agent-facing gap: enumerating a healthy namespace must not return []."""
    pods = [_pod("web-1", "test-ns", "Running"), _pod("job-1", "test-ns", "Pending")]
    res = await _search(pods, namespace="test-ns")
    assert res["success"]
    assert {p["name"] for p in res["data"]} == {"web-1", "job-1"}


async def test_generic_keyword_still_filters_to_unhealthy():
    pods = [_pod("web-1", "test-ns", "Running"), _pod("job-1", "test-ns", "Pending")]
    res = await _search(pods, keyword="broken", namespace="test-ns")
    assert [p["name"] for p in res["data"]] == ["job-1"]


async def test_specific_keyword_matches_by_name():
    pods = [_pod("web-1", "test-ns", "Running"), _pod("job-1", "test-ns", "Running")]
    res = await _search(pods, keyword="web", namespace="test-ns")
    assert [p["name"] for p in res["data"]] == ["web-1"]
