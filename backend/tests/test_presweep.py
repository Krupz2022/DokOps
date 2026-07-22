"""The pre-flight sweep must find what the agent kept forgetting to look for.

Regression: across three identical investigation runs the agent called
get_endpoints once, get_pod_logs once, and neither in the third run — so a
zero-endpoint Service and a CrashLoopBackOff's real error line were each found
once and missed twice. These checks are queries, not judgement calls, so they
run deterministically here.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.presweep import build_presweep, extract_namespace


# ── namespace extraction ─────────────────────────────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("Something is wrong in the dokops-chaos namespace. Investigate.", "dokops-chaos"),
    ("what is broken in namespace payments-prod", "payments-prod"),
    ("check pods -n kube-system please", "kube-system"),
    ("investigate the NAMESPACE Web-Tier", "web-tier"),
    ("why is my cluster unhealthy", None),
    ("what is wrong in the namespace", None),        # stopword, not a name
    ("anything broken in this namespace?", None),    # stopword, not a name
])
def test_extract_namespace(query, expected):
    assert extract_namespace(query) == expected


# ── sweep content ────────────────────────────────────────────────────────────

def _pod(name, labels, container=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels=labels),
        status=SimpleNamespace(container_statuses=[container] if container else []),
    )


def _crashing_container(name="worker"):
    return SimpleNamespace(
        name=name,
        restart_count=4,
        state=SimpleNamespace(waiting=SimpleNamespace(reason="CrashLoopBackOff")),
    )


def _fake_core(*, endpoints, services, pods):
    core = SimpleNamespace()
    core.list_namespaced_endpoints = AsyncMock(return_value=SimpleNamespace(items=endpoints))
    core.list_namespaced_service = AsyncMock(return_value=SimpleNamespace(items=services))
    core.list_namespaced_pod = AsyncMock(return_value=SimpleNamespace(items=pods))
    core.read_namespaced_pod_log = AsyncMock(
        return_value="starting up\nFATAL: could not connect to postgres at db.internal:5432"
    )
    return core


def _fake_apps(deployments):
    apps = SimpleNamespace()
    apps.list_namespaced_deployment = AsyncMock(return_value=SimpleNamespace(items=deployments))
    return apps


def _svc(name, selector, type_="ClusterIP"):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(selector=selector, type=type_),
    )


def _patch_apis(core, apps):
    def _get_api(kind, context=None):
        return core if kind == "CoreV1Api" else apps
    return patch("app.services.presweep.k8s_service._get_api", side_effect=_get_api)


@pytest.mark.asyncio
async def test_reports_zero_endpoint_service_with_selector_and_pod_labels():
    """The exact miss: healthy pods, typo'd selector, no endpoints."""
    core = _fake_core(
        endpoints=[SimpleNamespace(metadata=SimpleNamespace(name="web-frontend"), subsets=None)],
        services=[_svc("web-frontend", {"app": "web-fronted"})],
        pods=[_pod("web-frontend-abc", {"app": "web-frontend"})],
    )
    with _patch_apis(core, _fake_apps([])):
        out = await build_presweep("dokops-chaos")

    assert "web-frontend: 0 endpoints" in out
    assert "app=web-fronted" in out      # the selector, with the typo
    assert "app=web-frontend" in out     # the real pod labels, to compare against


@pytest.mark.asyncio
async def test_reports_crash_log_line():
    container = _crashing_container()
    core = _fake_core(
        endpoints=[], services=[],
        pods=[_pod("order-worker-xyz", {"app": "order-worker"}, container)],
    )
    with _patch_apis(core, _fake_apps([])):
        out = await build_presweep("dokops-chaos")

    assert "could not connect to postgres" in out


@pytest.mark.asyncio
async def test_reports_unready_deployment():
    deployment = SimpleNamespace(
        metadata=SimpleNamespace(name="sample-api"),
        spec=SimpleNamespace(replicas=3),
        status=SimpleNamespace(ready_replicas=1),
    )
    core = _fake_core(endpoints=[], services=[], pods=[])
    with _patch_apis(core, _fake_apps([deployment])):
        out = await build_presweep("dokops-chaos")

    assert "sample-api: 1/3 ready" in out


@pytest.mark.asyncio
async def test_externalname_service_is_not_reported_as_broken():
    """A selector-less Service has no endpoints by design — flagging it would be
    a manufactured finding, which erodes trust in the real ones."""
    core = _fake_core(
        endpoints=[SimpleNamespace(metadata=SimpleNamespace(name="ext-db"), subsets=None)],
        services=[_svc("ext-db", None, type_="ExternalName")],
        pods=[],
    )
    with _patch_apis(core, _fake_apps([])):
        out = await build_presweep("dokops-chaos")

    assert "ext-db" not in out


@pytest.mark.asyncio
async def test_healthy_namespace_produces_no_block():
    """Nothing wrong must yield an empty string, not an empty-sections header."""
    core = _fake_core(
        endpoints=[SimpleNamespace(
            metadata=SimpleNamespace(name="web"),
            subsets=[SimpleNamespace(addresses=[SimpleNamespace(ip="10.0.0.1")])],
        )],
        services=[_svc("web", {"app": "web"})],
        pods=[_pod("web-1", {"app": "web"})],
    )
    deployment = SimpleNamespace(
        metadata=SimpleNamespace(name="web"),
        spec=SimpleNamespace(replicas=1),
        status=SimpleNamespace(ready_replicas=1),
    )
    with _patch_apis(core, _fake_apps([deployment])):
        out = await build_presweep("dokops-clean")

    assert out == ""


@pytest.mark.asyncio
async def test_returns_empty_when_cluster_unreachable():
    """Mock mode / no kubeconfig returns None from _get_api — must not raise."""
    with patch("app.services.presweep.k8s_service._get_api", return_value=None):
        assert await build_presweep("anything") == ""


@pytest.mark.asyncio
async def test_api_failure_does_not_raise():
    core = _fake_core(endpoints=[], services=[], pods=[])
    core.list_namespaced_endpoints = AsyncMock(side_effect=Exception("api down"))
    with _patch_apis(core, _fake_apps([])):
        assert await build_presweep("dokops-chaos") == ""
