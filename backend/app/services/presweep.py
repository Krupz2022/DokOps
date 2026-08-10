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
from dataclasses import dataclass
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
    about it. "api-gateway is not creating pods" does not cover a quota rejection.

    The name test matches on '-'-boundary prefixes rather than the exact string:
    a sweep bullet is keyed by the full pod name ("sample-catalog-api-785d…-56xrs")
    while a good answer refers to the workload ("sample-catalog-api"). Requiring
    an exact match made every such answer read as uncovered, so the footer
    re-appended the very crash log the answer had just quoted — the same log shown
    to the user twice."""
    if not _subject_matches_query(subject, lowered_answer):
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
    full pod name.

    Shortening stops at the two generated segments a pod name adds (ReplicaSet
    hash + pod suffix), and never below two segments. Shortening all the way
    down made siblings collide: asked for a fix for documents-api, the answer
    came back with documents-worker's crash log appended, because both reduce
    to "documents".
    """
    name = subject.lower().split("/")[0].strip()
    parts = name.split("-")
    floor = max(len(parts) - 2, min(2, len(parts)))
    for end in range(len(parts), floor - 1, -1):
        candidate = "-".join(parts[:end])
        if len(candidate) >= 4 and candidate in lowered_query:
            return True
    return False


def sweep_subjects(presweep: str) -> list[str]:
    """All bullet subjects (resource names) in a sweep block."""
    return [m.group(1) for line in presweep.splitlines() if (m := _BULLET.match(line))]


def subjects_of(findings: list[Finding]) -> list[str]:
    """Resource names the sweep reported, in order, deduplicated.

    The records-based counterpart to sweep_subjects(), which regexes these back
    out of prose the collectors had just finished formatting. Both exist on
    purpose: this one serves callers that hold the findings, sweep_subjects()
    serves append_missing_findings(), which receives prose by contract.
    """
    seen: dict[str, None] = {}
    for f in findings:
        # "labels" is section-level context, not a resource; "verdict" carries
        # the namespace itself as its `name` (so a header can say which rollout
        # this is), and the namespace is not a resource a query can target the
        # way a pod/service/deployment name is — letting it through here would
        # flip `targeted` on for any query that merely mentions the namespace.
        if f.kind not in ("labels", "verdict"):
            seen.setdefault(f.name, None)
    return list(seen)


def append_missing_findings(
    presweep: str, answer: str, query: str = "", recent_text: str = ""
) -> str:
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
    lines = presweep.splitlines()
    subjects = sweep_subjects(presweep)

    def _targets(text: str) -> bool:
        low = (text or "").lower()
        return bool(low) and any(_subject_matches_query(s, low) for s in subjects)

    # A follow-up ("whats the fix?", "and now?") names no resource, so scoping on
    # the current message alone fell back to namespace-wide coverage and dumped an
    # unrelated container's crash log into a conversation about one pod. Fall back
    # to the immediately preceding exchange, same as namespace resolution does.
    # ponytail: last exchange only, not the whole thread — a long conversation
    # mentions everything, which would make every turn look targeted. Widen only
    # if follow-ups are still coming back unscoped.
    lowered_query = (query or "").lower()
    targeted = _targets(lowered_query)
    if not targeted and _targets(recent_text):
        lowered_query = (recent_text or "").lower()
        targeted = True

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


# ── the swept facts, as records ──────────────────────────────────────────────
#
# Collectors used to build formatted bullet strings and drop the structured data
# at the f-string; sweep_subjects() then regexed the prose back into resource
# names. Now they return records and _render() is the single place the prose
# lives. One consumer per field is the test that this schema is right:
# sweep_subjects -> name, reason -> symptom lookup, detail -> service domains,
# formatter -> all.

_SECTION_ENDPOINTS = "endpoints"
_SECTION_DEPLOYMENTS = "deployments"
_SECTION_REPLICASETS = "replicasets"
_SECTION_BLOCKED = "blocked"
_SECTION_CRASHLOGS = "crashlogs"
_SECTION_ROLLOUT = "rollout"


