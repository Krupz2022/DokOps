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
