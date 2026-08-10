"""The four assertions are one omission class with four instances: a fact
declared in one place and relied on in another, with nothing to fail when they
diverge. A fifth such pair gets the same treatment."""
import pytest


def _full_schema():
    from app.tools.registry import build_openai_tools_schema
    return build_openai_tools_schema()


def test_every_table_tool_exists_in_the_registry():
    from app.services.selection_invariants import verify_selection_invariants
    verify_selection_invariants()          # raises RuntimeError on any violation


def test_unknown_tool_name_in_the_table_is_rejected():
    from app.services import presweep
    from app.services.selection_invariants import verify_selection_invariants
    original = presweep.SYMPTOM_TOOLS
    presweep.SYMPTOM_TOOLS = {**original, "OOMKilled": ("no_such_tool_xyz",)}
    try:
        with pytest.raises(RuntimeError, match="no_such_tool_xyz"):
            verify_selection_invariants()
    finally:
        presweep.SYMPTOM_TOOLS = original


def test_table_row_for_a_reason_presweep_cannot_produce_is_rejected():
    """The ImagePullBackOff lesson: a row keyed on a reason outside the
    evidence surface is dead on arrival and must fail startup."""
    from app.services import presweep
    from app.services.selection_invariants import verify_selection_invariants
    original = presweep.SYMPTOM_TOOLS
    presweep.SYMPTOM_TOOLS = {**original, "NeverEmittedReason": ("get_pod_logs",)}
    try:
        with pytest.raises(RuntimeError, match="NeverEmittedReason"):
            verify_selection_invariants()
    finally:
        presweep.SYMPTOM_TOOLS = original


def test_evidence_reason_without_a_row_is_rejected():
    from app.services import presweep
    from app.services.selection_invariants import verify_selection_invariants
    original = presweep._BLOCKED_REASONS
    presweep._BLOCKED_REASONS = original + ("BrandNewKubeletReason",)
    try:
        with pytest.raises(RuntimeError, match="BrandNewKubeletReason"):
            verify_selection_invariants()
    finally:
        presweep._BLOCKED_REASONS = original


def test_every_write_tool_guards_on_confirmed():
    """The gate is enforced by convention: the dispatcher reacts to the tool's
    return value, never to the registry's requires_confirmation flag. A write
    tool that declares the flag and omits the guard mutates immediately.

    Unlike tests 2-4 (which corrupt presweep's side of the contract), this
    corrupts the registry's side: a write tool that accepts `confirmed` but
    never checks it, the exact shape the docstring above warns about — the
    parameter is present, so a naive "has confirmed?" check alone would miss
    it; only the source-guard regex catches it.
    """
    from app.tools import registry
    from app.services.selection_invariants import verify_selection_invariants

    async def _stub_unguarded_write(reason: str = "", confirmed: bool = False) -> dict:
        # Deliberately missing the standard confirmation guard other write tools
        # use before mutating — that omission is exactly what this test targets.
        return {"success": True}

    original = registry.TOOL_REGISTRY
    registry.TOOL_REGISTRY = {
        **original,
        "__test_unguarded_write_tool__": {
            "function": _stub_unguarded_write,
            "description": "test-only stub for assertion 3",
            "inputs": ["reason"],
            "operation_type": "write",
            "requires_confirmation": True,
        },
    }
    try:
        with pytest.raises(RuntimeError, match="__test_unguarded_write_tool__"):
            verify_selection_invariants()
    finally:
        registry.TOOL_REGISTRY = original


async def test_crash_log_text_selects_the_dependency_domain():
    """The crash log already names the failing dependency. Matching it beats
    classifying the user's question: 'why is checkout failing' names no
    database, but its log says postgres."""
    from app.services.ai_service import AIService
    from app.services.presweep import Finding

    findings = [Finding("crashlogs", "pod", "checkout-1", "app", "CrashLoopBackOff",
                        "FATAL: could not connect to postgres at db.internal:5432")]
    assert "postgres_" in AIService._domains_from_evidence(findings)


async def test_evidence_domains_are_empty_without_a_dependency_mention():
    from app.services.ai_service import AIService
    from app.services.presweep import Finding

    findings = [Finding("crashlogs", "pod", "api-1", "app", "OOMKilled", "Minimum worker threads: 100")]
    assert AIService._domains_from_evidence(findings) == set()