@dataclass(frozen=True)
class Finding:
    """One structured presweep fact.

    `container` is separate from `name` because _crash_logs renders
    "pod/container" while subject extraction wants the pod alone.

    `qualifier` is render-only: header text that belongs to no other field and
    that _render cannot derive from the rest. Two collectors need it — the owning
    ReplicaSet's name for a replicaset finding, and the full crash tag
    ("CrashLoopBackOff, last exit OOMKilled (137)") for a crash-log finding,
    whose `reason` is narrowed to the one symptom word the symptom lookup keys
    on. It is last and defaulted so the six fields above stay the schema.

    `reason` and `detail` are Optional because the Kubernetes API says they are:
    a replicaset finding takes both straight off a Warning Event, whose `reason`
    and `message` are both optional fields, and a crash-log finding has no
    waiting reason when the container is merely restarting. Consumers must treat
    them as `str | None` — `f.detail or ""`, not `keyword in f.detail`.
    """
    section: str
    kind: str
    name: str
    container: str | None
    reason: str | None
    detail: str | None
    qualifier: str | None = None


async def _zero_endpoint_services(core, namespace: str) -> list[Finding]:
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

    out: list[Finding] = []
    for name in broken:
        svc = by_name.get(name)
        selector = (svc.spec.selector if svc and svc.spec else None) or {}
        if svc is not None and svc.spec.type == "ExternalName":
            continue  # no selector by design — not a fault
        if not selector:
            out.append(Finding(_SECTION_ENDPOINTS, "service", name, None, "ZeroEndpoints",
                               "0 endpoints, no selector (headless or manually managed)"))
            continue
        rendered = ",".join(f"{k}={v}" for k, v in sorted(selector.items()))
        out.append(Finding(_SECTION_ENDPOINTS, "service", name, None, "ZeroEndpoints",
                           f"0 endpoints. selector={{{rendered}}}"))
    # The labels belong to the section, not to any one Service: they are what the
    # broken selectors have to be compared against.
    if out and pod_labels:
        out.append(Finding(_SECTION_ENDPOINTS, "labels", "", None, None,
                           "; ".join(pod_labels)))
    return out


async def _unready_deployments(apps, namespace: str) -> list[Finding]:
    deployments = await apps.list_namespaced_deployment(namespace)
    out: list[Finding] = []
    for dep in deployments.items:
        desired = dep.spec.replicas or 0
        ready = dep.status.ready_replicas or 0
        if desired and ready < desired:
            out.append(Finding(_SECTION_DEPLOYMENTS, "deployment", dep.metadata.name,
                               None, "NotReady", f"{ready}/{desired} ready"))
        elif desired == 0:
            out.append(Finding(_SECTION_DEPLOYMENTS, "deployment", dep.metadata.name,
                               None, "ScaledToZero", "scaled to 0 (may be intentional)"))
    return out


async def _replicaset_failures(core, apps, namespace: str) -> list[Finding]:
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
    out: list[Finding] = []
    seen: set[str] = set()
    for event in events.items:
        name = getattr(event.involved_object, "name", None)
        deployment = owned.get(name)
        if not deployment or deployment in seen or event.type != "Warning":
            continue
        seen.add(deployment)
        # The finding is about the Deployment — that is the name the user asked
        # about and the one subject extraction wants. The ReplicaSet is where the
        # evidence happens to live, so it rides along as the header's qualifier.
        out.append(Finding(_SECTION_REPLICASETS, "deployment", deployment, None,
                           event.reason, event.message, qualifier=name))
    return out


_BLOCKED_REASONS = (
    "CreateContainerConfigError", "CreateContainerError",
    "InvalidImageName", "InvalidValue",
    # An image-pull failure IS a container that never started: no logs exist and
    # the kubelet event carries the only precise detail — exactly what this
    # collector is documented to handle. Absent before, so tier 1 could never
    # fire on the single most common workload failure.
    "ImagePullBackOff", "ErrImagePull",
)

