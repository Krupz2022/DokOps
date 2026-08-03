"""The policy file must reproduce the pre-extraction prompt byte for byte.

The policy text moved from string constants in ai_service.py into
app/prompts/dokops.md. These snapshots were captured from the constants before
the move, so any drift means the extraction changed what the model is told.
"""
import pathlib

import pytest

from app.services.ai_service import build_agent_system_prompt, _FINAL_REVIEW_PROMPT
from app.tools import registry

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "policy_golden"

# Anchor ids ai_service requests from the policy file. Kept here rather than
# imported so a rename in the loader cannot silently satisfy its own test.
EXPECTED_ANCHORS = {
    "base", "service_tools", "image_pull", "minion",
    "deploy", "health_followup", "investigation", "final_review",
}


def _cases():
    schema = registry.build_openai_tools_schema()
    return {
        "normal_no_frags": dict(investigation=False, selected_tools=[]),
        "investigation_no_frags": dict(investigation=True, selected_tools=[]),
        "normal_all_frags": dict(investigation=False, selected_tools=schema),
        "investigation_all_frags": dict(investigation=True, selected_tools=schema),
    }


@pytest.mark.parametrize("name", list(_cases()))
def test_assembled_prompt_matches_pre_extraction_golden(name):
    expected = (GOLDEN / f"{name}.txt").read_text(encoding="utf-8")
    actual = build_agent_system_prompt(**_cases()[name])
    assert actual == expected, f"{name}: policy text drifted during extraction"


def test_final_review_prompt_matches_golden():
    expected = (GOLDEN / "final_review.txt").read_text(encoding="utf-8")
    assert _FINAL_REVIEW_PROMPT == expected


def test_every_requested_anchor_exists_in_the_file():
    from app.prompts import POLICY
    missing = EXPECTED_ANCHORS - set(POLICY)
    assert not missing, f"dokops.md is missing anchors: {sorted(missing)}"


def test_no_policy_section_is_empty():
    """A mistyped anchor splits into an empty section and silently drops a rule."""
    from app.prompts import POLICY
    empty = [k for k, v in POLICY.items() if not v.strip()]
    assert not empty, f"empty policy sections: {empty}"
