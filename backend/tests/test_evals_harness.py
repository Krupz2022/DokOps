"""Deterministic self-tests for the eval harness.

The evals themselves call a real LLM and are non-deterministic; the harness
that runs them must not be. These tests stub the model and assert the harness
records what the agent did.
"""
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from evals.harness import Scenario, Trace, load_scenarios, run_scenario

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


async def test_unfixtured_tool_returns_an_explicit_miss_not_a_crash():
    """A tool the scenario did not fixture must not raise — the model asked for
    something the author did not anticipate, and that should show up in the
    trace as a call, not kill the run."""
    scenario = Scenario(
        name="t", query="q", history=[], namespace=None, presweep="", topology="",
        cluster={}, expect={}, path=pathlib.Path("t.yaml"),
    )

    async def fake_loop(**kwargs):
        from app.tools import registry
        res = await registry.execute_tool_async("get_pod_logs", {"pod": "x"})
        assert res["success"] is False
        yield {"type": "result", "message": "done"}

    with patch("app.services.ai_service.ai_service.run_global_agentic_loop", fake_loop):
        trace = await run_scenario(scenario)

    assert trace.calls == [("get_pod_logs", {"pod": "x"})]


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
