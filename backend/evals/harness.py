"""Runs the real agent loop against canned cluster fixtures.

The LLM is real — every failure mode these evals exist to catch is model
behaviour, so a stubbed model would pass while the product stayed broken.
Everything that would otherwise reach a live cluster, a live integration, or
the network is patched to serve the scenario instead, so the cluster half of
the run is fully deterministic.

`_run_global_agentic_loop_inner` dispatches a model-requested tool call
through one of four branches, and only the last of them goes through the
`app.tools.registry` module used by ordinary Kubernetes tools:

  1. RAG tools             (`app.tools.registry.execute_rag_tool`, gated on
                            the `rag_enabled` DB setting — currently false,
                            not patched here; see task-2-report.md)
  2. `mcp__`-prefixed tools (`mcp_client_service.execute_tool` -> real
                            HTTP/SSE/stdio transports)
  3. observability-registry tools (closures bound to real Prometheus/Loki/
                            Grafana/Elasticsearch/Datadog `base_url`s, called
                            directly — no registry function in between)
  4. `TOOL_REGISTRY` tools  (`app.tools.registry.execute_tool_async` — the
                            k8s tool seam this harness fixtures)

Branches 2 and 3 do not go anywhere near a fixture unless independently
patched, so every seam that can put a real network call or a five-minute
`asyncio.wait_for` UI-approval timeout onto the eval path is listed in
`SEAMS` below and patched in `_patched_cluster`.
"""
import contextlib
import importlib
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
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


async def _no_prereqs(_self) -> Tuple[list, frozenset, str]:
    return [], frozenset(), ""


def _presweep_factory(scenario: Scenario, _trace: Trace):
    async def _presweep(_ns, query: str = "") -> str:
        return scenario.presweep

    return _presweep


def _resolve_ns_factory(scenario: Scenario, _trace: Trace):
    async def _resolve_ns(_text, strict: bool = False) -> Optional[str]:
        return scenario.namespace

    return _resolve_ns


def _topology_factory(scenario: Scenario, _trace: Trace):
    return lambda _ctx: scenario.topology


async def _no_mcp_prompt() -> str:
    return ""


async def _no_ext_rag(_query: str) -> str:
    return ""


async def _no_mcp_tools_schema() -> list:
    """Empty the MCP tool schema seen by the model. Patched in for both
    provider branches (`build_openai_tools_schema` and
    `build_gemini_tools_schema` take no args and both return a list)."""
    return []


async def _no_mcp_execute(tool_name: str, inputs: dict, confirmed: bool = False) -> Dict[str, Any]:
    """Belt-and-suspenders: even though the MCP schema is emptied so the model
    should never request an mcp__ tool, if one is requested anyway this must
    not reach `_call_http`/`_call_sse`/`_call_stdio` — and, critically, must
    never return `requires_confirmation`, which would otherwise make the loop
    `await asyncio.wait_for(..., timeout=300)` for a UI approval that will
    never arrive."""
    return {
        "success": False,
        "data": None,
        "error": f"eval: MCP tools are disabled in the harness (blocked call to '{tool_name}')",
        "source": "mcp",
    }


def _no_obs_registry() -> Dict[str, Any]:
    """Observability tool closures are bound to real integration base_urls and
    called directly by the dispatch loop (no registry function in between),
    so the only seam that stops a real Prometheus/Loki/Grafana/Elasticsearch/
    Datadog call is emptying the registry itself before it's built."""
    return {}


async def _no_internal_rag(query: str, collection_name: str, n_results: int = 3) -> str:
    """The knowledge-base RAG context injection ai_service runs before the
    tool loop even starts. Gated on the `rag_enabled` DB setting, which is
    false in this environment today — patched anyway so eval determinism
    does not depend on ambient DB state."""
    return ""


