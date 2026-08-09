"""Byte-level golden files for presweep's rendered prose.

The prose feeds both the model and the provider's prefix cache, so whitespace
drift silently invalidates cached prefixes. These goldens are generated from
UNMODIFIED code and committed before any refactor; a refactor then asserts a
zero diff against them.

Regenerate ONLY under one of the two gates in the design spec:
  refactor task      -> diff must be 0
  coverage extension -> diff must equal a prediction written down beforehand
Never regenerate to "make the test pass".
"""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.presweep import build_presweep, build_config_sources

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "presweep_golden"
REGENERATE = os.environ.get("REGENERATE_PRESWEEP_GOLDENS") == "1"


# ── fixture builders (self-contained: goldens must not drift when other
#    test modules refactor their helpers) ──────────────────────────────────

def _svc(name, selector=None, svc_type="ClusterIP"):
    return SimpleNamespace(metadata=SimpleNamespace(name=name),
                           spec=SimpleNamespace(selector=selector, type=svc_type))


def _endpoints(name, addresses=()):
    subsets = [SimpleNamespace(addresses=list(addresses))] if addresses else []
    return SimpleNamespace(metadata=SimpleNamespace(name=name), subsets=subsets)


def _dep(name, replicas=1, ready=1):
    return SimpleNamespace(metadata=SimpleNamespace(name=name),
                           spec=SimpleNamespace(replicas=replicas),
                           status=SimpleNamespace(ready_replicas=ready))


def _cs(name="app", *, waiting=None, last_reason=None, restarts=0):
    state = SimpleNamespace(waiting=None, running=None, terminated=None)
    if waiting:
        state.waiting = SimpleNamespace(reason=waiting, message="back-off restarting")
    last = SimpleNamespace(terminated=None)
    if last_reason:
        last.terminated = SimpleNamespace(reason=last_reason, exit_code=137, message=None)
    return SimpleNamespace(name=name, restart_count=restarts, state=state, last_state=last)


def _pod(name, labels=None, container=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels=labels or {}),
        status=SimpleNamespace(container_statuses=[container] if container else []),
    )


def _core(*, endpoints=(), services=(), pods=(), events=()):
    c = SimpleNamespace()
    c.list_namespaced_endpoints = AsyncMock(return_value=SimpleNamespace(items=list(endpoints)))
    c.list_namespaced_service = AsyncMock(return_value=SimpleNamespace(items=list(services)))
    c.list_namespaced_pod = AsyncMock(return_value=SimpleNamespace(items=list(pods)))
    c.list_namespaced_event = AsyncMock(return_value=SimpleNamespace(items=list(events)))
    c.read_namespaced_pod_log = AsyncMock(return_value="starting up\nFATAL: could not connect to postgres at db.internal:5432")
    c.read_namespaced_config_map = AsyncMock(side_effect=Exception("not needed"))
    return c


def _apps(deployments=(), replica_sets=()):
    a = SimpleNamespace()
    a.list_namespaced_deployment = AsyncMock(return_value=SimpleNamespace(items=list(deployments)))
    a.list_namespaced_replica_set = AsyncMock(return_value=SimpleNamespace(items=list(replica_sets)))
    a.list_namespaced_stateful_set = AsyncMock(return_value=SimpleNamespace(items=[]))
    a.list_namespaced_daemon_set = AsyncMock(return_value=SimpleNamespace(items=[]))
    return a


def _apis(core, apps):
    def _get(kind, context=None):
        return apps if kind == "AppsV1Api" else core
    return patch("app.services.presweep.k8s_service._get_api", side_effect=_get)


# ── scenarios: name -> async callable returning the rendered prose ─────────

async def _s_crashloop_oom():
    core = _core(pods=[_pod("checkoutapi-vw2m5", {"app": "checkoutapi"},
                            _cs("checkoutapi", waiting="CrashLoopBackOff",
                                last_reason="OOMKilled", restarts=591))])
    core.read_namespaced_pod_log = AsyncMock(return_value="Minimum worker threads: 100")
    with _apis(core, _apps()):
        return await build_presweep("dokops-chaos")


async def _s_crashloop_plain():
    core = _core(pods=[_pod("order-worker-qz", {"app": "order-worker"},
                            _cs("worker", waiting="CrashLoopBackOff", restarts=4))])
    with _apis(core, _apps()):
        return await build_presweep("dokops-chaos")


async def _s_blocked_configmap():
    cs = SimpleNamespace(name="app", restart_count=0,
                         state=SimpleNamespace(waiting=SimpleNamespace(reason="CreateContainerConfigError")))
    ev = SimpleNamespace(type="Warning", reason="Failed",
                         involved_object=SimpleNamespace(name="notify-svc-x"),
                         message="couldn't find key smtp_host in ConfigMap notify-config")
    core = _core(pods=[_pod("notify-svc-x", {"app": "notify"}, cs)], events=[ev])
    with _apis(core, _apps()):
        return await build_presweep("dokops-chaos")


async def _s_zero_endpoint_selector_mismatch():
    core = _core(endpoints=[_endpoints("web-frontend")],
                 services=[_svc("web-frontend", selector={"app": "web-fronted"})],
                 pods=[_pod("web-1", {"app": "web-frontend"})])
    with _apis(core, _apps()):
        return await build_presweep("dokops-chaos")


async def _s_zero_endpoint_no_selector():
    core = _core(endpoints=[_endpoints("headless")], services=[_svc("headless", selector=None)])
    with _apis(core, _apps()):
        return await build_presweep("dokops-chaos")


