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
        scenario.namespace or "",
        json.dumps(scenario.expect, default=str),
        json.dumps([c[0] for c in trace.calls]),
    ]).lower()
    # Tokenize the corpus with the same regex used on the answer, then test set
    # membership rather than substring containment. A raw substring test lets a
    # hallucinated "api-gateway" hide inside a real "api-gateway-prod-7d4f" —
    # exactly the case this scan exists to catch.
    #
    # Corpus-only: replace "_" with a space before tokenizing. \b does not fire
    # between two \w characters, and "_" is \w, so "restart_count_api-gateway"
    # would otherwise never yield "api-gateway" as its own token, flagging a
    # correct answer as a hallucination. The answer side is deliberately left
    # untouched — a hallucinated "foo_bar-baz" should stay one token there.
    corpus_names = set(_NAME_RE.findall(corpus.replace("_", " ")))
    seen: List[str] = []
    for name in _NAME_RE.findall(answer.lower()):
        if name in _PROSE or name in corpus_names or name in seen:
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

    _EMPTY_LIST_DETAIL = "empty list: this assertion can never fire; remove the key or populate it"

    if "must_call" in expect:
        must_call = expect["must_call"]
        if not must_call:
            checks.append(Check("must_call", False, _EMPTY_LIST_DETAIL))
        else:
            missing = [t for t in must_call if t not in called]
            checks.append(Check("must_call", not missing,
                                f"never called: {missing}" if missing else "ok"))

    if "must_not_call" in expect:
        must_not_call = expect["must_not_call"]
        if not must_not_call:
            checks.append(Check("must_not_call", False, _EMPTY_LIST_DETAIL))
        else:
            forbidden = [t for t in must_not_call if t in called]
            checks.append(Check("must_not_call", not forbidden,
                                f"called: {forbidden}" if forbidden else "ok"))

    if "must_cite" in expect:
        must_cite = expect["must_cite"]
        if not must_cite:
            checks.append(Check("must_cite", False, _EMPTY_LIST_DETAIL))
        else:
            lowered = answer.lower()
            absent = [s for s in must_cite if s.lower() not in lowered]
            checks.append(Check("must_cite", not absent,
                                f"not quoted in answer: {absent}" if absent else "ok"))

    if expect.get("must_not_end_on_question"):
        tail = answer.rstrip().rstrip("*_`)'\"").rstrip()
        ends_on_question = tail.endswith("?")
        checks.append(Check("must_not_end_on_question", not ends_on_question,
                            f"answer ends: ...{tail[-80:]}" if ends_on_question else "ok"))

    suspects = suspected_hallucinations(answer, scenario, trace)
    checks.append(Check("no_unknown_names", not suspects,
                        f"names absent from fixtures: {suspects}" if suspects else "ok"))

    return checks