# Single source of truth for every seam that must be neutralised before the
# real agent loop can run against canned fixtures instead of a live cluster.
# Both `_patched_cluster` (applies the patches) and
# `test_evals_harness.py::test_all_seam_targets_still_resolve` (a
# rename-detector — asserts every target still exists) iterate this list, so
# the two cannot silently drift apart.
#
# Each entry is (dotted_path, factory); factory(scenario, trace) returns the
# replacement object patched in at dotted_path. `dotted_path` is resolved the
# same way `unittest.mock.patch` resolves a string target — see
# `_resolve_seam_owner` — so class attributes, module-level functions, and
# attributes on module-level singleton instances are all valid.
SEAMS: List[Tuple[str, Callable[[Scenario, Trace], Any]]] = [
    # k8s tool dispatch (TOOL_REGISTRY branch) — the fixture-serving seam.
    ("app.tools.registry.execute_tool_async",
     lambda scenario, trace: _fixture_server(scenario, trace)),
    # Health-gate before the loop runs; also widens exposure of the obs
    # registry below if left unpatched (an empty `_unhealthy_int_names`
    # frozenset means no integration gets filtered out as unreachable).
    ("app.services.ai_service.AIService._run_prerequisite_check",
     lambda scenario, trace: _no_prereqs),
    ("app.services.presweep.build_presweep",
     lambda scenario, trace: _presweep_factory(scenario, trace)),
    ("app.services.presweep.resolve_namespace",
     lambda scenario, trace: _resolve_ns_factory(scenario, trace)),
    ("app.services.topology_service.topology_service.get_cluster_overview",
     lambda scenario, trace: _topology_factory(scenario, trace)),
    # MCP tool-listing prompt text (separate from the tool schema below).
    ("app.services.mcp_client_service.mcp_client_service.get_all_tools_for_prompt",
     lambda scenario, trace: _no_mcp_prompt),
    ("app.services.external_rag_service.external_rag_service.retrieve_all",
     lambda scenario, trace: _no_ext_rag),
    # CRITICAL: MCP tool schema — without this the model can see and request
    # mcp__ tools regardless of the execute-time stub below.
    ("app.services.mcp_client_service.mcp_client_service.build_openai_tools_schema",
     lambda scenario, trace: _no_mcp_tools_schema),
    ("app.services.mcp_client_service.mcp_client_service.build_gemini_tools_schema",
     lambda scenario, trace: _no_mcp_tools_schema),
    # CRITICAL: MCP tool execution — defence in depth if an mcp__ call is
    # made anyway; must never return requires_confirmation (300s hang risk).
    ("app.services.mcp_client_service.mcp_client_service.execute_tool",
     lambda scenario, trace: _no_mcp_execute),
    # CRITICAL: observability tool registry — closures bound to real
    # integration base_urls, called directly by the dispatch loop.
    ("app.services.integration_manager.integration_manager.get_active_tool_registry",
     lambda scenario, trace: _no_obs_registry),
    # Internal RAG context injection — latent today (rag_enabled is false
    # locally) but must not depend on that ambient DB state.
    ("app.services.rag_service.rag_service.retrieve",
     lambda scenario, trace: _no_internal_rag),
]


def _resolve_seam_owner(dotted_path: str) -> Tuple[Any, str]:
    """Resolve "pkg.mod.owner.attr" to (owner_object, attr_name) using the
    same module-then-attribute walk `unittest.mock.patch` performs on a
    string target, without depending on mock's private internals.

    Tries the longest importable module prefix first, then walks any
    remaining dotted components with getattr — this correctly resolves a
    bare module-level function, a class attribute, or an attribute on a
    module-level singleton instance, all of which appear in SEAMS.
    """
    parts = dotted_path.split(".")
    for i in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:i])
        try:
            owner: Any = importlib.import_module(module_name)
        except ImportError:
            continue
        for part in parts[i:-1]:
            owner = getattr(owner, part)
        return owner, parts[-1]
    raise ImportError(f"cannot resolve any importable module prefix for {dotted_path!r}")


@contextlib.contextmanager
def _patched_cluster(scenario: Scenario, trace: Trace):
    """Neutralise every seam in the agent loop that would reach a live cluster,
    a live integration, or the network. See SEAMS above."""
    with contextlib.ExitStack() as stack:
        for dotted_path, factory in SEAMS:
            stack.enter_context(patch(dotted_path, factory(scenario, trace)))
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
