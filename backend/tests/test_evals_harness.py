"""Deterministic self-tests for the eval harness.

The evals themselves call a real LLM and are non-deterministic; the harness
that runs them must not be. These tests stub the model and assert the harness
records what the agent did.
"""
import pathlib
from unittest.mock import patch

import pytest

from evals.harness import (
    SEAMS,
    Scenario,
    Trace,
    _patched_cluster,
    _resolve_seam_owner,
    load_scenarios,
    run_scenario,
)

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


def test_all_seam_targets_still_resolve():
    """Rename-detector for SEAMS, the harness's single source of truth for
    every patch target `_patched_cluster` neutralises (k8s tool dispatch, MCP
    schema + execution, the observability tool registry, presweep/topology,
    external + internal RAG, the prerequisite check, custom tool definitions
    + execution).

    Most of the other tests in this file replace `run_global_agentic_loop`
    wholesale, so execution never reaches the inner loop and none of these
    targets are ever consulted there. Without this test, a rename on any of
    them would leave every one of those tests green while silently losing
    seam coverage (e.g. an MCP tool call reaching a real server, or an
    observability tool call reaching a real Prometheus/Loki/Grafana/
    Elasticsearch/Datadog endpoint).

    This is deliberately the cheap check: it does not run the loop or apply
    the patches, it only confirms each (owner, attribute) pair in SEAMS still
    exists to be patched. `test_custom_tools_are_closed_off_inside_patched_cluster`
    below is the complementary expensive check: it actually applies the
    patches and proves the escape routes are closed, not just that the patch
    targets still exist.
    """
    assert SEAMS, "SEAMS must not be empty"
    for dotted_path, _factory in SEAMS:
        owner, attr = _resolve_seam_owner(dotted_path)
        assert hasattr(owner, attr), f"seam target no longer resolves: {dotted_path}"


async def test_custom_tools_are_closed_off_inside_patched_cluster():
    """Proves the custom-tool escape route is actually closed, not just that
    the patch targets still exist (that's `test_all_seam_targets_still_resolve`
    above — a rename-detector, not a coverage-detector). This test applies
    the real patches via `_patched_cluster` and exercises the same code paths
    `_run_global_agentic_loop_inner` uses.

    Background: `AIService._get_custom_tools_definitions` flattens operator-
    authored YAML toolsets from disk (`app/toolsets/*.yaml`) into ordinary
    function-calling tools with no seam of their own, and
    `AIService._execute_custom_tool` dispatches them to a real
    `subprocess.run`. This repo's `app/toolsets/helm_toolset.yaml` defines 22
    Helm tools, several destructive (e.g. `helm_upgrade_set_tag`, which has
    NO `god_mode` key set, so `_execute_custom_tool`'s only in-band guard
    does not gate it) — so an unpatched eval run could execute a real `helm
    upgrade` against whatever cluster `~/.kube/config` points at, driven by
    the always-on WRITE TOOL RULE that tells the model to call a write tool
    immediately without asking.

    Compares against the REAL, unpatched custom tool list (read fresh from
    disk before entering `_patched_cluster`) rather than a hardcoded name, so
    this test stays meaningful as toolsets on disk change.
    """
    from app.services.ai_service import AIService, ai_service
    from app.tools import registry as _registry

    real_custom_tools = ai_service._get_custom_tools_definitions()
    real_names = {t["name"] for t in real_custom_tools}
    assert real_names, (
        "expected at least one real custom tool on disk (app/toolsets/*.yaml) "
        "for this test to be meaningful against the actual exposure -- if "
        "toolsets were intentionally removed, this assertion needs updating, "
        "not skipping"
    )
    assert "helm_upgrade_set_tag" in real_names, (
        "expected helm_toolset.yaml's helm_upgrade_set_tag on disk -- this "
        "pins the test to the exact tool named in the safety report "
        "(destructive, god_mode unset)"
    )

    scenario = Scenario(
        name="t",
        query="the billing database is slow, connections seem exhausted",
        history=[], namespace=None, presweep="", topology="",
        cluster={}, expect={}, path=pathlib.Path("t.yaml"),
    )
    trace = Trace()

    with _patched_cluster(scenario, trace):
        # 1. Definitions seam: must return nothing while patched.
        assert ai_service._get_custom_tools_definitions() == []

        # 2. Schema seam: rebuild the tool schema the same way
        #    _run_global_agentic_loop_inner does for a representative
        #    scenario query (ai_service.py's OpenAI/Azure provider branch,
        #    ~ai_service.py:1773-1780) using the now-patched custom_tools
        #    source, and confirm none of the REAL names leak in through any
        #    other path (e.g. discover_tools, or a future change that stops
        #    routing through _get_custom_tools_definitions).
        patched_custom_tools = ai_service._get_custom_tools_definitions()
        full_k8s_schema = _registry.build_openai_tools_schema()
        custom_schema = _registry.build_openai_tools_schema(
            extra_tools=patched_custom_tools or []
        )[len(full_k8s_schema):]
        selected = AIService._select_dynamic_tools(
            query=scenario.query,
            obs_tools_schema=[],
            full_k8s_schema=full_k8s_schema,
            mcp_schema=[],
            custom_tools_schema=custom_schema,
        )
        selected_names = {t["function"]["name"] for t in selected}
        leaked = selected_names & real_names
        assert not leaked, (
            f"custom tool names leaked into the schema offered to the model: "
            f"{sorted(leaked)}"
        )

        # 3. Execution seam: cannot shell out. Assert the stub's own loud
        #    behaviour (it raises) rather than asserting a subprocess did not
        #    run -- see _blocked_custom_tool's docstring in harness.py for
        #    why raising, not a quiet stub, is the chosen backstop.
        with pytest.raises(RuntimeError, match="eval harness bug"):
            await ai_service._execute_custom_tool(real_custom_tools[0], {})
