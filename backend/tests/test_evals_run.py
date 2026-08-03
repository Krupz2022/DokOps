"""Deterministic tests for evals/run.py's advisory-check handling.

Regression: score() computed no_unknown_names (suspected_hallucinations) and
run.py treated it exactly like every other check — `all(c.passed for c in
checks)` — even though the function's own docstring says it is "a shortlist
for a human to read... not proof of hallucination". In the 2026-08-03
baseline it was the ONLY failing check on two scenarios (crashloop-needs-log-
line, redis-uses-redis-tools) that passed every real assertion, flagging
ordinary hyphenated English (config-reference, image-pull, ...) as if it were
a defect. These tests exercise `_run_one`'s pass/fail computation directly,
stubbing `run_scenario` so no LLM call happens.
"""
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from evals.harness import Scenario, Trace
from evals.run import _run_one

pytestmark = pytest.mark.asyncio


def _scenario(**expect):
    return Scenario(
        name="t", query="why is billing-worker failing", history=[], namespace="payments",
        presweep="", topology="",
        cluster={}, expect=expect, path=pathlib.Path("t.yaml"),
    )


async def test_advisory_only_failure_does_not_fail_the_attempt():
    """A scenario that passes every real assertion but trips the advisory
    hallucination scan must still be recorded as passed."""
    # "notify-worker" appears nowhere in the query/cluster/presweep/topology/
    # expect, so no_unknown_names will flag it — while must_call is satisfied.
    trace = Trace(calls=[("get_pod_logs", {})], answer="notify-worker is crashing.")
    with patch("evals.run.run_scenario", AsyncMock(return_value=trace)):
        result = await _run_one(_scenario(must_call=["get_pod_logs"]), runs=1)

    assert result["passes"] == 1, "advisory-only failure must not fail the attempt"
    attempt = result["attempts"][0]
    assert attempt["passed"] is True
    # The advisory check must still be recorded, and still show as failed —
    # advisory means "does not gate the verdict", not "invisible".
    advisory_checks = [c for c in attempt["checks"] if c["name"] == "no_unknown_names"]
    assert len(advisory_checks) == 1
    assert advisory_checks[0]["advisory"] is True
    assert advisory_checks[0]["passed"] is False


async def test_blocking_failure_still_fails_the_attempt():
    """A real assertion failure (must_call) must still fail the attempt,
    advisory checks notwithstanding."""
    trace = Trace(calls=[("search_pods", {})], answer="ok")
    with patch("evals.run.run_scenario", AsyncMock(return_value=trace)):
        result = await _run_one(_scenario(must_call=["get_pod_logs"]), runs=1)

    assert result["passes"] == 0
    assert result["attempts"][0]["passed"] is False


async def test_advisory_check_recorded_even_when_it_passes():
    """no_unknown_names must be present in the recorded checks (with its
    advisory flag) whether or not it fires, so the report always shows it."""
    trace = Trace(calls=[], answer="ok")
    with patch("evals.run.run_scenario", AsyncMock(return_value=trace)):
        result = await _run_one(_scenario(), runs=1)

    checks_by_name = {c["name"]: c for c in result["attempts"][0]["checks"]}
    assert checks_by_name["no_unknown_names"]["advisory"] is True
    assert checks_by_name["no_unknown_names"]["passed"] is True