def test_domain_order_is_a_literal_tuple_covering_every_emittable_domain():
    """sorted() would couple cache correctness to an implicit property a rename
    could shift silently, invalidating every downstream prefix with nothing
    failing. Assertion 4 covers completeness; only reading the source covers
    literalness — `tuple(sorted(set(_SERVICE_TOOL_MAP.values())))` is complete
    by construction and would leave the coverage check green forever."""
    import inspect
    import re
    from app.services.ai_service import AIService
    from app.services.selection_invariants import verify_selection_invariants

    verify_selection_invariants()                      # completeness
    src = inspect.getsource(AIService)
    literal = re.search(r"^\s*_DOMAIN_ORDER\s*:[^=]*=\s*\((.*?)\)",
                        src, re.MULTILINE | re.DOTALL)
    assert literal, "_DOMAIN_ORDER is no longer assigned a parenthesised literal"
    body = literal.group(1)
    assert "sorted" not in body, "_DOMAIN_ORDER must be a literal, not sorted() at runtime"
    # Every element is a plain quoted string, not a name or a call.
    assert all(re.fullmatch(r"""['"][a-z0-9_]+['"]""", part.strip())
               for part in body.split(",") if part.strip()), \
        f"_DOMAIN_ORDER must hold only string literals, got: {body!r}"


def test_a_domain_missing_from_the_ordering_tuple_is_rejected():
    from app.services.ai_service import AIService
    from app.services.selection_invariants import verify_selection_invariants
    original = AIService._DOMAIN_ORDER
    AIService._DOMAIN_ORDER = tuple(d for d in original if d != "redis_")
    try:
        # Matched on assertion 4's own wording, not just on "redis_": the domain
        # name alone would let any future unrelated message carrying it pass.
        with pytest.raises(RuntimeError, match="absent from _DOMAIN_ORDER"):
            verify_selection_invariants()
    finally:
        AIService._DOMAIN_ORDER = original


def test_evidence_tools_survive_the_cap():
    """Evidence is a floor: lower tiers only ADD, nothing removes a tier-1
    selection."""
    from app.services.ai_service import AIService
    selected = AIService._select_dynamic_tools(
        "is the cluster healthy", [], _full_schema(), [], [],
        max_total=20, evidence_tools=frozenset({"patch_deployment_resources"}),
    )
    assert "patch_deployment_resources" in {t["function"]["name"] for t in selected}


def test_tier_one_tools_are_ordered_last():
    """Volatile-last: tier-1 tools track cluster state, so they are the worst
    prefix citizens. Everything stable must precede them."""
    from app.services.ai_service import AIService
    selected = AIService._select_dynamic_tools(
        "why is checkout failing", [], _full_schema(), [], [],
        evidence_tools=frozenset({"patch_deployment_resources"}),
    )
    names = [t["function"]["name"] for t in selected]
    assert names[-1] == "patch_deployment_resources"


def test_evidence_domains_only_add_never_remove():
    """A floor means a superset, on every turn. Merging evidence domains into
    matched_service_prefixes would have fed `is_service`, and the service branch
    omits the relevance-scored k8s_rest tail — so a crash log that merely says
    'postgres' would have REMOVED query-scored tools from a plain k8s question.
    Evidence drives which domain toolsets are injected, never which branch runs."""
    from app.services.ai_service import AIService
    schema = _full_schema()
    query = "why is the checkout deployment failing"

    def _names(**kw):
        return {t["function"]["name"] for t in AIService._select_dynamic_tools(
            query, [], schema, [], [], max_total=200, **kw)}

    baseline = _names()
    with_evidence = _names(evidence_domains=frozenset({"postgres_"}))
    assert baseline <= with_evidence, (
        f"evidence removed {sorted(baseline - with_evidence)}")
    assert any(n.startswith("postgres_") for n in with_evidence)


def test_domain_blocks_follow_the_tuple_and_precede_the_evidence_block():
    """The cache contract itself: domains appear in _DOMAIN_ORDER order (not
    registry order), and the whole stable prefix precedes the volatile tier-1
    block. Asserted at BLOCK level — a [-1] check alone passes an implementation
    that ignores _DOMAIN_ORDER entirely."""
    from app.services.ai_service import AIService
    order = AIService._DOMAIN_ORDER
    assert order.index("postgres_") < order.index("redis_")   # premise of (a)

    selected = AIService._select_dynamic_tools(
        "why is checkout failing", [], _full_schema(), [], [],
        max_total=200,          # ordering under test, not the cap
        evidence_tools=frozenset({"patch_deployment_resources"}),
        evidence_domains=frozenset({"postgres_", "redis_"}),
    )
    names = [t["function"]["name"] for t in selected]
    postgres = [i for i, n in enumerate(names) if n.startswith("postgres_")]
    redis = [i for i, n in enumerate(names) if n.startswith("redis_")]
    assert postgres and redis, f"both domains must be injected, got {names}"

    # (a) tuple order, not registry order: postgres_ precedes redis_ as a block.
    assert max(postgres) < min(redis)

    # (b) every stable tool precedes every volatile one.
    evidence = [i for i, n in enumerate(names) if n == "patch_deployment_resources"]
    assert max(i for i, n in enumerate(names)
               if n != "patch_deployment_resources") < min(evidence)


