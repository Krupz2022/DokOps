"""The four assertions are one omission class with four instances: a fact
declared in one place and relied on in another, with nothing to fail when they
diverge. A fifth such pair gets the same treatment."""
import pytest


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
