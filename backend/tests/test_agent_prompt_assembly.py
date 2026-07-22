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