async def test_tier_two_contribution_is_logged_split_by_whether_tier_one_ran(caplog):
    """Unsplit, this number averages redundancy against irreplaceable cold-start
    coverage — opposite conclusions. It must never be reported unsplit."""
    import logging
    from app.services.ai_service import AIService
    with caplog.at_level(logging.INFO, logger="ai_service.selection"):
        AIService._log_selection(
            tier1_ran=False, tier1_tools=set(), tier1b_domains=set(),
            tier2_domains={"redis_"}, loaded=["get_pod_logs"], called=[], expansions=[],
        )
    msg = caplog.text
    assert "tier2_when_tier1_empty=1" in msg
    assert "tier2_when_tier1_ran=0" in msg


async def test_tier_two_contribution_counts_as_redundancy_when_tier_one_ran(caplog):
    """The other half of the split: the same contribution must land in the
    redundancy column, never both columns and never neither."""
    import logging
    from app.services.ai_service import AIService
    with caplog.at_level(logging.INFO, logger="ai_service.selection"):
        AIService._log_selection(
            tier1_ran=True, tier1_tools={"get_pod_logs"}, tier1b_domains={"postgres_"},
            tier2_domains={"redis_"}, loaded=["get_pod_logs"], called=[], expansions=[],
        )
    assert "tier2_when_tier1_ran=1" in caplog.text
    assert "tier2_when_tier1_empty=0" in caplog.text


async def test_expansion_outcome_is_logged_not_only_the_count(caplog):
    """A bare count cannot separate a registry-description gap (the model had to
    discover a tool the cascade should have loaded, and used it) from noise (it
    discovered tools and used none). The success count is the whole signal."""
    import logging
    from app.services.ai_service import AIService
    with caplog.at_level(logging.INFO, logger="ai_service.selection"):
        AIService._log_selection(
            tier1_ran=True, tier1_tools={"get_pod_logs"}, tier1b_domains=set(),
            tier2_domains=set(), loaded=["get_pod_logs"], called=["update_configmap"],
            expansions=[
                {"new_tools": ["update_configmap"], "expansion_succeeded": True},
                {"new_tools": ["redis_get_key"], "expansion_succeeded": False},
            ],
        )
    assert "expansions=2 expansions_ok=1" in caplog.text


async def test_every_turn_logs_exactly_one_selection_line(caplog, monkeypatch):
    """The loop has nine result-producing exits, so the line is emitted from a
    finally rather than from each branch. Verified on the error exit, which is
    also the one where no tier variable is ever assigned: a per-branch call logs
    zero lines here, and a finally reading unassigned locals would raise."""
    import logging
    from app.services.ai_service import AIService

    def _boom():
        raise RuntimeError("no client configured")

    svc = AIService()
    monkeypatch.setattr(svc, "_get_caching_client", _boom)
    with caplog.at_level(logging.INFO, logger="ai_service.selection"):
        events = [e async for e in
                  svc._run_global_agentic_loop_inner(query="is the cluster healthy")]

    assert any(e.get("type") == "result" for e in events), events
    lines = [r for r in caplog.records if r.name == "ai_service.selection"]
    assert len(lines) == 1, f"expected exactly one [SEL] line, got {len(lines)}"
    assert "tier1_ran=False" in lines[0].getMessage()
    assert "called=0 expansions=0 expansions_ok=0" in lines[0].getMessage()
    # Crashed before the provider setting was read, and the line says so rather
    # than naming a provider it never saw.
    assert "provider=?" in lines[0].getMessage()


