import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.asyncio


async def _discover(ai_reply: str):
    from app.services import agent_executor_service as svc
    fake_ai = MagicMock()
    fake_ai.simple_completion.return_value = ai_reply
    with patch("app.services.ai_service.ai_service", fake_ai):
        return [t["name"] for t in await svc.discover_tools_for_goal("watch test-ns")]


async def test_enumerator_added_when_picker_omits_it():
    """The real failure: picker returns only name-keyed tools, agent can't find names."""
    names = await _discover('["get_pod_status", "get_pod_logs"]')
    assert "search_pods" in names


async def test_no_duplicate_when_picker_already_chose_it():
    names = await _discover('["search_pods", "get_pod_logs"]')
    assert names.count("search_pods") == 1
