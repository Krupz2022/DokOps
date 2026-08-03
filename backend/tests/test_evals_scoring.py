import pathlib

from evals.harness import Scenario, Trace
from evals.scoring import score, suspected_hallucinations


def _scenario(**expect):
    return Scenario(
        name="t", query="why is sample-api failing", history=[], namespace="payments",
        presweep="", topology="",
        cluster={"get_pod_logs": {"success": True, "data": "ConnectionRefusedError on redis-master:6379"}},
        expect=expect, path=pathlib.Path("t.yaml"),
    )


def _checks(scenario, trace):
    return {c.name: c for c in score(scenario, trace)}


def test_must_call_passes_when_tool_was_called():
    trace = Trace(calls=[("get_pod_logs", {})], answer="ok")
    assert _checks(_scenario(must_call=["get_pod_logs"]), trace)["must_call"].passed


def test_must_call_fails_and_names_the_missing_tool():
    trace = Trace(calls=[("search_pods", {})], answer="ok")
    check = _checks(_scenario(must_call=["get_pod_logs"]), trace)["must_call"]
    assert not check.passed
    assert "get_pod_logs" in check.detail


def test_must_not_call_fails_when_forbidden_tool_used():
    trace = Trace(calls=[("restart_pod", {})], answer="ok")
    check = _checks(_scenario(must_not_call=["restart_pod"]), trace)["must_not_call"]
    assert not check.passed
    assert "restart_pod" in check.detail


def test_must_cite_is_case_insensitive_substring():
    trace = Trace(calls=[], answer="The pod hit a **connection refused** error.")
    assert _checks(_scenario(must_cite=["Connection refused"]), trace)["must_cite"].passed


def test_must_not_end_on_question_fails_on_trailing_question():
    trace = Trace(calls=[], answer="This is likely a DNS issue.\n\nWould you like me to investigate?")
    check = _checks(_scenario(must_not_end_on_question=True), trace)["must_not_end_on_question"]
    assert not check.passed


def test_must_not_end_on_question_passes_on_a_statement():
    trace = Trace(calls=[], answer="Root cause: redis-master is unreachable on 6379.")
    assert _checks(_scenario(must_not_end_on_question=True), trace)["must_not_end_on_question"].passed


def test_error_in_trace_fails_everything():
    trace = Trace(calls=[], answer="", error="RuntimeError: provider down")
    checks = _checks(_scenario(must_call=["get_pod_logs"]), trace)
    assert not checks["run_completed"].passed


def test_hallucination_scan_flags_a_name_absent_from_fixtures_and_query():
    trace = Trace(calls=[], answer="The failure is in the billing-worker deployment.")
    assert "billing-worker" in suspected_hallucinations(trace.answer, _scenario(), trace)


def test_hallucination_scan_accepts_names_present_in_fixture_data():
    trace = Trace(calls=[], answer="It cannot reach redis-master:6379.")
    assert suspected_hallucinations(trace.answer, _scenario(), trace) == []


def test_hallucination_scan_accepts_names_from_the_query():
    trace = Trace(calls=[], answer="sample-api is the failing workload.")
    assert suspected_hallucinations(trace.answer, _scenario(), trace) == []


def test_hallucination_scan_ignores_common_hyphenated_prose():
    """Low noise matters more than total recall here — a scan that cries wolf
    on ordinary English gets switched off and catches nothing."""
    trace = Trace(calls=[], answer="This is a well-known read-only check, up-to-date as of now.")
    assert suspected_hallucinations(trace.answer, _scenario(), trace) == []
