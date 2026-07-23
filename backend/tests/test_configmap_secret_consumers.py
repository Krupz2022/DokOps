"""Consumer-restart: a ConfigMap/Secret change is only real once the Deployments,
StatefulSets AND DaemonSets that consume it are rolled — not Deployments alone."""
import pytest
from types import SimpleNamespace as N
from unittest.mock import ANY, AsyncMock, patch

import app.tools.k8s_tools as k

_consumes = k._workload_consumes


def _wl(name, *, env=(), env_from=(), volumes=()):
    """A workload (Deployment/STS/DS all share .spec.template.spec)."""
    c = N(env=list(env), env_from=list(env_from))
    return N(metadata=N(name=name),
             spec=N(template=N(spec=N(containers=[c], init_containers=[], volumes=list(volumes)))))


# ── _workload_consumes truth table ───────────────────────────────────────────

def test_configmap_via_envfrom():
    w = _wl("d", env_from=[N(config_map_ref=N(name="cfg"), secret_ref=None)])
    assert _consumes(w, "configmap", "cfg")
    assert not _consumes(w, "configmap", "other")


def test_configmap_via_valuefrom_and_volume():
    ev = _wl("d", env=[N(value_from=N(config_map_key_ref=N(name="cfg"), secret_key_ref=None))])
    vol = _wl("d", volumes=[N(config_map=N(name="cfg"), secret=None)])
    assert _consumes(ev, "configmap", "cfg")
    assert _consumes(vol, "configmap", "cfg")


def test_secret_via_envfrom_valuefrom_volume():
    ef = _wl("d", env_from=[N(config_map_ref=None, secret_ref=N(name="sec"))])
    ev = _wl("d", env=[N(value_from=N(config_map_key_ref=None, secret_key_ref=N(name="sec")))])
    vol = _wl("d", volumes=[N(config_map=None, secret=N(secret_name="sec"))])
    assert _consumes(ef, "secret", "sec")
    assert _consumes(ev, "secret", "sec")
    assert _consumes(vol, "secret", "sec")


def test_kind_does_not_cross_match():
    # a secret ref must not match a configmap query and vice-versa
    w = _wl("d", env_from=[N(config_map_ref=None, secret_ref=N(name="shared"))])
    assert _consumes(w, "secret", "shared")
    assert not _consumes(w, "configmap", "shared")


# ── _rollout_restart_consumers spans Deployment + StatefulSet + DaemonSet ─────

def _fake_apps(*, deployments=(), statefulsets=(), daemonsets=()):
    apps = N()
    apps.list_namespaced_deployment = AsyncMock(return_value=N(items=list(deployments)))
    apps.list_namespaced_stateful_set = AsyncMock(return_value=N(items=list(statefulsets)))
    apps.list_namespaced_daemon_set = AsyncMock(return_value=N(items=list(daemonsets)))
    apps.patch_namespaced_deployment = AsyncMock()
    apps.patch_namespaced_stateful_set = AsyncMock()
    apps.patch_namespaced_daemon_set = AsyncMock()
    return apps


@pytest.mark.asyncio
async def test_restart_consumers_covers_all_three_kinds():
    cfg = [N(config_map_ref=N(name="cfg"), secret_ref=None)]
    apps = _fake_apps(
        deployments=[_wl("web", env_from=cfg), _wl("unrelated")],
        statefulsets=[_wl("postgres", env_from=cfg)],
        daemonsets=[_wl("agent", env_from=cfg)],
    )
    with patch.object(k.k8s_service, "_get_api", return_value=apps):
        restarted = await k._rollout_restart_consumers("ns", "configmap", "cfg")

    assert restarted == ["deployment/web", "statefulset/postgres", "daemonset/agent"]
    # the unrelated deployment was NOT patched; the consuming one was
    apps.patch_namespaced_deployment.assert_awaited_once_with("web", "ns", ANY)
    apps.patch_namespaced_stateful_set.assert_awaited_once()
    apps.patch_namespaced_daemon_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_consumers_none_match_returns_empty():
    apps = _fake_apps(deployments=[_wl("web")], statefulsets=[_wl("db")])
    with patch.object(k.k8s_service, "_get_api", return_value=apps):
        restarted = await k._rollout_restart_consumers("ns", "secret", "sec")
    assert restarted == []
    apps.patch_namespaced_deployment.assert_not_awaited()
