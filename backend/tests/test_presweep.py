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

from app.services.presweep import (
    _rollout_state, append_missing_findings, build_presweep, extract_namespace,
    namespace_of_write, resolve_namespace, settle_after_write,
)


# ── settle after a write ─────────────────────────────────────────────────────

@pytest.mark.parametrize("inputs,expected", [
    ({"namespace": "dokops-chaos", "reason": "x"}, "dokops-chaos"),
    ({"manifest_yaml": "kind: ConfigMap\nmetadata:\n  name: c\n  namespace: payments\n"}, "payments"),
    ({"manifest_yaml": "kind: ConfigMap\nmetadata:\n  name: c\n"}, None),
    ({}, None),
])
def test_namespace_of_write(inputs, expected):
    assert namespace_of_write(inputs) == expected


# ── namespace resolution against the live cluster ────────────────────────────

def _ns_lister(*names):
    core = SimpleNamespace()
    core.list_namespace = AsyncMock(return_value=SimpleNamespace(
        items=[SimpleNamespace(metadata=SimpleNamespace(name=n)) for n in names]
    ))
    return core


@pytest.mark.asyncio
async def test_resolves_namespace_named_without_the_word_namespace():
    """Regression: "why is api-gateway not running in dokops-chaos?" never says
    "namespace", so the regex returned None, the sweep silently did not run, and
    the agent answered from speculation."""
    core = _ns_lister("default", "kube-system", "dokops-chaos")
    with patch("app.services.presweep.k8s_service._get_api", return_value=core):
        got = await resolve_namespace("Why is api-gateway not running in dokops-chaos?")
    assert got == "dokops-chaos"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "Three services are down in dokops-chaos. Find the cause.",   # trailing period
    "Three services are down in dokops-chaos?",                   # trailing question mark
    "check dokops-chaos, something is broken",                    # trailing comma
    "look at dokops-chaos",                                       # no punctuation
])
async def test_trailing_punctuation_does_not_break_resolution(query):
    """Regression: the token pattern must allow '.' for names like team-a.prod,
    so it swallowed sentence-ending periods — "dokops-chaos." never matched and
    the sweep silently produced nothing. The '?' form worked, the '.' form did not."""
    core = _ns_lister("default", "dokops-chaos")
    with patch("app.services.presweep.k8s_service._get_api", return_value=core):
        assert await resolve_namespace(query) == "dokops-chaos"


@pytest.mark.asyncio
async def test_longest_namespace_match_wins():
    core = _ns_lister("dokops", "dokops-chaos")
    with patch("app.services.presweep.k8s_service._get_api", return_value=core):
        got = await resolve_namespace("something broke in dokops-chaos today")
    assert got == "dokops-chaos"


@pytest.mark.asyncio
async def test_regex_form_does_not_need_the_cluster():
    """An explicit "namespace X" must resolve without an API call."""
    with patch("app.services.presweep.k8s_service._get_api", return_value=None):
        got = await resolve_namespace("what is broken in namespace payments-prod")
    assert got == "payments-prod"


@pytest.mark.asyncio
async def test_unmatched_query_resolves_to_none():
    core = _ns_lister("default", "dokops-chaos")
    with patch("app.services.presweep.k8s_service._get_api", return_value=core):
        got = await resolve_namespace("is my cluster healthy")
    assert got is None


# ── answer coverage ──────────────────────────────────────────────────────────

_SWEEP = """PRE-FLIGHT SWEEP of namespace 'dokops-chaos' — verified facts.
Services with NO ready endpoints (broken even if their pods are Running):
  - web-frontend: 0 endpoints. selector={app=web-fronted}
  pod labels present in this namespace: app=web-frontend
Logs from crashing containers:
  - order-worker-qzfjg/worker (CrashLoopBackOff):
      FATAL: could not connect to postgres
"""