# Evidence verdict -> the tools that answer it. Tier 1 emits TOOL NAMES, not
# domains, because its targets (patch_deployment_resources, get_hpa,
# get_limit_range ...) sit in the 68 registry tools that carry no domain prefix
# and are therefore unreachable by _SERVICE_TOOL_MAP at any tier.
#
# † = also in _CORE_K8S. Kept deliberately: the union dedupes, so duplicates
# cost nothing, and a row that omitted them would lie about the intended
# response. This table is an audit surface for remediation coverage.
#
# Every row pairs write tools with diagnostics (rollback WITH history, patch
# WITH metrics/limits) so remediation is never the only thing on offer. A row
# holding a write tool ALONE is the most action-provoking shape — do not add one.
SYMPTOM_TOOLS: dict[str, tuple[str, ...]] = {
    "ImagePullBackOff":            ("fix_image_pull", "get_secret_exists", "list_secrets"),
    "ErrImagePull":                ("fix_image_pull", "get_secret_exists", "list_secrets"),
    "InvalidImageName":            ("fix_image_pull", "get_secret_exists", "list_secrets"),
    "CreateContainerConfigError":  ("get_workload_config", "get_configmap",
                                    "get_secret_keys", "update_configmap"),
    "CreateContainerError":        ("get_workload_config", "get_configmap",
                                    "get_secret_keys", "update_configmap"),
    "InvalidValue":                ("get_workload_config", "get_limit_range"),
    "OOMKilled":                   ("patch_deployment_resources", "get_pod_metrics",
                                    "get_limit_range"),
    "Error":                       ("get_deployment_rollout_history", "rollback_deployment"),
    "NotReady":                    ("get_deployment_status", "get_hpa", "get_pod_events"),
    "ZeroEndpoints":               ("get_endpoints", "get_service", "get_network_policies"),
    "FailedCreate":                ("get_resource_quota", "get_limit_range", "get_replicasets"),
    "failed":                      ("get_deployment_rollout_history", "rollback_deployment",
                                    "get_replicasets"),
}

# Reasons that can appear in evidence but deliberately map to no tools.
INTENTIONALLY_UNMAPPED: frozenset[str] = frozenset({
    "ScaledToZero",   # "may be intentional" — not a fault
    "progressing",    # a slow rollout is not broken
})


def evidence_reasons() -> frozenset[str]:
    """Every reason that can reach a Finding.reason. Assertion 2 keys off this;
    it must widen in lockstep with any collector that emits a new reason."""
    return frozenset(_BLOCKED_REASONS) | frozenset({
        "OOMKilled", "Error", "NotReady", "ScaledToZero",
        "ZeroEndpoints", "FailedCreate", "failed", "progressing",
    })


def tools_for_findings(findings: list[Finding]) -> set[str]:
    """Tier 1: structured verdicts -> tool names."""
    out: set[str] = set()
    for f in findings:
        out.update(SYMPTOM_TOOLS.get(f.reason or "", ()))
    return out


async def _blocked_containers(core, namespace: str) -> list[Finding]:
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

    return [
        Finding(_SECTION_BLOCKED, "container", pod_name, container, reason,
                messages.get(pod_name, ""))
        for pod_name, (container, reason) in blocked.items()
    ]


