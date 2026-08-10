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