def test_omitted_finding_is_appended():
    """The exact regression: four pod diagnoses, Service silently dropped."""
    answer = "Pod order-worker-qzfjg is crashlooping against postgres."
    out = append_missing_findings(_SWEEP, answer)

    assert "Also found by the pre-flight sweep" in out
    assert "web-frontend: 0 endpoints" in out
    assert out.startswith(answer)          # original answer preserved verbatim


def test_appended_crash_bullet_carries_its_log_body():
    """Regression: appending only the bullet produced
    "billing-x/app (CrashLoopBackOff):" with no error message — the log body
    lives on the indented continuation line and was dropped."""
    out = append_missing_findings(_SWEEP, "Only postgres is discussed here.")

    assert "order-worker-qzfjg/worker (CrashLoopBackOff):" in out
    assert "FATAL: could not connect to postgres" in out


def test_naming_the_resource_is_not_reporting_the_finding():
    """Scenario 02 regression: the answer said "api-gateway is not creating pods"
    and the quota rejection counted as covered purely because the name appeared.
    Coverage must require a concrete fact, not a mention."""
    sweep = (
        "Deployments that produced NO pods (failure is on the ReplicaSet):\n"
        "  - api-gateway (ReplicaSet api-gateway-755d4d56d5) FailedCreate: "
        'Error creating: pods "x" is forbidden: exceeded quota: no-pods-allowed\n'
    )
    vague = "The api-gateway Deployment is not creating pods; review its configuration."
    out = append_missing_findings(sweep, vague)

    assert "Also found by the pre-flight sweep" in out
    assert "exceeded quota" in out


def test_concrete_report_counts_as_covered():
    sweep = (
        "Deployments that produced NO pods (failure is on the ReplicaSet):\n"
        "  - api-gateway (ReplicaSet api-gateway-755d4d56d5) FailedCreate: "
        'Error creating: pods "x" is forbidden: exceeded quota: no-pods-allowed\n'
    )
    concrete = (
        "api-gateway cannot create pods: FailedCreate — forbidden, exceeded quota "
        "no-pods-allowed. Raise the ResourceQuota."
    )
    assert append_missing_findings(sweep, concrete) == concrete


def test_covered_findings_are_not_appended():
    answer = (
        "web-frontend has 0 endpoints; order-worker-qzfjg is in CrashLoopBackOff "
        "because it cannot reach postgres."
    )
    assert append_missing_findings(_SWEEP, answer) == answer


def test_continuation_and_context_lines_are_not_treated_as_findings():
    """Only bullets are findings — log bodies and the pod-labels note are not.

    Both bullets are reported concretely here, so if anything is appended it can
    only be a non-bullet line that was mistaken for a finding.
    """
    answer = (
        "web-frontend: 0 endpoints, selector app=web-fronted does not match its pods. "
        "order-worker-qzfjg is in CrashLoopBackOff against postgres."
    )
    out = append_missing_findings(_SWEEP, answer)

    assert out == answer, "a non-bullet line was mistaken for a finding"


@pytest.mark.parametrize("query", [
    "Why is api-gateway not running in dokops-chaos?",
    "the checkout pod is stuck in namespace shop",
    "no pods in namespace batch",
])
def test_failure_signals_floor_these_to_investigate(query):
    """These phrasings scored SIMPLE, which skipped the whole investigation.

    Regression: "why is api-gateway not running in dokops-chaos" was classified
    simple on one run and investigate on the next; the simple run answered "the
    pod does not exist, it may have been removed" after four tool calls.
    """
    from app.services.ai_service import AIService

    assert any(sig in query.lower() for sig in AIService._FAILURE_SIGNALS), (
        "query would not be floored to investigate"
    )


