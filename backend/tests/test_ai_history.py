# backend/tests/test_ai_history.py
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.ai_service import ai_service


async def test_history_is_prepended_to_messages():
    """History messages appear between system prompt and new query in the messages list."""
    captured_messages = []

    def fake_create(**kwargs):
        captured_messages.extend(kwargs["messages"])
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Final Answer: done"
        return mock_resp

    history = [
        {"role": "user", "content": "What was the first issue?"},
        {"role": "assistant", "content": "The pod was OOMKilled."},
    ]

    with patch.object(ai_service, "_get_client") as mock_client, \
         patch.object(ai_service, "_get_setting", return_value="gpt-3.5-turbo"):
        mock_client.return_value.chat.completions.create.side_effect = fake_create
        async for _ in ai_service.run_global_agentic_loop("Follow up question", history=history):
            pass

    roles = [m["role"] for m in captured_messages]
    assert roles[0] == "system"
    assert roles[1] == "user"   # history[0]
    assert roles[2] == "assistant"  # history[1]
    assert roles[3] == "user"   # new query