async def _crash_logs(core, namespace: str, max_pods: int, tail_lines: int) -> list[Finding]:
    """Tail logs for containers that are crashing — the error line the agent
    otherwise reports as 'investigate the logs to determine the cause'."""
    pods = await core.list_namespaced_pod(namespace)
    out: list[Finding] = []
    for pod in pods.items:
        # The budget is in rendered PROSE lines, not findings: a crash log is a
        # bullet plus its excerpt, and an OOM with an empty tail is a bullet
        # alone. Measured through the formatter so the two cannot drift.
        if len(_render(out)) >= max_pods * 2:
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
            # ponytail: stack frames are padding — a .NET/Java trace states its cause
            # in the header and spends 15 lines unwinding. Tailing raw lines fed the
            # agent frames only, and "Connection refused (consul-server:8501)" became
            # "fails during host build". Fall back to raw lines if filtering empties it.
            body = [
                line for line in (log or "").strip().splitlines()
                if not line.strip().startswith(("at ", "--- End of"))
            ]
            excerpt = "\n".join((body or (log or "").strip().splitlines())[-8:])
            # ponytail: the kill reason costs one getattr and is the whole diagnosis.
            # An OOM kill writes NOTHING to the log — the kernel SIGKILLs the process
            # mid-run, so the tail just stops on an ordinary startup line. Without the
            # reason the agent reads that clean tail as "no cause in the logs" and
            # stops, which it did on a container 591 restarts deep whose memory limit
            # had been dropped to 50Mi. state.waiting only ever says CrashLoopBackOff.
            last_term = getattr(getattr(status, "last_state", None), "terminated", None)
            kill = getattr(last_term, "reason", None)
            code = getattr(last_term, "exit_code", None)
            tag = (reason or "restarting") + (f", last exit {kill}" if kill else "")
            if code is not None and kill:
                tag += f" ({code})"
            # `reason` is narrowed to the one symptom word downstream keys on; the
            # full tag rides along as the header qualifier.
            if kill == "OOMKilled":
                out.append(Finding(_SECTION_CRASHLOGS, "container", pod.metadata.name,
                                   status.name, "OOMKilled", excerpt, qualifier=tag))
            elif excerpt:
                out.append(Finding(_SECTION_CRASHLOGS, "container", pod.metadata.name,
                                   status.name, reason, excerpt, qualifier=tag))
            break
    return out


async def _rollout_verdict(core, apps, namespace: str) -> list[Finding]:
    """The namespace's rollout classification, as one Finding — not one per
    fatal/progressing line.

    _rollout_state's bullet lines restate facts a full collector above already
    rendered (the crash reason, the deployment's ready count, ...): the verdict
    word is the only fact in them that isn't already a Finding elsewhere. So
    only the word becomes a Finding here; the lines themselves are read only to
    decide whether to emit at all, then discarded. Making this a Finding (not
    prose appended after _render_sections, as it was before) is what makes the
    verdict visible to `reason`-keyed lookups over `findings`, the same as any
    other collector's result.

    The `verdict != "healthy" and rollout_lines` guard is kept byte-for-byte
    from the pre-Finding version: it exists to skip a non-healthy verdict that
    carries no lines, not to gate on the lines' content once non-empty.
    """
    verdict, rollout_lines = await _rollout_state(core, apps, namespace)
    if verdict != "healthy" and rollout_lines:
        return [Finding(_SECTION_ROLLOUT, "verdict", namespace, None, verdict, "")]
    return []


def _render(findings: list[Finding]) -> list[str]:
    """Records -> the exact bullet prose that shipped before the refactor.

    Every string here is byte-identical to its pre-refactor f-string, and the
    goldens in tests/fixtures/presweep_golden assert that. Changing one is a
    coverage change, not a refactor.

    This is the only place presweep's prose contract lives, so read it to learn
    what the sweep looks like. Section HEADERS are not here — they belong to
    _render_sections, which knows which sections came back non-empty.

    A finding whose section has no branch below is dropped rather than raising:
    presweep is best-effort and build_presweep must never break a chat turn. The
    section constants are a closed set, and _render_sections only ever renders
    sections it has a header for, so an unrenderable section cannot reach here
    without someone adding a constant and forgetting both places at once.
    """
    lines: list[str] = []
    for f in findings:
        if f.section == _SECTION_ENDPOINTS:
            if f.kind == "labels":
                # Section-level, so no "- ": it is context for the bullets above.
                lines.append(f"  pod labels present in this namespace: {f.detail}")
            else:
                lines.append(f"  - {f.name}: {f.detail}")
        elif f.section == _SECTION_DEPLOYMENTS:
            lines.append(f"  - {f.name}: {f.detail}")
        elif f.section == _SECTION_REPLICASETS:
            lines.append(f"  - {f.name} (ReplicaSet {f.qualifier}) {f.reason}: {f.detail}")
        elif f.section == _SECTION_BLOCKED:
            # NOTE rstrip takes a character SET, not a suffix: this drops the
            # dangling ": " when no event message was found, but also eats any
            # trailing ':' or space the message itself ended with. Pre-refactor
            # behaviour, preserved deliberately — byte-identity governs.
            lines.append(f"  - {f.name}/{f.container} {f.reason}: {f.detail}".rstrip(": "))
        elif f.section == _SECTION_CRASHLOGS:
            if f.reason == "OOMKilled":
                lines.append(
                    f"  - {f.name}/{f.container} ({f.qualifier}): killed at its memory "
                    "limit. Any log below is cut short by the kill, NOT an application "
                    "error — check the container's memory limit against actual usage."
                )
                if f.detail:
                    lines.append(_indent_log(f.detail))
            else:
                lines.append(f"  - {f.name}/{f.container} ({f.qualifier}):")
                lines.append(_indent_log(f.detail))
        elif f.section == _SECTION_ROLLOUT:
            # No "  - " bullet: this isn't a resource among peers, it's the
            # namespace-wide verdict, rendered as its own trailing line.
            lines.append(f"Rollout state: {f.reason}")
    return lines