@pytest.mark.asyncio
async def test_settle_reports_remaining_problems_not_success():
    """The exact silent failure: a ConfigMap created with the wrong key applied
    cleanly, was reported as success, and left the pod broken."""
    container = SimpleNamespace(
        name="app", restart_count=0,
        state=SimpleNamespace(waiting=SimpleNamespace(reason="CreateContainerConfigError")),
    )
    core = _fake_core(endpoints=[], services=[],
                      pods=[_pod("notify-svc-x", {"app": "notify-svc"}, container)])
    core.list_namespaced_event = AsyncMock(return_value=SimpleNamespace(items=[
        SimpleNamespace(type="Warning", reason="Failed",
                        involved_object=SimpleNamespace(name="notify-svc-x"),
                        message="Error: couldn't find key smtp_host in ConfigMap x/notify-config")
    ]))
    with _patch_apis(core, _fake_apps([])):
        out = await settle_after_write("dokops-chaos", timeout=0.01, interval=0.001)

    assert "REMAIN" in out
    assert "do NOT report success" in out
    assert "couldn't find key smtp_host" in out


@pytest.mark.asyncio
async def test_settle_confirms_success_when_healthy():
    core = _fake_core(
        endpoints=[SimpleNamespace(metadata=SimpleNamespace(name="web"),
                                   subsets=[SimpleNamespace(addresses=[SimpleNamespace(ip="10.0.0.1")])])],
        services=[_svc("web", {"app": "web"})],
        pods=[_pod("web-1", {"app": "web"})],
    )
    healthy = SimpleNamespace(
        metadata=SimpleNamespace(name="web"),
        spec=SimpleNamespace(replicas=1),
        status=SimpleNamespace(ready_replicas=1),
    )
    with _patch_apis(core, _fake_apps([healthy])):
        out = await settle_after_write("dokops-clean", timeout=0.01, interval=0.001)

    assert "The fix worked" in out
    assert "REMAIN" not in out


@pytest.mark.asyncio
async def test_settle_waits_for_a_rollout_instead_of_reporting_it_broken():
    """Regression: an image patch was verified 5s after apply, caught the rollout
    mid-flight, and reported "0 ready replicas" as though the fix had failed."""
    rolling = SimpleNamespace(
        metadata=SimpleNamespace(name="sample-api"),
        spec=SimpleNamespace(replicas=1),
        status=SimpleNamespace(ready_replicas=0),
    )
    ready = SimpleNamespace(
        metadata=SimpleNamespace(name="sample-api"),
        spec=SimpleNamespace(replicas=1),
        status=SimpleNamespace(ready_replicas=1),
    )
    core = _fake_core(endpoints=[], services=[], pods=[])
    apps = _fake_apps([])
    # Unready on the first poll, ready on the second — settle must keep waiting.
    apps.list_namespaced_deployment = AsyncMock(side_effect=[
        SimpleNamespace(items=[rolling]),
        SimpleNamespace(items=[ready]),
        SimpleNamespace(items=[ready]),
    ])
    with _patch_apis(core, apps):
        out = await settle_after_write("dokops-chaos", timeout=5.0, interval=0.01)

    assert apps.list_namespaced_deployment.await_count >= 2, "did not wait for the rollout"
    assert "The fix worked" in out


# ── the classifier covers StatefulSets, DaemonSets and bare pods, not just Deployments ──

@pytest.mark.asyncio
async def test_rollout_state_statefulset_still_rolling_is_progressing():
    """The v1 gap: a slow StatefulSet (ordered roll — DBs) used to read as healthy the
    instant no pod was crashing, because only Deployments were checked."""
    core = _fake_core(endpoints=[], services=[], pods=[])
    apps = _fake_apps([], statefulsets=[_sts("postgres", ready=1, replicas=3)])
    state, detail = await _rollout_state(core, apps, "db")
    assert state == "progressing"
    assert "statefulset/postgres: 1/3 ready" in "\n".join(detail)


@pytest.mark.asyncio
async def test_rollout_state_daemonset_not_fully_scheduled_is_progressing():
    core = _fake_core(endpoints=[], services=[], pods=[])
    apps = _fake_apps([], daemonsets=[_ds("fluentd", ready=1, desired=2)])
    state, detail = await _rollout_state(core, apps, "logging")
    assert state == "progressing"
    assert "daemonset/fluentd: 1/2 ready" in "\n".join(detail)


