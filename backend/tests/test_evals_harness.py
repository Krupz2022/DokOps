"""Deterministic self-tests for the eval harness.

The evals themselves call a real LLM and are non-deterministic; the harness
that runs them must not be. These tests stub the model and assert the harness
records what the agent did.
"""
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from evals.defaults import CORE_TOOL_DEFAULTS
from evals.harness import SEAMS, Scenario, Trace, _resolve_seam_owner, load_scenarios, run_scenario

pytestmark = pytest.mark.asyncio

SCENARIOS = pathlib.Path(__file__).parent.parent / "evals" / "scenarios"


def test_load_scenarios_reads_every_yaml():
    scenarios = load_scenarios(SCENARIOS)
    assert scenarios, "no scenarios found"
    names = {s.name for s in scenarios}
    assert "self-check" in names


def test_scenario_defaults_are_filled():
    """A scenario declaring only query + cluster must still be runnable."""
    scenarios = {s.name: s for s in load_scenarios(SCENARIOS)}
    s = scenarios["self-check"]
    assert s.history == []
    assert isinstance(s.cluster, dict)
    assert isinstance(s.expect, dict)


async def test_run_scenario_records_tool_calls_and_answer():
    """The harness must serve fixtures for tool calls and capture the trace."""
    scenario = Scenario(
        name="t", query="q", history=[], namespace=None, presweep="", topology="",
        cluster={"search_pods": {"success": True, "data": ["api-0"]}},
        expect={}, path=pathlib.Path("t.yaml"),
    )

    async def fake_loop(**kwargs):
        from app.tools import registry
        await registry.execute_tool_async("search_pods", {"status": "failing"})
        yield {"type": "step", "message": "working"}
        yield {"type": "result", "message": "api-0 is failing"}

    with patch("app.services.ai_service.ai_service.run_global_agentic_loop", fake_loop):
        trace = await run_scenario(scenario)

    assert trace.calls == [("search_pods", {"status": "failing"})]
    assert trace.answer == "api-0 is failing"
    assert trace.error is None


async def test_unfixtured_unknown_tool_returns_an_explicit_miss_not_a_crash():
    """A tool that is neither scenario-fixtured NOR one of AIService._CORE_K8S's
    always-on tools must not raise — the model asked for something the author
    did not anticipate and the harness has no safe default for, and that must
    show up in the trace as a call, not kill the run or get papered over."""
    scenario = Scenario(
        name="t", query="q", history=[], namespace=None, presweep="", topology="",
        cluster={}, expect={}, path=pathlib.Path("t.yaml"),
    )

    async def fake_loop(**kwargs):
        from app.tools import registry
        res = await registry.execute_tool_async("totally_unrecognised_tool", {"pod": "x"})
        assert res["success"] is False
        assert "no fixture" in res["error"]
        yield {"type": "result", "message": "done"}

    with patch("app.services.ai_service.ai_service.run_global_agentic_loop", fake_loop):
        trace = await run_scenario(scenario)

    assert trace.calls == [("totally_unrecognised_tool", {"pod": "x"})]


async def test_unfixtured_core_tool_gets_a_plausible_non_error_default():
    """A scenario that never mentions `list_services` (one of
    AIService._CORE_K8S's always-on tools) must not make the agent read the
    environment as broken. It should get a plausible, well-formed default
    (see evals/defaults.py) rather than the harness's own "no fixture" miss,
    and the call must still land in Trace.calls so must_not_call assertions
    and the report both still see it."""
    scenario = Scenario(
        name="t", query="q", history=[], namespace=None, presweep="", topology="",
        cluster={}, expect={}, path=pathlib.Path("t.yaml"),
    )

    async def fake_loop(**kwargs):
        from app.tools import registry
        res = await registry.execute_tool_async("list_services", {"namespace": "payments"})
        assert res["success"] is True
        assert res["data"] == {"services": [], "total": 0}
        yield {"type": "result", "message": "done"}

    with patch("app.services.ai_service.ai_service.run_global_agentic_loop", fake_loop):
        trace = await run_scenario(scenario)

    assert trace.calls == [("list_services", {"namespace": "payments"})]


async def test_scenario_fixture_overrides_core_default():
    """A scenario that DOES fixture a core tool must get exactly what it
    declared, not the generic default — scenario-declared fixtures always
    win."""
    scenario = Scenario(
        name="t", query="q", history=[], namespace=None, presweep="", topology="",
        cluster={"list_services": {"success": True, "data": {"services": [{"name": "checkout-web"}], "total": 1}}},
        expect={}, path=pathlib.Path("t.yaml"),
    )

    async def fake_loop(**kwargs):
        from app.tools import registry
        res = await registry.execute_tool_async("list_services", {})
        assert res["data"]["total"] == 1
        yield {"type": "result", "message": "done"}

    with patch("app.services.ai_service.ai_service.run_global_agentic_loop", fake_loop):
        trace = await run_scenario(scenario)

    assert trace.calls == [("list_services", {})]


def test_core_tool_defaults_cover_exactly_ai_service_core_k8s():
    """Rename-detector: CORE_TOOL_DEFAULTS must cover exactly
    AIService._CORE_K8S — no more, no less — so adding a new always-on core
    tool forces a decision about its default instead of silently
    reintroducing the "eval: no fixture" bug for it, and so a stale default
    is not left behind for a tool that no longer exists."""
    from app.services.ai_service import AIService

    assert set(CORE_TOOL_DEFAULTS) == AIService._CORE_K8S


async def test_loop_exception_is_captured_as_error_not_raised():
    scenario = Scenario(
        name="t", query="q", history=[], namespace=None, presweep="", topology="",
        cluster={}, expect={}, path=pathlib.Path("t.yaml"),
    )

    async def boom(**kwargs):
        raise RuntimeError("provider down")
        yield  # pragma: no cover — makes this an async generator

    with patch("app.services.ai_service.ai_service.run_global_agentic_loop", boom):
        trace = await run_scenario(scenario)

    assert trace.error is not None and "provider down" in trace.error
    assert trace.answer == ""


def test_all_seam_targets_still_resolve():
    """Rename-detector for SEAMS, the harness's single source of truth for
    every patch target `_patched_cluster` neutralises (k8s tool dispatch, MCP
    schema + execution, the observability tool registry, presweep/topology,
    external + internal RAG, the prerequisite check).

    None of the other tests in this file exercise `_patched_cluster` for real
    — they all replace `run_global_agentic_loop` wholesale, so execution
    never reaches the inner loop and none of these targets are ever
    consulted. Without this test, a rename on any of them would leave every
    other test green while silently losing seam coverage (e.g. an MCP tool
    call reaching a real server, or an observability tool call reaching a
    real Prometheus/Loki/Grafana/Elasticsearch/Datadog endpoint).

    This is deliberately the cheap check: it does not run the loop or apply
    the patches, it only confirms each (owner, attribute) pair in SEAMS still
    exists to be patched.
    """
    assert SEAMS, "SEAMS must not be empty"
    for dotted_path, _factory in SEAMS:
        owner, attr = _resolve_seam_owner(dotted_path)
        assert hasattr(owner, attr), f"seam target no longer resolves: {dotted_path}"
