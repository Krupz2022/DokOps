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
    append_missing_findings, build_presweep, extract_namespace, resolve_namespace,
)


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