def _indent_log(detail: str) -> str:
    """A log excerpt as one continuation block under its bullet.

    Every line is indented, not just the first: append_missing_findings() reads
    a bullet's body back by indentation, and an unindented line would terminate
    it early."""
    return "      " + detail.replace("\n", "\n      ")


async def _collect_findings(
    core, apps, namespace: str, max_log_pods: int, tail_lines: int
) -> list[Finding]:
    """Every swept fact about `namespace`, in section order.

    Each check is independent — one failing must not suppress the others, so each
    gets its own handler and the sweep degrades to the sections that did work."""
    # Called, not pre-awaited: a cancelled chat turn must not leave four
    # never-awaited coroutines behind warning into the logs.
    checks = (
        ("endpoint", lambda: _zero_endpoint_services(core, namespace)),
        ("deployment", lambda: _unready_deployments(apps, namespace)),
        ("replicaset", lambda: _replicaset_failures(core, apps, namespace)),
        ("blocked-container", lambda: _blocked_containers(core, namespace)),
        ("crash-log", lambda: _crash_logs(core, namespace, max_log_pods, tail_lines)),
        ("rollout", lambda: _rollout_verdict(core, apps, namespace)),
    )
    findings: list[Finding] = []
    for label, check in checks:
        try:
            findings.extend(await check())
        except Exception as e:
            logger.debug("presweep: %s check failed for %s: %s", label, namespace, e)
    return findings


# Rendered in this order, and only for sections that came back with findings.
# _SECTION_ROLLOUT is last on purpose: it's the namespace-wide verdict, not a
# per-resource section, so it trails everything else. Its header is None —
# "Rollout state: <verdict>" is dynamic and rendered as the finding's own line
# in _render, so there is no static header string to put here; _render_sections
# below treats a None header as "no header line, just the rendered lines."
_SECTION_HEADERS = (
    (_SECTION_ENDPOINTS,
     "Services with NO ready endpoints (broken even if their pods are Running):"),
    (_SECTION_DEPLOYMENTS,
     "Deployments not at full readiness:"),
    (_SECTION_REPLICASETS,
     "Deployments that produced NO pods (failure is on the ReplicaSet):"),
    (_SECTION_BLOCKED,
     "Containers blocked before start (no logs exist — the event is the evidence):"),
    (_SECTION_CRASHLOGS,
     "Logs from crashing containers:"),
    (_SECTION_ROLLOUT, None),
)


def _render_sections(findings: list[Finding]) -> list[str]:
    """Every problem section as prose: a header per non-empty section, followed
    by that section's rendered bullets. Split out of _collect_sections so a
    caller that already holds `findings` (build_presweep, for subjects_of) does
    not need a second cluster read to get the rendered prose too."""
    sections: list[str] = []
    for section, header in _SECTION_HEADERS:
        # Rendering used to happen inside the collectors, so a formatting fault was
        # caught by that collector's handler and cost exactly one section. Keep that
        # property: build_presweep documents "never raises" and has no handler of
        # its own, and resting that on _render happening to be raise-proof is an
        # unenforced invariant in front of a live chat turn. Collection is already
        # guarded in _collect_findings, so this can only ever see a formatter fault
        # — it cannot mask a collector bug.
        try:
            lines = _render([f for f in findings if f.section == section])
        except Exception as e:
            logger.debug("presweep: rendering %s failed: %s", section, e)
            continue
        if lines:
            if header is not None:
                sections.append(header)
            sections.extend(lines)
    return sections


