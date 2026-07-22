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

import logging
import re
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


def append_missing_findings(presweep: str, answer: str) -> str:
    """Append any pre-flight finding the drafted answer failed to report.

    Discovery being deterministic is not enough on its own: with the sweep in
    context the model still reported only the Service in one run and only the
    pods in the next, dropping findings it was holding. Coverage is mechanical,
    so it is enforced here rather than asked for in the prompt.
    """
    if not presweep or not answer:
        return answer

    lowered = answer.lower()
    missing = [
        line for line in presweep.splitlines()
        if (m := _BULLET.match(line)) and not _is_covered(line, m.group(1), lowered)
    ]
    if not missing:
        return answer

    return (
        f"{answer.rstrip()}\n\n"
        "**Also found by the pre-flight sweep, not covered above:**\n"
        + "\n".join(f"- {line.strip().lstrip('- ')}" for line in missing)
    )


async def resolve_namespace(query: str) -> Optional[str]:
    """Namespace for a query: the regex forms first, then any real namespace name
    mentioned anywhere in it.

    The regex only fires when the word "namespace" is present, so "why is
    api-gateway not running in dokops-chaos?" resolved to None and the whole
    sweep silently did not run — the agent then answered from speculation.
    Matching against the cluster's actual namespaces removes the dependency on
    how the user phrased it.
    """
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


async def build_presweep(
    namespace: str, *, max_log_pods: int = 3, tail_lines: int = 30
) -> str:
    """Return a context block of facts for `namespace`, or '' if nothing to report.

    Never raises: a presweep failure must not break a chat turn.
    """
    core = k8s_service._get_api("CoreV1Api")
    apps = k8s_service._get_api("AppsV1Api")
    if core is None or apps is None:
        return ""  # mock mode or no reachable cluster

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
        if logs := await _crash_logs(core, namespace, max_log_pods, tail_lines):
            sections.append("Logs from crashing containers:")
            sections.extend(logs)
    except Exception as e:
        logger.debug("presweep: crash-log check failed for %s: %s", namespace, e)

    if not sections:
        return ""
    body = "\n".join(sections)
    return (
        f"PRE-FLIGHT SWEEP of namespace '{namespace}' — verified facts, already gathered "
        f"for you. Do not re-fetch these with tools.\n"
        f"This is a HEAD START, NOT the scope of your investigation. It covers only "
        f"service endpoints, deployment readiness, ReplicaSet failures and crash logs. "
        f"Quote these facts directly — they are the answer, not a hint. You must STILL "
        f"investigate every failing pod yourself and report those findings alongside "
        f"these — an answer that covers only what appears below is incomplete.\n{body}\n"
    )