async def test_a_real_turn_logs_one_line_with_the_tiers_actually_wired(caplog):
    """The gap this closes: a defined-but-uncalled _log_selection, or a call site
    handed empty literals, both look fine in a unit test and produce a log whose
    fields are structurally always zero. So drive a whole turn and assert the line
    exists once AND that tier 2 carries the domain the query really named."""
    import logging
    from unittest.mock import MagicMock, patch
    from app.services.ai_service import ai_service

    def fake_create(**kwargs):
        resp = MagicMock()
        resp.choices[0].message.content = "Final Answer: redis looks healthy"
        return resp

    with caplog.at_level(logging.INFO, logger="ai_service.selection"), \
         patch.object(ai_service, "_get_client") as mock_client, \
         patch.object(ai_service, "_get_setting", return_value="gpt-3.5-turbo"):
        mock_client.return_value.chat.completions.create.side_effect = fake_create
        events = [e async for e in
                  ai_service.run_global_agentic_loop("is redis healthy")]

    assert any(e.get("type") == "result" for e in events), events
    lines = [r for r in caplog.records if r.name == "ai_service.selection"]
    assert len(lines) == 1, f"expected exactly one [SEL] line, got {len(lines)}"
    msg = lines[0].getMessage()
    assert "tier2=['redis_']" in msg, msg      # tier 2 is read from the real scan
    assert "loaded=0" not in msg, msg          # and `loaded` from the real schema
    # Read from the turn, not defaulted: a GEMINI turn skips the cascade and emits
    # every tier empty with a real `called` count, which is only readable as
    # "the cascade did not run here" if the provider is on the line.
    assert "provider=gpt-3.5-turbo" in msg, msg


def test_the_selection_line_is_emitted_from_a_finally_exactly_once():
    """Structural, because the alternative is unobservable: per-branch calls would
    need one at each of the loop's nine result-producing exits, and a forgotten one
    logs nothing while a duplicate double-counts every ratio read off these lines.
    Only the source shows there is exactly one call and that it sits in the
    outermost finally, where every exit — including consumer abandonment — passes."""
    import inspect
    from app.services.ai_service import AIService
    src = inspect.getsource(AIService._run_global_agentic_loop_inner)
    assert src.count("_log_selection(") == 1, "exactly one call site, or the count lies"
    after_outer_finally = src.split("\n        finally:\n")[-1]
    assert "_log_selection(" in after_outer_finally, \
        "the call must live in the loop's outermost finally, not on one exit path"


def test_tier_two_domains_come_from_the_same_scan_the_selection_uses():
    """The logged tier-2 number and the tools actually injected must be the same
    scan. A second copy of the keyword walk would let the number drift from the
    selection with nothing failing — so the selector is required to call the
    helper the log reads, not to keep its own copy."""
    import inspect
    from app.services.ai_service import AIService
    q = "why is redis slow"
    assert AIService._domains_from_query(q) == {"redis_"}
    names = {t["function"]["name"] for t in AIService._select_dynamic_tools(
        q, [], _full_schema(), [], [], max_total=200)}
    assert any(n.startswith("redis_") for n in names)
    assert "_domains_from_query" in inspect.getsource(AIService._select_dynamic_tools), \
        "the selection must read tier 2 from the same helper the log does"


def test_the_scanned_tier_two_set_is_injected_not_rescanned():
    """One scan per turn: the agent loop runs it (it needs the set for the [SEL]
    line) and hands it over. `query_domains` must therefore DRIVE the injection —
    if the selector rescanned the query instead, this query names no service and
    no redis tool would appear, and the logged number would describe a scan the
    selection ignored."""
    from app.services.ai_service import AIService
    names = {t["function"]["name"] for t in AIService._select_dynamic_tools(
        "why is checkout failing", [], _full_schema(), [], [], max_total=200,
        query_domains={"redis_"})}
    assert any(n.startswith("redis_") for n in names)


def test_the_query_scan_runs_once_per_turn():
    """The plan's standing constraint: no parallel selector, nothing runs twice.
    The loop needs tier 2 for its log AND for the injection; counting calls is the
    only way to catch a second walk, since two walks of the same map agree and so
    no assertion on the RESULT can ever fail."""
    from app.services.ai_service import AIService
    calls: list = []
    real = AIService._domains_from_query        # a plain function via the class

    def _counting(q, history=None):
        calls.append(q)
        return real(q, history)

    AIService._domains_from_query = staticmethod(_counting)
    try:
        AIService._select_dynamic_tools(
            "why is redis slow", [], _full_schema(), [], [], max_total=200,
            query_domains=AIService._domains_from_query("why is redis slow"))
    finally:
        AIService._domains_from_query = staticmethod(real)
    assert len(calls) == 1, f"the keyword scan ran {len(calls)} times, must run once"