@pytest.mark.asyncio
async def test_rollout_state_bare_pod_not_ready_is_progressing():
    """A restarted pod with no controller (bare pod) has no Deployment to track it."""
    core = _fake_core(endpoints=[], services=[], pods=[_bare_pod("job-runner", "Running", ready=False)])
    apps = _fake_apps([])
    state, detail = await _rollout_state(core, apps, "batch")
    assert state == "progressing"
    assert "pod/job-runner: not Ready" in "\n".join(detail)


@pytest.mark.asyncio
async def test_rollout_state_all_workloads_ready_is_healthy():
    """STS + DS fully ready and a Ready bare pod → healthy (no premature-broken)."""
    core = _fake_core(endpoints=[], services=[], pods=[_bare_pod("oneoff", "Running", ready=True)])
    apps = _fake_apps(
        [],
        statefulsets=[_sts("postgres", ready=3, replicas=3)],
        daemonsets=[_ds("fluentd", ready=2, desired=2)],
    )
    state, detail = await _rollout_state(core, apps, "prod")
    assert state == "healthy"
    assert detail == []


@pytest.mark.asyncio
async def test_rollout_state_succeeded_bare_pod_does_not_hold_progressing():
    """A completed bare pod (Job-style Succeeded) is not a rollout in progress."""
    core = _fake_core(endpoints=[], services=[], pods=[_bare_pod("migrate", "Succeeded", ready=False)])
    apps = _fake_apps([])
    state, _ = await _rollout_state(core, apps, "prod")
    assert state == "healthy"


@pytest.mark.asyncio
async def test_settle_slow_pod_is_converging_not_broken():
    """The 1.5-min-startup case: a pod that is simply slow to become Ready — no crash,
    no bad image, no config error — must NOT be reported as a failed fix once the wait
    times out. It is still rolling out, and that is normal."""
    slow = SimpleNamespace(
        metadata=SimpleNamespace(name="sample-api"),
        spec=SimpleNamespace(replicas=1),
        status=SimpleNamespace(ready_replicas=0, conditions=[]),
    )
    starting = SimpleNamespace(
        name="app", restart_count=0,
        state=SimpleNamespace(waiting=SimpleNamespace(reason="ContainerCreating")),
    )
    core = _fake_core(endpoints=[], services=[],
                      pods=[_pod("sample-api-x", {"app": "sample-api"}, starting)])
    with _patch_apis(core, _fake_apps([slow])):
        out = await settle_after_write("dokops-chaos", timeout=0.02, interval=0.001)

    assert "STILL IN PROGRESS" in out
    assert "converging" in out
    assert "REMAIN" not in out
    assert "The fix worked" not in out


def test_no_sweep_returns_answer_unchanged():
    assert append_missing_findings("", "some answer") == "some answer"


def test_presweep_survives_the_reviewer_evidence_cap():
    """The final reviewer strips claims lacking tool evidence, so the sweep must
    reach it as evidence AND survive _select_evidence's cap of 10.

    Regression: the sweep contains no _ERR keyword ("0 endpoints" is not "error")
    and is the oldest observation, so on busy investigations it was silently
    dropped from the reviewer's evidence — and the reviewer then deleted the
    swept findings from the draft as unverified.
    """
    from app.services.ai_service import AIService

    sweep = _SWEEP.replace("FATAL: could not connect to postgres", "app cannot reach db")
    filler = [f"tool result {i}: everything looks healthy" for i in range(14)]
    kept = AIService._select_evidence([sweep] + filler, limit=10)

    assert any(o.startswith("PRE-FLIGHT SWEEP") for o in kept)


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


