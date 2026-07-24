"""Deterministic pre-flight facts for namespace investigations.

Live testing showed the agent follows a discovery checklist inconsistently. Across
three identical runs against the same broken namespace it called get_endpoints in
one run, get_pod_logs in another, and neither in the third — so a Service with a
typo'd selector (zero endpoints, healthy pods) and a CrashLoopBackOff's actual error
line were each found once and missed twice.

None of those lookups need judgement: "which services have no endpoints" is a query,
not a decision. So compute them here and hand the agent the answers, instead of
asking it to remember to go looking. Judgement — explaining *why* the selector is
wrong — is left to the model, which is what it is actually good at.

Everything here is best-effort: any failure returns an empty block, and the agent
still has its full toolset to fall back on.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

from app.services.k8s_service import k8s_service

logger = logging.getLogger(__name__)

# Words that would otherwise be captured by the "<word> namespace" pattern.
_NS_STOPWORDS = frozenset({
    "the", "a", "an", "this", "that", "my", "our", "any", "each", "every",
    "all", "same", "which", "what", "some", "other", "another", "per", "its",
})

# Ordered: an explicit "namespace X" / "-n X" beats the trailing "X namespace" form.
_NS_PATTERNS = (
    re.compile(r"\bnamespaces?[:\s]+([a-z0-9][a-z0-9.\-]*)", re.I),
    re.compile(r"(?:^|\s)-n\s+([a-z0-9][a-z0-9.\-]*)"),
    re.compile(r"\b([a-z0-9][a-z0-9.\-]*)\s+namespaces?\b", re.I),
)


def extract_namespace(query: str) -> Optional[str]:
    """Best-effort namespace from a natural-language query, or None."""
    for pattern in _NS_PATTERNS:
        match = pattern.search(query or "")
        if not match:
            continue
        namespace = match.group(1).strip(".,;:!?'\"").lower()
        if namespace and namespace not in _NS_STOPWORDS:
            return namespace
    return None


# A sweep bullet: "  - web-frontend: 0 endpoints…", "  - order-worker-x/worker (…)".
# The subject is the resource name, up to the first ':', '/' or ' ('.
_BULLET = re.compile(r"^\s+- (\S+?)(?=[:/]|\s\()")


# Hard facts inside a bullet: anything carrying a digit (0 endpoints, 1/3 ready,
# api-gateway-755d4d56d5) or CamelCase (FailedCreate, CrashLoopBackOff). Naming the
# resource is not the same as reporting the finding.
_FACT_TOKEN = re.compile(r"\b(?:[\w.\-/]*\d[\w.\-/]*|[A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")


def _is_covered(bullet: str, subject: str, lowered_answer: str) -> bool:
    """True only if the answer names the resource AND reports something concrete
    about it. "api-gateway is not creating pods" does not cover a quota rejection."""
    if subject.lower() not in lowered_answer:
        return False
    detail = bullet[bullet.index(subject) + len(subject):]
    facts = {t.lower() for t in _FACT_TOKEN.findall(detail)}
    if not facts:
        return True  # nothing concrete to check — the name is all there was
    return any(fact in lowered_answer for fact in facts)


def _subject_matches_query(subject: str, lowered_query: str) -> bool:
    """True when the query names this swept resource. Pod names carry hash
    suffixes ("api-785d7689bc-b2xjj"), so match on progressively shorter
    '-'-boundary prefixes: "sample-catalog-api" in the query matches the
    full pod name."""
    name = subject.lower().split("/")[0].strip()
    parts = name.split("-")
    for end in range(len(parts), 0, -1):
        candidate = "-".join(parts[:end])
        if len(candidate) >= 4 and candidate in lowered_query:
            return True
    return False


def sweep_subjects(presweep: str) -> list[str]:
    """All bullet subjects (resource names) in a sweep block."""
    return [m.group(1) for line in presweep.splitlines() if (m := _BULLET.match(line))]


def append_missing_findings(presweep: str, answer: str, query: str = "") -> str:
    """Append any pre-flight finding the drafted answer failed to report.

    Discovery being deterministic is not enough on its own: with the sweep in
    context the model still reported only the Service in one run and only the
    pods in the next, dropping findings it was holding. Coverage is mechanical,
    so it is enforced here rather than asked for in the prompt.

    Scope-aware: when `query` names one of the swept resources ("why is
    sample-catalog-api failing?"), only bullets about matching resources are
    appended. Namespace-wide coverage enforcement on a pod-scoped question
    dumped other containers' crash logs into the answer — noise presented as
    findings. A query naming no swept resource keeps full-namespace coverage.
    """
    if not presweep or not answer:
        return answer

    lowered = answer.lower()
    lowered_query = (query or "").lower()
    lines = presweep.splitlines()
    targeted = bool(lowered_query) and any(
        _subject_matches_query(s, lowered_query) for s in sweep_subjects(presweep)
    )

    missing: list[str] = []
    for i, line in enumerate(lines):
        match = _BULLET.match(line)
        if not match or _is_covered(line, match.group(1), lowered):
            continue
        if targeted and not _subject_matches_query(match.group(1), lowered_query):
            continue  # user asked about a specific resource — skip the others
        missing.append(f"- {line.strip().lstrip('- ')}")
        # Carry the bullet's continuation lines (a crash log's body lives there;
        # appending the header alone produced "pod/app (CrashLoopBackOff):" with
        # no error message, which is worse than useless). Fence the body so raw
        # log lines render as a code block, not prose soup.
        indent = len(line) - len(line.lstrip())
        body: list[str] = []
        for follow in lines[i + 1:]:
            if not follow.strip() or _BULLET.match(follow):
                break
            if len(follow) - len(follow.lstrip()) <= indent:
                break
            body.append(follow.strip())
        if body:
            missing.append("  ```")
            missing.extend(f"  {b}" for b in body)
            missing.append("  ```")

    if not missing:
        return answer

    return (
        f"{answer.rstrip()}\n\n"
        "**Also found by the pre-flight sweep, not covered above:**\n"
        + "\n".join(missing)
    )


async def resolve_namespace(query: str, *, strict: bool = False) -> Optional[str]:
    """Namespace for a query: the regex forms first, then any real namespace name
    mentioned anywhere in it.

    The regex only fires when the word "namespace" is present, so "why is
    api-gateway not running in dokops-chaos?" resolved to None and the whole
    sweep silently did not run — the agent then answered from speculation.
    Matching against the cluster's actual namespaces removes the dependency on
    how the user phrased it.

    strict: when True, skip the extract_namespace() regex branch entirely and
    resolve ONLY against real namespace names from list_namespace(). The regex
    branch matches "namespace: X" wherever it appears, with no validation — fine
    for a user's own query, but callers may feed this text that is itself
    verbatim tool/evidence output (e.g. a describe result mentioning an
    unrelated "namespace: kube-system"), in which case the unvalidated regex
    would confidently return a namespace the user never asked about.
    """
    if not strict:
        if namespace := extract_namespace(query):
            return namespace

    core = k8s_service._get_api("CoreV1Api")
    if core is None:
        return None
    try:
        existing = [ns.metadata.name for ns in (await core.list_namespace()).items]
    except Exception as e:
        logger.debug("presweep: could not list namespaces: %s", e)
        return None

    # Strip trailing punctuation: the token class has to allow '.' and '-' for
    # names like "team-a.prod", which makes it swallow sentence-ending periods —
    # "dokops-chaos." then failed to match the namespace and the sweep silently
    # produced nothing. A query ending in '?' worked; the same one ending in '.'
    # did not.
    tokens = {
        t.strip(".-")
        for t in re.findall(r"[a-z0-9][a-z0-9.\-]*", (query or "").lower())
    }
    # Longest first so "dokops-chaos" wins over a hypothetical "dokops".
    for name in sorted(existing, key=len, reverse=True):
        if name.lower() in tokens:
            return name
    return None


async def _zero_endpoint_services(core, namespace: str) -> list[str]:
    """Services with no ready backend addresses, with their selector and the pod
    labels actually present — enough for the model to name a selector mismatch."""
    endpoints = await core.list_namespaced_endpoints(namespace)
    broken = [
        ep.metadata.name for ep in endpoints.items
        if not any(subset.addresses for subset in (ep.subsets or []))
    ]
    if not broken:
        return []

    services = await core.list_namespaced_service(namespace)
    by_name = {svc.metadata.name: svc for svc in services.items}
    pods = await core.list_namespaced_pod(namespace)
    pod_labels = sorted({
        ",".join(f"{k}={v}" for k, v in sorted((pod.metadata.labels or {}).items()))
        for pod in pods.items
    } - {""})

    lines = []
    for name in broken:
        svc = by_name.get(name)
        selector = (svc.spec.selector if svc and svc.spec else None) or {}
        if svc is not None and svc.spec.type == "ExternalName":
            continue  # no selector by design — not a fault
        if not selector:
            lines.append(f"  - {name}: 0 endpoints, no selector (headless or manually managed)")
            continue
        rendered = ",".join(f"{k}={v}" for k, v in sorted(selector.items()))
        lines.append(f"  - {name}: 0 endpoints. selector={{{rendered}}}")
    if lines and pod_labels:
        lines.append(f"  pod labels present in this namespace: {'; '.join(pod_labels)}")
    return lines


async def _unready_deployments(apps, namespace: str) -> list[str]:
    deployments = await apps.list_namespaced_deployment(namespace)
    lines = []
    for dep in deployments.items:
        desired = dep.spec.replicas or 0
        ready = dep.status.ready_replicas or 0
        if desired and ready < desired:
            lines.append(f"  - {dep.metadata.name}: {ready}/{desired} ready")
        elif desired == 0:
            lines.append(f"  - {dep.metadata.name}: scaled to 0 (may be intentional)")
    return lines


async def _replicaset_failures(core, apps, namespace: str) -> list[str]:
    """Why a Deployment produced no pods at all.

    When the ReplicaSet cannot create pods — quota rejection, an invalid template —
    the only evidence is a Warning event on the ReplicaSet. No pod exists to inspect,
    so a pod-centric investigation sees nothing and falls back to guessing.
    """
    deployments = await apps.list_namespaced_deployment(namespace)
    stalled = {
        dep.metadata.name for dep in deployments.items
        if (dep.spec.replicas or 0) > 0 and (dep.status.ready_replicas or 0) == 0
    }
    if not stalled:
        return []

    replica_sets = await apps.list_namespaced_replica_set(namespace)
    owned: dict[str, str] = {}
    for rs in replica_sets.items:
        for owner in (rs.metadata.owner_references or []):
            if owner.kind == "Deployment" and owner.name in stalled:
                owned[rs.metadata.name] = owner.name

    if not owned:
        return []

    events = await core.list_namespaced_event(namespace)
    lines, seen = [], set()
    for event in events.items:
        name = getattr(event.involved_object, "name", None)
        deployment = owned.get(name)
        if not deployment or deployment in seen or event.type != "Warning":
            continue
        seen.add(deployment)
        lines.append(f"  - {deployment} (ReplicaSet {name}) {event.reason}: {event.message}")
    return lines


_BLOCKED_REASONS = (
    "CreateContainerConfigError", "CreateContainerError",
    "InvalidImageName", "InvalidValue",
)


async def _blocked_containers(core, namespace: str) -> list[str]:
    """Containers that never started because of a config reference.

    These have no logs — the container was never created — so the crash-log sweep
    cannot see them, and the kubelet event carries the only precise detail. That
    detail matters: asked to fix a missing ConfigMap, the agent created it with the
    key named after the env var (SMTP_HOST) instead of the referenced key
    (smtp_host). The event says "couldn't find key smtp_host" outright.
    """
    pods = await core.list_namespaced_pod(namespace)
    blocked = {}
    for pod in pods.items:
        for status in (pod.status.container_statuses or []):
            waiting = status.state.waiting if status.state else None
            reason = getattr(waiting, "reason", None)
            if reason in _BLOCKED_REASONS:
                blocked[pod.metadata.name] = (status.name, reason)
    if not blocked:
        return []

    events = await core.list_namespaced_event(namespace)
    messages: dict[str, str] = {}
    for event in events.items:
        name = getattr(event.involved_object, "name", None)
        if name in blocked and event.type == "Warning" and event.message:
            messages[name] = event.message  # keep the most recent

    lines = []
    for pod_name, (container, reason) in blocked.items():
        detail = messages.get(pod_name, "")
        lines.append(f"  - {pod_name}/{container} {reason}: {detail}".rstrip(": "))
    return lines


async def _crash_logs(core, namespace: str, max_pods: int, tail_lines: int) -> list[str]:
    """Tail logs for containers that are crashing — the error line the agent
    otherwise reports as 'investigate the logs to determine the cause'."""
    pods = await core.list_namespaced_pod(namespace)
    lines: list[str] = []
    for pod in pods.items:
        if len(lines) >= max_pods * 2:
            break
        for status in (pod.status.container_statuses or []):
            waiting = status.state.waiting if status.state else None
            reason = getattr(waiting, "reason", None)
            crashed = reason in ("CrashLoopBackOff", "Error") or (status.restart_count or 0) > 0
            if not crashed:
                continue
            try:
                log = await core.read_namespaced_pod_log(
                    pod.metadata.name, namespace,
                    container=status.name, tail_lines=tail_lines, previous=bool(reason),
                )
            except Exception:
                try:  # a container that never started has no previous log
                    log = await core.read_namespaced_pod_log(
                        pod.metadata.name, namespace,
                        container=status.name, tail_lines=tail_lines,
                    )
                except Exception:
                    continue
            snippet = "\n      ".join((log or "").strip().splitlines()[-8:])
            if snippet:
                lines.append(f"  - {pod.metadata.name}/{status.name} ({reason or 'restarting'}):")
                lines.append(f"      {snippet}")
            break
    return lines


async def _collect_sections(core, apps, namespace: str, max_log_pods: int, tail_lines: int) -> list[str]:
    """Gather every problem section for `namespace`. Each check is independent —
    one failing must not suppress the others."""
    sections: list[str] = []
    try:
        if services := await _zero_endpoint_services(core, namespace):
            sections.append("Services with NO ready endpoints (broken even if their pods are Running):")
            sections.extend(services)
    except Exception as e:
        logger.debug("presweep: endpoint check failed for %s: %s", namespace, e)

    try:
        if deployments := await _unready_deployments(apps, namespace):
            sections.append("Deployments not at full readiness:")
            sections.extend(deployments)
    except Exception as e:
        logger.debug("presweep: deployment check failed for %s: %s", namespace, e)

    try:
        if stalled := await _replicaset_failures(core, apps, namespace):
            sections.append("Deployments that produced NO pods (failure is on the ReplicaSet):")
            sections.extend(stalled)
    except Exception as e:
        logger.debug("presweep: replicaset check failed for %s: %s", namespace, e)

    try:
        if blocked := await _blocked_containers(core, namespace):
            sections.append("Containers blocked before start (no logs exist — the event is the evidence):")
            sections.extend(blocked)
    except Exception as e:
        logger.debug("presweep: blocked-container check failed for %s: %s", namespace, e)

    try:
        if logs := await _crash_logs(core, namespace, max_log_pods, tail_lines):
            sections.append("Logs from crashing containers:")
            sections.extend(logs)
    except Exception as e:
        logger.debug("presweep: crash-log check failed for %s: %s", namespace, e)

    return sections


async def build_presweep(
    namespace: str, *, query: str = "", max_log_pods: int = 3, tail_lines: int = 30
) -> str:
    """Return a context block of facts for `namespace`, or '' if nothing to report.

    Never raises: a presweep failure must not break a chat turn.

    When `query` names one of the swept resources, the header scopes the answer
    to that resource: the old always-on "report every finding alongside these"
    instruction made a pod-scoped question ("why is X failing?") come back
    padded with every other broken workload in the namespace.
    """
    core = k8s_service._get_api("CoreV1Api")
    apps = k8s_service._get_api("AppsV1Api")
    if core is None or apps is None:
        return ""  # mock mode or no reachable cluster

    sections = await _collect_sections(core, apps, namespace, max_log_pods, tail_lines)
    if not sections:
        return ""
    body = "\n".join(sections)

    lowered_query = (query or "").lower()
    targeted = bool(lowered_query) and any(
        _subject_matches_query(m.group(1), lowered_query)
        for line in sections if (m := _BULLET.match(line))
    )
    if targeted:
        scope_line = (
            f"The user asked about a SPECIFIC resource — answer about that resource. "
            f"Other findings below are namespace context: mention them in at most one "
            f"short 'other issues in {namespace}' note, without their log excerpts."
        )
    else:
        scope_line = (
            f"You must STILL investigate every failing pod yourself and report those "
            f"findings alongside these — an answer that covers only what appears below "
            f"is incomplete."
        )
    return (
        f"PRE-FLIGHT SWEEP of namespace '{namespace}' — verified facts, already gathered "
        f"for you. Do not re-fetch these with tools.\n"
        f"This is a HEAD START, NOT the scope of your investigation. It covers only "
        f"service endpoints, deployment readiness, ReplicaSet failures and crash logs. "
        f"Quote these facts directly — they are the answer, not a hint. {scope_line}\n{body}\n"
    )


def namespace_of_write(tool_inputs: dict) -> Optional[str]:
    """Namespace a write touched: an explicit input, else the manifest's own field."""
    explicit = (tool_inputs or {}).get("namespace")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    manifest = (tool_inputs or {}).get("manifest_yaml") or ""
    match = re.search(r"^\s*namespace:\s*([a-z0-9][a-z0-9.\-]*)", manifest, re.M | re.I)
    return match.group(1) if match else None


# Waiting reasons that mean the rollout is genuinely broken, not just slow.
_FATAL_WAITING = (
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "InvalidImageName",
    "CreateContainerConfigError", "CreateContainerError",
)


async def _rollout_state(core, apps, namespace: str) -> tuple[str, list[str]]:
    """Classify a namespace mid-rollout as 'healthy', 'failed', or 'progressing'.

    Readiness is checked across Deployments, StatefulSets, DaemonSets AND bare Pods —
    not Deployments alone — so a slow StatefulSet/DaemonSet/pod reads as 'progressing',
    not a premature 'healthy'. 'progressing' is the case a fixed short wait got wrong: a
    workload that is simply slow to come up (image pull, init containers, ordered
    StatefulSet roll, readiness-probe delay) is NOT broken. Only a hard signal — a
    crashloop/bad-image/config-error waiting reason on any pod, an exceeded Deployment
    progress deadline, or a Failed bare pod — is 'failed'.

    Jobs (run-to-completion) and PVCs (bind-once) are deliberately excluded: their
    'done' semantics differ from readiness, and namespace-scoped inclusion would hold
    the watch open on unrelated CronJob activity or a pre-existing Pending PVC."""
    fatal: list[str] = []
    progressing: list[str] = []

    for d in (await apps.list_namespaced_deployment(namespace)).items:
        for cond in (getattr(d.status, "conditions", None) or []):
            if getattr(cond, "type", None) == "Progressing" and getattr(cond, "reason", None) == "ProgressDeadlineExceeded":
                fatal.append(f"  - deployment/{d.metadata.name}: rollout failed (ProgressDeadlineExceeded)")
        desired = d.spec.replicas or 0
        if desired > 0 and (d.status.ready_replicas or 0) < desired:
            progressing.append(f"  - deployment/{d.metadata.name}: {(d.status.ready_replicas or 0)}/{desired} ready")

    for s in (await apps.list_namespaced_stateful_set(namespace)).items:
        desired = s.spec.replicas or 0
        if desired > 0 and (s.status.ready_replicas or 0) < desired:
            progressing.append(f"  - statefulset/{s.metadata.name}: {(s.status.ready_replicas or 0)}/{desired} ready")

    for ds in (await apps.list_namespaced_daemon_set(namespace)).items:
        desired = ds.status.desired_number_scheduled or 0
        if desired > 0 and (ds.status.number_ready or 0) < desired:
            progressing.append(f"  - daemonset/{ds.metadata.name}: {(ds.status.number_ready or 0)}/{desired} ready")

    for pod in (await core.list_namespaced_pod(namespace)).items:
        for st in (pod.status.container_statuses or []):
            waiting = getattr(st.state, "waiting", None) if st.state else None
            if getattr(waiting, "reason", None) in _FATAL_WAITING:
                fatal.append(f"  - {pod.metadata.name}/{st.name}: {waiting.reason}")
        # A bare pod (no controller) has no Deployment/STS/DS to track its readiness.
        if not (getattr(pod.metadata, "owner_references", None) or []):
            phase = getattr(pod.status, "phase", None)
            if phase in (None, "Succeeded"):
                continue  # unknown (mock/no phase) or completed — not a rollout in progress
            if phase == "Failed":
                fatal.append(f"  - pod/{pod.metadata.name}: Failed")
            elif not any(
                getattr(c, "type", None) == "Ready" and getattr(c, "status", None) == "True"
                for c in (getattr(pod.status, "conditions", None) or [])
            ):
                progressing.append(f"  - pod/{pod.metadata.name}: not Ready ({phase})")

    if fatal:
        return "failed", fatal
    if progressing:
        return "progressing", progressing
    return "healthy", []


async def settle_after_write(
    namespace: str, *, timeout: float = 120.0, interval: float = 3.0
) -> str:
    """Wait for an applied change to actually take effect, then report the REAL end state.

    A write reports "applied successfully" the moment the API server accepts it, which
    is not the same as fixed. We poll until the rollout is definitively healthy or
    definitively failed — breaking early either way — and only wait out the full timeout
    for a rollout that is still legitimately coming up. Failure modes seen live: an image
    patch verified 5s after apply caught the rollout mid-flight and reported "0 ready
    replicas" as failed; a ConfigMap with the wrong key applied cleanly and left the pod
    broken; and a pod that simply took ~90s to become Ready was called broken because the
    wait was a fixed 25s. The three-way classification handles all three.
    """
    core = k8s_service._get_api("CoreV1Api")
    apps = k8s_service._get_api("AppsV1Api")
    if core is None or apps is None:
        return ""

    deadline = time.monotonic() + timeout
    state, detail = "progressing", []
    while True:
        await asyncio.sleep(interval)
        try:
            state, detail = await _rollout_state(core, apps, namespace)
        except Exception as e:
            logger.debug("settle: rollout-state check failed for %s: %s", namespace, e)
            return ""
        if state in ("healthy", "failed") or time.monotonic() >= deadline:
            break

    if state == "healthy":
        return (
            f"POST-CHANGE STATE of '{namespace}' (verified after waiting for the rollout "
            f"to finish): everything is now healthy — all workloads (deployments, "
            f"statefulsets, daemonsets, pods) at full readiness, no blocked or crashing "
            f"containers. The fix worked; say so plainly."
        )

    if state == "failed":
        try:
            remaining = await _collect_sections(core, apps, namespace, 3, 30)
        except Exception as e:
            logger.debug("settle: post-change sweep failed for %s: %s", namespace, e)
            remaining = detail
        return (
            f"POST-CHANGE STATE of '{namespace}' (verified after waiting for the change to "
            f"take effect): the write was accepted, but these problems REMAIN. Applying a "
            f"manifest is not the same as fixing the problem — do NOT report success. Say "
            f"what is still broken and why your change did not resolve it:\n"
            + "\n".join(remaining or detail)
        )

    # progressing — timed out while still legitimately coming up, no hard error
    return (
        f"POST-CHANGE STATE of '{namespace}': the change was applied and the rollout is "
        f"STILL IN PROGRESS after {int(timeout)}s with no error (no crash, bad image, or "
        f"config failure). Pods are still becoming Ready:\n" + "\n".join(detail) + "\n"
        f"This is normal for slow-starting pods. Tell the user the fix was applied and the "
        f"rollout is converging — it is NOT broken, but not yet confirmed healthy. Suggest "
        f"they re-check in a moment."
    )