async def _collect_sections(core, apps, namespace: str, max_log_pods: int, tail_lines: int) -> list[str]:
    """Every problem section for `namespace` as prose: a header per non-empty
    section, followed by that section's rendered bullets.

    Thin wrapper over _collect_findings + _render_sections: settle_after_write
    only ever needs the prose, never the records, so it keeps calling this."""
    findings = await _collect_findings(core, apps, namespace, max_log_pods, tail_lines)
    return _render_sections(findings)


async def build_presweep(
    namespace: str, *, query: str = "", max_log_pods: int = 3, tail_lines: int = 80
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

    findings = await _collect_findings(core, apps, namespace, max_log_pods, tail_lines)
    sections = _render_sections(findings)
    if not sections:
        return ""
    body = "\n".join(sections)

    lowered_query = (query or "").lower()
    targeted = bool(lowered_query) and any(
        _subject_matches_query(s, lowered_query) for s in subjects_of(findings)
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


# ── where a workload's config actually lives ─────────────────────────────────
#
# Asked to change a setting, the agent went straight for patch_deployment_env
# because nothing ever told it the value was owned elsewhere: ConfigMaps are in
# the topology graph but get_cluster_overview never renders them, and the two
# candidate tools ("use when the user asks to change a config value" vs "use to
# fix misconfigured credentials, service URLs, or feature flags") describe the
# same intent with no ordering between them. Resolving the owner is a lookup,
# not a judgement, so it is done here and handed over — same bargain as the
# sweep above.

# Var names whose literal value must not be echoed back. Over-redaction is the
# safe failure (CLAUDE.md §3a): a redacted URL is an inconvenience, a printed
# password is an incident.
_SECRETISH = re.compile(r"pass|secret|token|credential|private|api[_-]?key|(?:^|_)key(?:$|_)", re.I)

# A container with 200 env vars would crowd out the rest of the context.
_MAX_ENV_SHOWN = 40


def _format_env(entry: dict) -> str:
    """One 'NAME <- owner' line. The arrow means 'owned elsewhere', '=' means
    'lives in the deployment' — the whole distinction the agent was missing."""
    name = entry.get("name", "?")
    source = entry.get("source")
    if source == "configMapKeyRef":
        return f"{name} <- configmap/{entry.get('configmap_name')} key '{entry.get('key')}'"
    if source == "secretKeyRef":
        return f"{name} <- secret/{entry.get('secret_name')} key '{entry.get('key')}'"
    if source == "fieldRef":
        return f"{name} <- fieldRef {entry.get('field_path')} (Kubernetes sets it per pod)"
    if source == "resourceFieldRef":
        return f"{name} <- resourceFieldRef {entry.get('resource')} (Kubernetes sets it)"
    if source == "literal":
        shown = "<redacted>" if _SECRETISH.search(name) else repr(entry.get("value"))
        return f"{name} = {shown} (literal in the deployment — patch it HERE)"
    return f"{name} <- {source or 'unknown source'}"


async def _workload_config_lines(name: str, namespace: str, core) -> list[str]:
    """Render one deployment's config ownership, or [] if it cannot be read."""
    from app.tools.k8s_tools import get_workload_config  # lazy: keeps presweep standalone

    result = await get_workload_config(name, namespace)
    if not result.get("success"):
        return []
    data = result["data"]

    lines = [f"CONFIG SOURCES for deployment/{name} (resolved — do not re-fetch):"]
    for container in data.get("containers", []):
        lines.append(f"  container {container.get('container_name')}:")
        # Printed before the env block on purpose: for an OOM this is the answer, and
        # buried under 40 env vars it reads as trivia. "no memory limit set" is itself
        # a finding — an unbounded container is killed by the node, not by its limit.
        limits, requests = container.get("limits") or {}, container.get("requests") or {}
        if limits or requests:
            lines.append(
                f"    resources: limits {limits or 'none set'} | requests {requests or 'none set'}"
                " (patch with patch_deployment_resources)"
            )
        env_vars = container.get("env_vars", [])
        for entry in env_vars[:_MAX_ENV_SHOWN]:
            lines.append(f"    {_format_env(entry)}")
        if len(env_vars) > _MAX_ENV_SHOWN:
            lines.append(f"    … and {len(env_vars) - _MAX_ENV_SHOWN} more (use get_workload_config)")
        for ref in container.get("env_from_configmaps", []):
            prefix = f", prefixed '{ref['prefix']}'" if ref.get("prefix") else ""
            lines.append(f"    envFrom: configmap/{ref['configmap_name']} — ALL its keys "
                         f"become env vars{prefix}")
        for ref in container.get("env_from_secrets", []):
            prefix = f", prefixed '{ref['prefix']}'" if ref.get("prefix") else ""
            lines.append(f"    envFrom: secret/{ref['secret_name']} — ALL its keys become "
                         f"env vars{prefix}")

    # Mount paths live on the container, the ConfigMap name on the volume — join
    # them so "the setting is in a file" is answerable without another round trip.
    mount_paths = {
        mount["name"]: mount["mount_path"]
        for container in data.get("containers", [])
        for mount in container.get("volume_mounts", [])
    }
    mounted: list[str] = []
    for volume in data.get("volume_configmaps", []):
        where = mount_paths.get(volume["volume_name"], "(not mounted)")
        keys = ""
        if core is not None:
            try:
                config_map = await core.read_namespaced_config_map(
                    volume["configmap_name"], namespace)
                # Key names only. ConfigMap VALUES are never pulled into context here.
                if names := sorted((config_map.data or {}).keys()):
                    keys = f" (keys: {', '.join(names)})"
            except Exception as e:
                logger.debug("config sources: cannot read cm %s: %s",
                             volume["configmap_name"], e)
        mounted.append(f"    configmap/{volume['configmap_name']} at {where}{keys}")
    for volume in data.get("volume_secrets", []):
        where = mount_paths.get(volume["volume_name"], "(not mounted)")
        mounted.append(f"    secret/{volume['secret_name']} at {where}")
    if mounted:
        lines.append("  mounted as files:")
        lines.extend(mounted)

    return lines


async def build_config_sources(
    namespace: str, query: str, *, max_workloads: int = 3
) -> str:
    """Where each of a workload's config values actually lives, or '' if the
    query names no workload in `namespace`.

    Deliberately NOT gated on a config-change intent classifier, for the reason
    already written at the presweep call site: the classifier is a coin flip. One
    extra deployment read on any query naming a workload is cheaper than a
    heuristic that silently misses.

    ponytail: Deployments only — get_workload_config reads
    read_namespaced_deployment. Add StatefulSet/DaemonSet there if a config
    question about one ever comes up; do not build a workload abstraction first.
    """
    apps = k8s_service._get_api("AppsV1Api")
    if apps is None or not (query or "").strip():
        return ""
    core = k8s_service._get_api("CoreV1Api")

    try:
        deployments = await apps.list_namespaced_deployment(namespace)
    except Exception as e:
        logger.debug("config sources: cannot list deployments in %s: %s", namespace, e)
        return ""

    lowered = query.lower()
    matched = [
        d.metadata.name for d in deployments.items
        if _subject_matches_query(d.metadata.name, lowered)
    ][:max_workloads]
    if not matched:
        return ""

    blocks: list[str] = []
    for name in matched:
        try:
            if lines := await _workload_config_lines(name, namespace, core):
                blocks.append("\n".join(lines))
        except Exception as e:
            logger.debug("config sources: failed for %s/%s: %s", namespace, name, e)

    if not blocks:
        return ""
    return (
        "\n\n".join(blocks)
        + "\nTo CHANGE a value, write to the object that OWNS it — the ConfigMap or "
        "Secret named above, not the deployment. Patching the deployment detaches it "
        "from its source: the ConfigMap keeps the old value for every other consumer, "
        "and the next helm/GitOps sync reverts you.\n"
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
