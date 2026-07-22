"""The agent prompt must not invite a follow-up question during an investigation.

Regression: _AGENT_BASE told the model to end health responses with
'Would you like me to investigate any of these?'. That template leaked into
investigation mode, so root-cause runs stopped at the symptom and asked
permission instead of spending their step budget.
"""
from app.services.ai_service import build_agent_system_prompt


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