async def _s_deployment_scaled_to_zero():
    with _apis(_core(), _apps([_dep("batch-worker", replicas=0, ready=0)])):
        return await build_presweep("dokops-chaos")


async def _s_replicaset_quota_failure():
    rs = SimpleNamespace(metadata=SimpleNamespace(
        name="api-755d", owner_references=[SimpleNamespace(kind="Deployment", name="api")]))
    ev = SimpleNamespace(type="Warning", reason="FailedCreate",
                         involved_object=SimpleNamespace(name="api-755d"),
                         message='pods "x" is forbidden: exceeded quota: no-pods-allowed')
    with _apis(_core(events=[ev]), _apps([_dep("api", 1, 0)], [rs])):
        return await build_presweep("dokops-chaos")


async def _s_collector_raises_deployments():
    apps = _apps()
    apps.list_namespaced_deployment = AsyncMock(side_effect=RuntimeError("apps API down"))
    core = _core(endpoints=[_endpoints("web")], services=[_svc("web", selector={"app": "web"})])
    with _apis(core, apps):
        return await build_presweep("dokops-chaos")


async def _s_collector_raises_pod_listing():
    core = _core()
    core.list_namespaced_pod = AsyncMock(side_effect=RuntimeError("pod list failed"))
    with _apis(core, _apps([_dep("api", 1, 0)])):
        return await build_presweep("dokops-chaos")


async def _s_no_previous_log():
    core = _core(pods=[_pod("api-xyz", {"app": "api"},
                            _cs("app", waiting="CrashLoopBackOff", restarts=2))])
    core.read_namespaced_pod_log = AsyncMock(
        side_effect=[RuntimeError("previous terminated container not found"),
                     "starting up\nFATAL: config missing"])
    with _apis(core, _apps()):
        return await build_presweep("dokops-chaos")


async def _s_empty_namespace():
    with _apis(_core(), _apps()):
        return await build_presweep("dokops-chaos")


async def _s_image_pull_backoff():
    cs = SimpleNamespace(name="app", restart_count=0,
                         state=SimpleNamespace(waiting=SimpleNamespace(reason="ImagePullBackOff")))
    ev = SimpleNamespace(type="Warning", reason="Failed",
                         involved_object=SimpleNamespace(name="api-abc"),
                         message='Failed to pull image "registry.io/api:2.9": not found')
    core = _core(pods=[_pod("api-abc", {"app": "api"}, cs)], events=[ev])
    with _apis(core, _apps()):
        return await build_presweep("dokops-chaos")


_WORKLOAD_CONFIG = {
    "success": True,
    "data": {
        "deployment": "checkout-api", "namespace": "payments",
        "volume_configmaps": [], "volume_secrets": [],
        "containers": [{
            "container_name": "checkout",
            "env_vars": [
                {"name": "LOG_LEVEL", "source": "configMapKeyRef",
                 "configmap_name": "checkout-config", "key": "log_level"},
                {"name": "PORT", "source": "literal", "value": "8080"},
                {"name": "DB_PASSWORD", "source": "literal", "value": "hunter2"},
            ],
            "env_from_configmaps": [{"configmap_name": "checkout-flags", "prefix": None}],
            "env_from_secrets": [],
            "volume_mounts": [],
            "limits": {"memory": "50Mi"}, "requests": {"memory": "50Mi"},
        }],
    },
    "error": None, "source": "k8s_client",
}


async def _s_config_sources_with_resources():
    apps = _apps()
    apps.list_namespaced_deployment = AsyncMock(return_value=SimpleNamespace(
        items=[SimpleNamespace(metadata=SimpleNamespace(name="checkout-api"))]))
    with _apis(_core(), apps), \
         patch("app.tools.k8s_tools.get_workload_config",
               AsyncMock(return_value=_WORKLOAD_CONFIG)):
        return await build_config_sources("payments", "fix the OOM in checkout-api")


SCENARIOS = {
    "crashloop_oom": _s_crashloop_oom,
    "crashloop_plain": _s_crashloop_plain,
    "blocked_configmap": _s_blocked_configmap,
    "zero_endpoint_selector_mismatch": _s_zero_endpoint_selector_mismatch,
    "zero_endpoint_no_selector": _s_zero_endpoint_no_selector,
    "deployment_scaled_to_zero": _s_deployment_scaled_to_zero,
    "replicaset_quota_failure": _s_replicaset_quota_failure,
    "collector_raises_deployments": _s_collector_raises_deployments,
    "collector_raises_pod_listing": _s_collector_raises_pod_listing,
    "no_previous_log": _s_no_previous_log,
    "empty_namespace": _s_empty_namespace,
    "image_pull_backoff": _s_image_pull_backoff,
    "config_sources_with_resources": _s_config_sources_with_resources,
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
async def test_presweep_prose_matches_golden(name):
    rendered = await SCENARIOS[name]()
    path = GOLDEN_DIR / f"{name}.txt"
    if REGENERATE:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")
        pytest.skip(f"regenerated {path.name}")
    assert path.exists(), f"missing golden {path.name} — regenerate deliberately, under a gate"
    assert rendered == path.read_text(encoding="utf-8"), (
        f"presweep prose changed for scenario '{name}'.\n"
        "A refactor must produce a ZERO diff. If this change is intentional, it belongs "
        "in a coverage task with a written-down predicted diff — see the design spec §6."
    )
