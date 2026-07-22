"""The agent prompt must not invite a follow-up question during an investigation.

Regression: _AGENT_BASE told the model to end health responses with
'Would you like me to investigate any of these?'. That template leaked into
investigation mode, so root-cause runs stopped at the symptom and asked
permission instead of spending their step budget.
"""
from app.services.ai_service import AIService, build_agent_system_prompt
from app.tools import registry


def test_health_followup_absent_in_investigation_mode():
    prompt = build_agent_system_prompt(investigation=True, selected_tools=[])
    assert "Would you like me to investigate any of these?" not in prompt


def test_health_followup_present_in_normal_mode():
    prompt = build_agent_system_prompt(investigation=False, selected_tools=[])
    assert "Would you like me to investigate any of these?" in prompt


def test_investigation_protocol_forbids_ending_on_answerable_question():
    prompt = build_agent_system_prompt(investigation=True, selected_tools=[])
    assert "PHASE 4 — TERMINAL CONDITION" in prompt
    # Assert the prohibition itself, not just its heading — a header with an
    # empty or reworded body would otherwise pass while the rule does nothing.
    assert "Never end your turn with a question you have a tool to answer" in prompt


def test_investigation_protocol_requires_non_pod_sweep():
    """A namespace investigation must look past pod status.

    Regression: a Service whose selector typo left it with zero endpoints was
    missed twice, because discovery only enumerated pods and its pods were healthy.
    """
    prompt = build_agent_system_prompt(investigation=True, selected_tools=[])
    for tool in ("list_services", "get_endpoints", "list_deployments"):
        assert tool in prompt, f"{tool} not named in the discovery sweep"


def test_deployment_guide_does_not_fire_on_creating_a_resource():
    """Regression: asked to fix a CreateContainerConfigError "by creating what it
    needs", the agent correctly created the ConfigMap and then proposed
    create_namespace named 'notify-config' — feeding a ConfigMap's name in as a
    namespace. The DEPLOYMENT GUIDE fired on the word "create" and is always-on.
    """
    prompt = build_agent_system_prompt(investigation=False, selected_tools=[])
    assert "ONLY when the user asks to deploy or install a new APPLICATION" in prompt
    assert "never pass it the" in prompt and "name of a ConfigMap" in prompt


def test_image_pull_rule_has_diagnostic_fallback():
    """When fix_image_pull errors the user must still get a root cause.

    Regression: the rule forbids describe_pod first, so a failing fix tool left
    the user with no diagnosis whatsoever.
    """
    prompt = build_agent_system_prompt(investigation=False, selected_tools=[])
    # Both tools are named elsewhere in the base prompt, so assert the rule-6
    # phrasing that pairs them — a bare "get_pod_events" check passes regardless.
    assert "describe_pod and get_pod_events" in prompt
    assert "Never tell the user only that the fix tool failed" in prompt


# PHASE 1.5 tells the model to call these tools during namespace/cluster
# investigations to catch failures pod status alone can't show (e.g. a Service
# with a typo'd selector and zero endpoints, healthy pods notwithstanding).
_PHASE_1_5_TOOLS = ("list_services", "get_endpoints", "list_deployments")


def test_phase_1_5_tools_are_actually_offered_to_the_model():
    """A tool named in PHASE 1.5 must be present in the tool schema the model
    is actually given for an investigation-shaped query — otherwise the model
    is being told to call a tool it cannot see.

    Regression: PHASE 1.5 named list_services/get_endpoints/list_deployments,
    but none of the three were in _CORE_K8S, so they fell into the
    relevance-scored tail and were dropped from the schema for most
    investigation queries. get_endpoints — the one tool that would have caught
    the zero-endpoints Service — was absent for every representative
    investigation query tested. This exercises the real selection path
    (_select_dynamic_tools against the real registry schema), not a mock of it.
    """
    full_k8s_schema = registry.build_openai_tools_schema()
    selected = AIService._select_dynamic_tools(
        query="investigate the payments namespace, something seems broken",
        obs_tools_schema=[],
        full_k8s_schema=full_k8s_schema,
        mcp_schema=[],
        custom_tools_schema=[],
    )
    selected_names = {t["function"]["name"] for t in selected}
    missing = [name for name in _PHASE_1_5_TOOLS if name not in selected_names]
    assert not missing, f"PHASE 1.5 names tools never offered to the model: {missing}"


def test_phase_1_5_demands_endpoints_per_service():
    """Listing services must not read as satisfying the endpoint check.

    Regression: given the sweep, the agent called list_services, saw the Service
    existed, and reported it "functional with ClusterIP and port 80/TCP" — while it
    had zero endpoints. It never called get_endpoints. A confident false negative is
    worse than the silent miss it replaced.
    """
    prompt = build_agent_system_prompt(investigation=True, selected_tools=[])
    assert "call get_endpoints for EVERY Service it returned" in prompt
    # Phrase chosen to sit within one wrapped line of the constant.
    assert "functional or healthy without having seen its endpoints" in prompt


def test_evidence_gate_blocks_unexplained_crash_and_endpoints():
    """Base-prompt rules proved weaker than protocol phases in live testing.

    Regression: a DIAGNOSE RULE addition in _AGENT_BASE asking for logs after a
    diagnosis was ignored — the agent ran diagnose_pod four times and still wrote
    "investigate the logs". The same class of instruction placed in
    _INVESTIGATION_PROTOCOL was followed. These gates live in PHASE 3.
    """
    prompt = build_agent_system_prompt(investigation=True, selected_tools=[])
    assert "is not an answer — you have that tool, call it" in prompt
    assert "against the labels of the pods that should back it" in prompt


def test_diagnose_rule_demands_logs_after_diagnosis():
    """The DIAGNOSE RULE must not read as making diagnose_pod terminal.

    Regression: the rule forbade fetching logs BEFORE a diagnosis but never asked
    for them after, so the agent ran diagnose_pod three times, fetched no logs, and
    misattributed a CrashLoopBackOff to a missing readiness probe.
    """
    prompt = build_agent_system_prompt(investigation=False, selected_tools=[])
    assert "AFTER the\ndiagnosis, DO fetch them" in prompt
    assert "never blame a crash on a missing readiness probe" in prompt
