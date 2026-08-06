"""Regression guards for the audited tool-context gaps.

Every test here encodes one field that the Kubernetes API returned and a
DokOps tool threw away. The agent could only ever be as good as the dict it
was handed; these lock the dicts open.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _container_status(name="app", *, waiting=None, last_reason=None,
                      restart_count=0, ready=False):
    state = SimpleNamespace(waiting=None, running=None, terminated=None)
    if waiting:
        state.waiting = SimpleNamespace(reason=waiting, message="back-off restarting")
    last_state = SimpleNamespace(terminated=None)
    if last_reason:
        last_state.terminated = SimpleNamespace(
            reason=last_reason, exit_code=137, message=None)
    return SimpleNamespace(name=name, ready=ready, restart_count=restart_count,
                           state=state, last_state=last_state, image="checkout:1.2")


def _spec_container(name="app", *, limits=None, requests=None):
    return SimpleNamespace(
        name=name, image="checkout:1.2",
        resources=SimpleNamespace(limits=limits or {}, requests=requests or {}),
        volume_mounts=[SimpleNamespace(name="cfg", mount_path="/etc/app")],
    )


async def test_describe_pod_shows_restarts_state_and_limits():
    """The checkoutapi case. describe_pod is advertised as showing container
    specs and resource limits; it returned Phase/Node/Created/Labels only, so
    an agent that picked it for an OOM investigation learned nothing."""
    from app.services.k8s_service import K8sService

    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="checkoutapi-vw2m5", namespace="uat",
                                 creation_timestamp="2026-08-01", labels={"app": "checkoutapi"}),
        spec=SimpleNamespace(node_name="aks-node-b",
                             containers=[_spec_container("checkoutapi", limits={"memory": "50Mi"})]),
        status=SimpleNamespace(
            phase="Running",
            container_statuses=[_container_status(
                "checkoutapi", waiting="CrashLoopBackOff", last_reason="OOMKilled",
                restart_count=591)],
            conditions=[SimpleNamespace(type="Ready", status="False",
                                        reason="ContainersNotReady", message="not ready")],
        ),
    )
    api = MagicMock()
    api.read_namespaced_pod = AsyncMock(return_value=pod)
    api.list_namespaced_event = AsyncMock(return_value=SimpleNamespace(items=[
        SimpleNamespace(type="Warning", reason="BackOff", count=400,
                        message="Back-off restarting failed container",
                        last_timestamp="2026-08-06", event_time=None),
    ]))

    svc = K8sService()
    with patch.object(svc, "_ensure_context_loaded", new=AsyncMock()), \
         patch.object(svc, "_get_api", return_value=api):
        out = await svc.get_pod_details("uat", "checkoutapi-vw2m5")

    assert "591" in out                 # restart count
    assert "OOMKilled" in out           # the kill reason, from last_state
    assert "50Mi" in out                # the limit that caused it
    assert "CrashLoopBackOff" in out    # current state
    assert "ContainersNotReady" in out  # conditions
    assert "Back-off restarting" in out # events
    assert "Phase: Running" in out      # the old four fields still present


async def test_rollout_history_reports_the_recorded_change_cause():
    """'What changed in the last rollout' is the regression question, and the
    tool answered it with a hardcoded 'unknown' while the annotation sat on the
    ReplicaSet that get_replicasets already reads."""
    from app.tools.k8s_tools import get_deployment_rollout_history

    dep = SimpleNamespace(spec=SimpleNamespace(
        selector=SimpleNamespace(match_labels={"app": "checkout"})))
    rs = SimpleNamespace(
        metadata=SimpleNamespace(
            name="checkout-abc", creation_timestamp="2026-08-05",
            annotations={"deployment.kubernetes.io/revision": "7",
                         "kubernetes.io/change-cause": "kubectl set image checkout=checkout:2.2"},
            owner_references=[SimpleNamespace(kind="Deployment", name="checkout")]),
        spec=SimpleNamespace(replicas=1, template=SimpleNamespace(
            spec=SimpleNamespace(containers=[SimpleNamespace(image="checkout:2.2")]))),
        status=SimpleNamespace(ready_replicas=1, conditions=[]),
    )
    api = MagicMock()
    api.read_namespaced_deployment = AsyncMock(return_value=dep)
    api.list_namespaced_replica_set = AsyncMock(return_value=SimpleNamespace(items=[rs]))

    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=api):
        result = await get_deployment_rollout_history("checkout", "uat")

    assert result["success"] is True
    assert result["data"][0]["change_cause"] == "kubectl set image checkout=checkout:2.2"


def _node(name="aks-node-b", *, ready="True", unschedulable=False):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels={"kubernetes.io/os": "linux"}),
        spec=SimpleNamespace(taints=[], unschedulable=unschedulable),
        status=SimpleNamespace(
            capacity={"cpu": "8"}, allocatable={"cpu": "7900m"},
            node_info=SimpleNamespace(kubelet_version="v1.29.4"),
            conditions=[
                SimpleNamespace(type="MemoryPressure", status="False", reason=None, message=None),
                SimpleNamespace(type="Ready", status=ready, reason="KubeletReady", message="ok"),
            ],
        ),
    )


async def test_node_status_reports_readiness_not_the_condition_name():
    """conditions[-1].type is the condition's LABEL. A NotReady node reported
    'Ready' because the code printed the name and never looked at the status."""
    from app.tools.k8s_tools import get_node_status
    api = MagicMock()
    api.list_node = AsyncMock(return_value=SimpleNamespace(items=[_node(ready="False")]))

    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=api):
        result = await get_node_status()

    assert result["data"][0]["status"] == "NotReady"


async def test_node_status_surfaces_cordon():
    """ChatMessage.tsx tells the agent to call get_node_status to confirm a
    cordon took effect. spec.unschedulable was never in the payload."""
    from app.tools.k8s_tools import get_node_status
    api = MagicMock()
    api.list_node = AsyncMock(return_value=SimpleNamespace(items=[_node(unschedulable=True)]))

    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=api):
        result = await get_node_status()

    assert result["data"][0]["schedulable"] is False
    assert result["data"][0]["status"] == "Ready"


async def test_pod_metrics_carries_the_limit_to_compare_against():
    """Registry: 'use when diagnosing OOMKilled'. Usage with no limit beside it
    cannot answer 'is this a lot' — the exact gap that made the agent patch an
    env var instead of the 50Mi limit."""
    from app.tools.k8s_tools import get_pod_metrics

    metrics = {
        "metadata": {"name": "checkoutapi-vw2m5", "namespace": "uat"},
        "containers": [{"name": "checkoutapi", "usage": {"cpu": "12m", "memory": "48Mi"}}],
    }
    pod = SimpleNamespace(spec=SimpleNamespace(containers=[
        _spec_container("checkoutapi", limits={"memory": "50Mi"}, requests={"memory": "50Mi"})]))

    custom = MagicMock()
    custom.get_namespaced_custom_object = AsyncMock(return_value=metrics)
    core = MagicMock()
    core.read_namespaced_pod = AsyncMock(return_value=pod)

    def _api(kind, context=None):
        return custom if kind == "CustomObjectsApi" else core

    with patch("app.tools.k8s_tools.k8s_service._get_api", side_effect=_api):
        result = await get_pod_metrics("checkoutapi-vw2m5", "uat")

    container = result["data"]["containers"][0]
    assert container["memory"] == "48Mi"
    assert container["limits"] == {"memory": "50Mi"}


async def test_pod_metrics_still_returns_usage_when_the_pod_spec_is_unreadable():
    """The limit join is a convenience. Losing it must not lose the metrics."""
    from app.tools.k8s_tools import get_pod_metrics

    metrics = {
        "metadata": {"name": "checkoutapi-vw2m5", "namespace": "uat"},
        "containers": [{"name": "checkoutapi", "usage": {"cpu": "12m", "memory": "48Mi"}}],
    }
    custom = MagicMock()
    custom.get_namespaced_custom_object = AsyncMock(return_value=metrics)
    core = MagicMock()
    core.read_namespaced_pod = AsyncMock(side_effect=Exception("403 forbidden"))

    def _api(kind, context=None):
        return custom if kind == "CustomObjectsApi" else core

    with patch("app.tools.k8s_tools.k8s_service._get_api", side_effect=_api):
        result = await get_pod_metrics("checkoutapi-vw2m5", "uat")

    assert result["success"] is True
    assert result["data"]["containers"][0]["memory"] == "48Mi"
    assert result["data"]["containers"][0]["limits"] == {}


async def test_cluster_health_names_the_kill_reason_in_the_issue():
    """'Which pods are failing' answered 'CrashLoopBackOff' for an OOM, because
    the list view read state.waiting only — same defect get_pod_status had."""
    from app.tools.k8s_tools import get_cluster_health

    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="checkoutapi-vw2m5", namespace="uat"),
        status=SimpleNamespace(phase="Running", container_statuses=[
            _container_status("checkoutapi", waiting="CrashLoopBackOff",
                              last_reason="OOMKilled", restart_count=591)]),
    )
    node = SimpleNamespace(
        metadata=SimpleNamespace(name="n1"),
        status=SimpleNamespace(conditions=[SimpleNamespace(type="Ready", status="True")]))

    api = MagicMock()
    api.list_node = AsyncMock(return_value=SimpleNamespace(items=[node]))
    api.list_pod_for_all_namespaces = AsyncMock(return_value=SimpleNamespace(items=[pod]))

    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=api):
        result = await get_cluster_health()

    issue = result["data"]["unhealthy_pods"][0]["issue"]
    assert "CrashLoopBackOff" in issue
    assert "OOMKilled" in issue


async def test_search_pods_names_the_kill_reason_in_the_status():
    """search_pods has the same waiting-reason-only defect as get_cluster_health,
    on a separate code path (K8sService method, not a k8s_tools function)."""
    from app.services.k8s_service import K8sService

    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="checkoutapi-vw2m5", namespace="uat"),
        status=SimpleNamespace(phase="Running", pod_ip="10.0.0.5", container_statuses=[
            _container_status("checkoutapi", waiting="CrashLoopBackOff",
                              last_reason="OOMKilled", restart_count=591)]),
    )
    api = MagicMock()
    api.list_pod_for_all_namespaces = AsyncMock(return_value=SimpleNamespace(items=[pod]))

    svc = K8sService()
    with patch.object(svc, "_ensure_context_loaded", new=AsyncMock()), \
         patch.object(svc, "_get_api", return_value=api):
        results = await svc.search_pods("failing pods")

    assert results[0]["status"] == "CrashLoopBackOff (last exit OOMKilled)"