def _fake_apps(deployments, statefulsets=(), daemonsets=()):
    apps = SimpleNamespace()
    apps.list_namespaced_deployment = AsyncMock(return_value=SimpleNamespace(items=deployments))
    apps.list_namespaced_stateful_set = AsyncMock(return_value=SimpleNamespace(items=list(statefulsets)))
    apps.list_namespaced_daemon_set = AsyncMock(return_value=SimpleNamespace(items=list(daemonsets)))
    return apps


def _sts(name, ready, replicas):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(replicas=replicas),
        status=SimpleNamespace(ready_replicas=ready),
    )


def _ds(name, ready, desired):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        status=SimpleNamespace(number_ready=ready, desired_number_scheduled=desired),
    )


def _bare_pod(name, phase, ready):
    """A pod with no owner_references (not controlled by a Deployment/STS/DS)."""
    conds = [SimpleNamespace(type="Ready", status="True" if ready else "False")]
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels={}, owner_references=[]),
        status=SimpleNamespace(phase=phase, conditions=conds, container_statuses=[]),
    )


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
async def test_block_states_it_is_not_the_whole_investigation():
    """Regression: with the sweep present, the agent reported ONLY the swept
    findings and dropped four failing pods it had previously caught. The block
    must read as a head start, not as the scope of the investigation."""
    core = _fake_core(
        endpoints=[SimpleNamespace(metadata=SimpleNamespace(name="web"), subsets=None)],
        services=[_svc("web", {"app": "typo"})],
        pods=[_pod("web-1", {"app": "web"})],
    )
    with _patch_apis(core, _fake_apps([])):
        out = await build_presweep("dokops-chaos")

    assert "NOT the scope of your investigation" in out
    assert "investigate every failing pod yourself" in out


@pytest.mark.asyncio
async def test_reports_blocked_container_with_the_exact_missing_key():
    """Regression: asked to fix a missing ConfigMap, the agent created it keyed
    on the env var name (SMTP_HOST) instead of the referenced key (smtp_host).
    The fix applied cleanly, was reported as success, and the pod stayed broken.
    The kubelet event names the real key — surface it."""
    container = SimpleNamespace(
        name="app", restart_count=0,
        state=SimpleNamespace(waiting=SimpleNamespace(reason="CreateContainerConfigError")),
    )
    core = _fake_core(
        endpoints=[], services=[],
        pods=[_pod("notify-svc-78bfbf86d4-4lwcq", {"app": "notify-svc"}, container)],
    )
    core.list_namespaced_event = AsyncMock(return_value=SimpleNamespace(items=[
        SimpleNamespace(
            type="Warning", reason="Failed",
            involved_object=SimpleNamespace(name="notify-svc-78bfbf86d4-4lwcq"),
            message="Error: couldn't find key smtp_host in ConfigMap dokops-chaos/notify-config",
        )
    ]))
    with _patch_apis(core, _fake_apps([])):
        out = await build_presweep("dokops-chaos")

    assert "blocked before start" in out
    assert "couldn't find key smtp_host" in out


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
async def test_reports_replicaset_failure_when_no_pods_exist():
    """Scenario 02: a ResourceQuota of pods=0 means no pod ever exists, so the
    only evidence is a Warning event on the ReplicaSet. Without this the agent
    listed four speculative causes and asked the user which to check."""
    deployment = SimpleNamespace(
        metadata=SimpleNamespace(name="api-gateway"),
        spec=SimpleNamespace(replicas=2),
        status=SimpleNamespace(ready_replicas=0),
    )
    replica_set = SimpleNamespace(metadata=SimpleNamespace(
        name="api-gateway-755d4d56d5",
        owner_references=[SimpleNamespace(kind="Deployment", name="api-gateway")],
    ))
    event = SimpleNamespace(
        type="Warning", reason="FailedCreate",
        involved_object=SimpleNamespace(name="api-gateway-755d4d56d5"),
        message='pods "api-gateway-755d4d56d5-qj8pw" is forbidden: exceeded quota: no-pods-allowed',
    )
    core = _fake_core(endpoints=[], services=[], pods=[])
    core.list_namespaced_event = AsyncMock(return_value=SimpleNamespace(items=[event]))
    apps = _fake_apps([deployment])
    apps.list_namespaced_replica_set = AsyncMock(return_value=SimpleNamespace(items=[replica_set]))

    with _patch_apis(core, apps):
        out = await build_presweep("dokops-chaos")

    assert "failure is on the ReplicaSet" in out
    assert "exceeded quota: no-pods-allowed" in out


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


