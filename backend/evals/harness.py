"""Runs the real agent loop against canned cluster fixtures.

The LLM is real — every failure mode these evals exist to catch is model
behaviour, so a stubbed model would pass while the product stayed broken.
Everything that would otherwise reach a live cluster or the network is
patched to serve the scenario instead, so the cluster half of the run is
fully deterministic.
"""
import contextlib
import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import yaml


@dataclass
class Scenario:
    name: str
    query: str
    history: List[dict]
    namespace: Optional[str]
    presweep: str
    topology: str
    cluster: Dict[str, Any]
    expect: Dict[str, Any]
    path: pathlib.Path


@dataclass
class Trace:
    calls: List[Tuple[str, dict]] = field(default_factory=list)
    answer: str = ""
    error: Optional[str] = None


def load_scenarios(directory: pathlib.Path) -> List[Scenario]:
    scenarios: List[Scenario] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        scenarios.append(
            Scenario(
                name=raw.get("name") or path.stem,
                query=raw["query"],
                history=raw.get("history") or [],
                namespace=raw.get("namespace"),
                presweep=raw.get("presweep") or "",
                topology=raw.get("topology") or "",
                cluster=raw.get("cluster") or {},
                expect=raw.get("expect") or {},
                path=path,
            )
        )
    return scenarios


def _fixture_server(scenario: Scenario, trace: Trace):
    """Stands in for registry.execute_tool_async: records the call, serves the fixture."""

    async def _serve(tool_name: str, inputs: dict, confirmed: bool = False) -> Dict[str, Any]:
        trace.calls.append((tool_name, inputs))
        if tool_name in scenario.cluster:
            return scenario.cluster[tool_name]
        # ponytail: an unfixtured tool returns an explicit miss rather than raising.
        # The call is still recorded, so must_not_call assertions fire on it and the
        # report shows the author which fixture the model wanted but did not get.
        return {
            "success": False,
            "error": f"eval: no fixture for '{tool_name}' in scenario '{scenario.name}'",
        }

    return _serve


async def _no_mcp() -> str:
    return ""


@contextlib.contextmanager
def _patched_cluster(scenario: Scenario, trace: Trace):
    """Neutralise every seam in the agent loop that would reach a live cluster."""
    from app.services.mcp_client_service import mcp_client_service
    from app.services.topology_service import topology_service
    from app.services.ai_service import AIService

    async def _no_prereqs(_self):
        return [], frozenset(), ""

    async def _presweep(_ns, query=""):
        return scenario.presweep

    async def _resolve_ns(_text, strict=False):
        return scenario.namespace

    async def _no_ext_rag(_query):
        return ""

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("app.tools.registry.execute_tool_async",
                                  _fixture_server(scenario, trace)))
        stack.enter_context(patch.object(AIService, "_run_prerequisite_check", _no_prereqs))
        stack.enter_context(patch("app.services.presweep.build_presweep", _presweep))
        stack.enter_context(patch("app.services.presweep.resolve_namespace", _resolve_ns))
        stack.enter_context(patch.object(topology_service, "get_cluster_overview",
                                         lambda _ctx: scenario.topology))
        stack.enter_context(patch.object(mcp_client_service, "get_all_tools_for_prompt",
                                         _no_mcp))
        stack.enter_context(patch("app.services.external_rag_service."
                                  "external_rag_service.retrieve_all", _no_ext_rag))
        yield


async def run_scenario(scenario: Scenario) -> Trace:
    """Run one scenario end to end. Never raises — a blown run is a failed run."""
    from app.services.ai_service import ai_service

    trace = Trace()
    try:
        with _patched_cluster(scenario, trace):
            async for event in ai_service.run_global_agentic_loop(
                query=scenario.query,
                history=list(scenario.history) or None,
            ):
                if event.get("type") == "result":
                    trace.answer = event.get("message") or ""
    except Exception as exc:  # a provider error is a data point, not a crash
        trace.error = f"{type(exc).__name__}: {exc}"
    return trace
