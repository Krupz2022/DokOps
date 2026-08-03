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


def test_hallucination_scan_is_not_defeated_by_substring_containment():
    """A raw substring test lets a hallucinated short name hide inside a longer
    real one (e.g. "api-gateway" inside "api-gateway-prod-7d4f") — exactly the
    case a human most needs flagged. Tokenizing the corpus with the same regex
    used on the answer, then testing set membership, closes that gap."""
    scenario = Scenario(
        name="t", query="why is the workload failing", history=[], namespace="payments",
        presweep="", topology="",
        cluster={"get_pod_logs": {"success": True, "data": "restart loop on api-gateway-prod-7d4f"}},
        expect={}, path=pathlib.Path("t.yaml"),
    )
    trace = Trace(calls=[], answer="The failure is in api-gateway.")
    assert "api-gateway" in suspected_hallucinations(trace.answer, scenario, trace)


def test_hallucination_scan_ignores_underscore_adjacent_names_in_corpus():
    """Word boundaries do not fire between two word characters, and "_" is a
    word character, so a hyphenated object name glued to snake_case text (e.g.
    "restart_count_api-gateway") would never become its own corpus token
    without normalization, and a correct answer using that name would be
    flagged as a hallucination. Corpus-side "_" -> " " fixes this; the answer
    side is deliberately left un-normalized (see the function's own comment)."""
    scenario = Scenario(
        name="t", query="why is sample-api failing", history=[], namespace="payments",
        presweep="restart_count_api-gateway is elevated", topology="",
        cluster={}, expect={}, path=pathlib.Path("t.yaml"),
    )
    trace = Trace(calls=[], answer="The failure is in api-gateway.")
    assert suspected_hallucinations(trace.answer, scenario, trace) == []


def test_hallucination_scan_still_flags_masked_name_after_underscore_fix():
    """Guards test_hallucination_scan_is_not_defeated_by_substring_containment
    (round 1's masking fix) against regression from the underscore-adjacency
    fix directly above: the two pull in opposite directions — one widens what
    counts as a corpus token, the other narrows it — and a change satisfying
    one must not silently undo the other. "api-gateway-prod-7d4f" in the
    corpus must still NOT mask a hallucinated "api-gateway" in the answer."""
    scenario = Scenario(
        name="t", query="why is the workload failing", history=[], namespace="payments",
        presweep="", topology="",
        cluster={"get_pod_logs": {"success": True, "data": "restart loop on api-gateway-prod-7d4f"}},
        expect={}, path=pathlib.Path("t.yaml"),
    )
    trace = Trace(calls=[], answer="The failure is in api-gateway.")
    assert suspected_hallucinations(trace.answer, scenario, trace) == ["api-gateway"]


def test_hallucination_scan_accepts_names_present_in_fixture_data_still_holds_under_tokenization():
    """Regression guard: tokenizing the corpus must not turn a real multi-hyphen
    token like "redis-master" into a false positive when the answer mentions it
    with the same trailing port suffix as the fixture."""
    trace = Trace(calls=[], answer="It cannot reach redis-master:6379.")
    assert suspected_hallucinations(trace.answer, _scenario(), trace) == []


def test_hallucination_scan_accepts_namespace_mentioned_in_answer():
    scenario = Scenario(
        name="t", query="why is sample-api failing", history=[], namespace="kube-system",
        presweep="", topology="",
        cluster={}, expect={}, path=pathlib.Path("t.yaml"),
    )
    trace = Trace(calls=[], answer="The issue originates in kube-system.")
    assert suspected_hallucinations(trace.answer, scenario, trace) == []


def test_must_not_end_on_question_fails_on_quote_wrapped_question():
    trace = Trace(calls=[], answer="I could ask: 'Should I proceed?'")
    check = _checks(_scenario(must_not_end_on_question=True), trace)["must_not_end_on_question"]
    assert not check.passed


def test_must_call_empty_list_fails_with_explanation():
    trace = Trace(calls=[("get_pod_logs", {})], answer="ok")
    check = _checks(_scenario(must_call=[]), trace)["must_call"]
    assert not check.passed
    assert "empty list" in check.detail


def test_must_not_call_empty_list_fails_with_explanation():
    trace = Trace(calls=[], answer="ok")
    check = _checks(_scenario(must_not_call=[]), trace)["must_not_call"]
    assert not check.passed
    assert "empty list" in check.detail


def test_must_cite_empty_list_fails_with_explanation():
    trace = Trace(calls=[], answer="ok")
    check = _checks(_scenario(must_cite=[]), trace)["must_cite"]
    assert not check.passed
    assert "empty list" in check.detail


def test_absent_assertion_key_adds_no_check():
    """An absent key must keep its current behaviour: no check at all — only a
    present-but-empty list is treated as a defect."""
    trace = Trace(calls=[], answer="ok")
    checks = _checks(_scenario(), trace)
    assert "must_call" not in checks
    assert "must_not_call" not in checks
    assert "must_cite" not in checks
    assert "must_not_cite" not in checks


def test_must_not_call_passes_when_forbidden_tool_not_used():
    trace = Trace(calls=[("get_pod_logs", {})], answer="ok")
    assert _checks(_scenario(must_not_call=["restart_pod"]), trace)["must_not_call"].passed


def test_must_cite_fails_when_missing_from_answer():
    trace = Trace(calls=[], answer="The pod is fine.")
    check = _checks(_scenario(must_cite=["Connection refused"]), trace)["must_cite"]
    assert not check.passed
    assert "Connection refused" in check.detail


def test_must_not_cite_fails_when_forbidden_phrase_present():
    trace = Trace(calls=[], answer="Likely caused by a missing readiness probe.")
    check = _checks(_scenario(must_not_cite=["readiness probe"]), trace)["must_not_cite"]
    assert not check.passed


def test_must_not_cite_passes_when_forbidden_phrase_absent():
    trace = Trace(calls=[], answer="Connection refused on redis-master:6379.")
    assert _checks(_scenario(must_not_cite=["readiness probe"]), trace)["must_not_cite"].passed


def test_must_not_cite_empty_list_fails_with_explanation():
    trace = Trace(calls=[], answer="ok")
    check = _checks(_scenario(must_not_cite=[]), trace)["must_not_cite"]
    assert not check.passed
    assert "empty list" in check.detail