# ── scope-awareness: a pod-scoped question must not drag in the namespace ─────
# Live complaint: asked "why is pod X failing", the answer came back padded with
# other containers' raw crash logs, because coverage enforcement was always
# namespace-wide.

_MULTI_SWEEP = """PRE-FLIGHT SWEEP of namespace 'dokops-demo' — verified facts.
Deployments not at full readiness:
  - sample-catalog-api: 0/1 ready
  - order-worker: 0/2 ready
Logs from crashing containers:
  - sample-catalog-api-785d7689bc-b2xjj/api (CrashLoopBackOff):
      Connection refused (consul-server:8501)
  - order-worker-qzfjg/worker (CrashLoopBackOff):
      FATAL: could not connect to postgres
"""


def test_targeted_query_appends_only_the_named_resource():
    """Query names one swept resource -> other resources are not appended."""
    answer = "The deployment is not ready."  # covers nothing concretely
    out = append_missing_findings(
        _MULTI_SWEEP, answer, "why is sample-catalog-api failing?"
    )
    assert "sample-catalog-api" in out
    assert "consul-server:8501" in out
    # The unrelated workload and its logs must NOT be dragged in
    assert "order-worker" not in out
    assert "postgres" not in out


def test_targeted_query_matches_pod_name_despite_hash_suffix():
    """'sample-catalog-api' in the query must match pod ...-785d7689bc-b2xjj."""
    from app.services.presweep import _subject_matches_query

    assert _subject_matches_query(
        "sample-catalog-api-785d7689bc-b2xjj/api", "why is sample-catalog-api failing?"
    )
    assert not _subject_matches_query(
        "order-worker-qzfjg/worker", "why is sample-catalog-api failing?"
    )


def test_untargeted_query_keeps_full_namespace_coverage():
    """Query names no swept resource -> every finding still enforced (old behaviour)."""
    out = append_missing_findings(_MULTI_SWEEP, "Something is wrong.", "what is broken?")
    assert "sample-catalog-api" in out
    assert "order-worker" in out


def test_no_query_is_backward_compatible():
    """Omitting query keeps the pre-existing namespace-wide behaviour."""
    assert append_missing_findings(_MULTI_SWEEP, "Something is wrong.") == \
        append_missing_findings(_MULTI_SWEEP, "Something is wrong.", "")


def test_appended_log_bodies_are_fenced():
    """Raw log lines must render as a code block, not as prose in the UI."""
    out = append_missing_findings(_MULTI_SWEEP, "Nothing covered.", "")
    assert "```" in out
    fenced = out.split("```")
    assert any("consul-server:8501" in seg for seg in fenced)


async def test_build_presweep_scopes_header_to_named_resource():
    """A targeted query must not get the 'report every failing pod' instruction."""
    with patch("app.services.presweep._collect_sections", new=AsyncMock(return_value=[
        "Deployments not at full readiness:",
        "  - sample-catalog-api: 0/1 ready",
        "  - order-worker: 0/2 ready",
    ])), patch("app.services.presweep.k8s_service._get_api", return_value=object()):
        targeted = await build_presweep("dokops-demo", query="why is sample-catalog-api failing?")
        broad = await build_presweep("dokops-demo", query="what is broken?")

    assert "SPECIFIC resource" in targeted
    assert "report those findings alongside" not in targeted
    assert "report those findings alongside" in broad
