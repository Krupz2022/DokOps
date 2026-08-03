"""Pure scoring: a Trace plus a Scenario's expectations in, a list of Checks out.

Deliberately free of I/O and of the agent loop so it can be unit tested against
synthetic traces.
"""
import json
import re
from dataclasses import dataclass
from typing import List

from evals.harness import Scenario, Trace

# Hyphenated lowercase tokens look like Kubernetes object names. Restricting the
# scan to these keeps it quiet: it will not fire on "error", "CrashLoopBackOff"
# or ordinary capitalised prose.
_NAME_RE = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b")

# ponytail: a small stopword list beats a POS tagger here. Extend it when a real
# run produces a false positive — do not pre-populate it by imagination.
_PROSE = {
    "well-known", "read-only", "up-to-date", "root-cause", "long-running",
    "out-of-memory", "step-by-step", "cluster-wide", "in-progress", "follow-up",
    "non-existent", "pre-existing", "so-called", "double-check", "high-level",
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def suspected_hallucinations(answer: str, scenario: Scenario, trace: Trace) -> List[str]:
    """Names in the answer that appear nowhere in the fixtures or the question.

    Not proof of hallucination — it is a shortlist for a human to read.
    """
    corpus = " ".join([
        json.dumps(scenario.cluster, default=str),
        scenario.presweep,
        scenario.topology,
        scenario.query,
        json.dumps(scenario.expect, default=str),
        json.dumps([c[0] for c in trace.calls]),
    ]).lower()
    seen: List[str] = []
    for name in _NAME_RE.findall(answer.lower()):
        if name in _PROSE or name in corpus or name in seen:
            continue
        seen.append(name)
    return seen


def score(scenario: Scenario, trace: Trace) -> List[Check]:
    checks: List[Check] = []
    called = [name for name, _ in trace.calls]
    answer = trace.answer or ""
    expect = scenario.expect

    checks.append(Check(
        "run_completed",
        trace.error is None,
        trace.error or "ok",
    ))

    if "must_call" in expect:
        missing = [t for t in expect["must_call"] if t not in called]
        checks.append(Check("must_call", not missing,
                            f"never called: {missing}" if missing else "ok"))

    if "must_not_call" in expect:
        forbidden = [t for t in expect["must_not_call"] if t in called]
        checks.append(Check("must_not_call", not forbidden,
                            f"called: {forbidden}" if forbidden else "ok"))

    if "must_cite" in expect:
        lowered = answer.lower()
        absent = [s for s in expect["must_cite"] if s.lower() not in lowered]
        checks.append(Check("must_cite", not absent,
                            f"not quoted in answer: {absent}" if absent else "ok"))

    if expect.get("must_not_end_on_question"):
        tail = answer.rstrip().rstrip("*_`)").rstrip()
        ends_on_question = tail.endswith("?")
        checks.append(Check("must_not_end_on_question", not ends_on_question,
                            f"answer ends: ...{tail[-80:]}" if ends_on_question else "ok"))

    suspects = suspected_hallucinations(answer, scenario, trace)
    checks.append(Check("no_unknown_names", not suspects,
                        f"names absent from fixtures: {suspects}" if suspects else "ok"))

    return checks
