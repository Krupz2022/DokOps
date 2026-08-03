"""Regression guard for the wrong-tool-routing bug fixed on 2026-08-03.

Commit 78fb39f ("perf(ai): split agent system prompt into core + conditional
fragments", 2026-06-18) moved SERVICE TOOL RULE and MINION RULE out of the
always-on system prompt into fragments gated on a literal keyword match
against AIService._SERVICE_TOOL_MAP. Clients phrase questions obliquely
("the database is slow", "what's wrong with node-7") rather than naming a
product ("postgres", "minion") or namespace-style hostname, so the gate
never fires — the model loses both the service/minion tools AND the
instruction that they exist, and falls back to Kubernetes tools.

The fix keeps the two fragments gated (that split is intentional prompt-cost
work, not being reverted) and adds a short always-on pointer to the `base`
policy section naming the non-Kubernetes tool families and instructing the
model to call discover_tools rather than substitute Kubernetes tools.

This test exercises the real selection path end to end for all eight
oblique phrasings measured during triage: the real _select_dynamic_tools
against the real registry schema, then the real build_agent_system_prompt --
exactly what test_phase_1_5_tools_are_actually_offered_to_the_model in
test_agent_prompt_assembly.py does for the endpoints-sweep regression. This
is what would have caught the 78fb39f regression in June.
"""
import pytest

from app.services.ai_service import AIService, build_agent_system_prompt
from app.tools import registry

# The eight phrasings measured in triage: none contain a _SERVICE_TOOL_MAP
# keyword (postgres/redis/rabbitmq/mongo/.../minion/on-prem/edge/device), so
# none trip the gate that would pull in SERVICE TOOL RULE or MINION RULE.
OBLIQUE_PHRASINGS = [
    "the database is slow",
    "why can't the app reach its datastore",
    "the broker is dropping messages",
    "our message bus is backed up",
    "check the key-value store memory",
    "connections are exhausted on the db",
    "what's wrong with node-7",
    "the appliance in the DC is offline",
]

_POINTER_PHRASE = "call discover_tools before answering"


@pytest.mark.parametrize("query", OBLIQUE_PHRASINGS)
def test_oblique_phrasing_still_gets_the_tool_discovery_pointer(query):
    """Every oblique phrasing must see the always-on pointer even though the
    SERVICE TOOL RULE / MINION RULE fragments stay correctly gated off."""
    full_k8s_schema = registry.build_openai_tools_schema()
    selected = AIService._select_dynamic_tools(
        query=query,
        obs_tools_schema=[],
        full_k8s_schema=full_k8s_schema,
        mcp_schema=[],
        custom_tools_schema=[],
    )
    prompt = build_agent_system_prompt(investigation=False, selected_tools=selected)

    assert _POINTER_PHRASE in prompt, (
        f"query {query!r}: always-on TOOL DISCOVERY RULE pointer missing from the "
        "assembled prompt -- the model has no way to learn non-Kubernetes tools exist"
    )
    # discover_tools must actually be callable for the pointer's instruction
    # to be genuine, not just words -- confirms the escape hatch this pointer
    # relies on (always appended in _select_dynamic_tools) is really there.
    selected_names = {t["function"]["name"] for t in selected}
    assert "discover_tools" in selected_names, (
        f"query {query!r}: prompt tells the model to call discover_tools but "
        "discover_tools is not in its tool schema"
    )


def test_pointer_names_every_non_kubernetes_tool_family():
    """The pointer must name every backend-service family and minion nodes,
    or a family absent from it repeats the exact same failure for its own
    oblique phrasing (e.g. adding a new integration without updating this
    line silently reintroduces the regression for that family)."""
    prompt = build_agent_system_prompt(investigation=False, selected_tools=[])
    for family in (
        "RabbitMQ", "Redis", "PostgreSQL", "MySQL", "MariaDB",
        "MongoDB", "CouchDB", "MSSQL", "container registries",
        "on-premise minion nodes",
    ):
        assert family in prompt, f"{family!r} not named in the always-on tool discovery pointer"


def test_pointer_is_present_regardless_of_gated_fragments():
    """The pointer belongs to the always-on `base` section, so it must survive
    both investigation mode and a full tool schema that trips every gate --
    it is not itself conditionally included."""
    schema = registry.build_openai_tools_schema()
    for investigation in (False, True):
        for selected_tools in ([], schema):
            prompt = build_agent_system_prompt(investigation=investigation, selected_tools=selected_tools)
            assert _POINTER_PHRASE in prompt


def test_pointer_does_not_restate_gated_fragment_content():
    """The pointer must stay short -- it should not duplicate the per-service
    startup-tool guidance that already lives in the gated SERVICE TOOL RULE
    fragment (that content is intentionally NOT always-on, for token cost)."""
    prompt = build_agent_system_prompt(investigation=False, selected_tools=[])
    pointer_start = prompt.index("TOOL DISCOVERY RULE")
    # The pointer is one paragraph in the `base` section; the blank line
    # after it ends the paragraph regardless of which gated fragments follow.
    paragraph_end = prompt.index("\n\n", pointer_start)
    pointer_text = prompt[pointer_start:paragraph_end]
    assert len(pointer_text) < 700, (
        f"TOOL DISCOVERY RULE pointer is {len(pointer_text)} chars -- expected a short "
        "few-line pointer, not a restatement of the gated fragment's content"
    )
