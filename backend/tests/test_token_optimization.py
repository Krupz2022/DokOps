import pytest
import asyncio
from unittest.mock import MagicMock, patch
from app.services.cached_ai_client import trim_messages
from app.services.ai_service import (
    build_agent_system_prompt,
    _AGENT_CORE_SYSTEM,
    _GLOBAL_AGENT_STATIC_SYSTEM,
    _FRAG_SERVICE_TOOLS,
    _FRAG_MINION,
    _FRAG_IMAGE_PULL,
    _FRAG_DEPLOY,
    _INVESTIGATION_PROTOCOL,
)


def _make_messages():
    """Build a 7-message conversation with 3 tool result turns."""
    return [
        {"role": "system", "content": "you are a k8s agent"},
        {"role": "user", "content": "what's wrong with nginx?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc1", "type": "function",
                            "function": {"name": "get_logs", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "A" * 2000},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc2", "type": "function",
                            "function": {"name": "get_events", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "tc2", "content": "B" * 2000},
        {"role": "assistant", "content": "Found the root cause."},
    ]


def test_trim_keeps_system_and_all_assistant_messages():
    msgs = _make_messages()
    result = trim_messages(msgs, keep_tool_results=1, token_cap=99999)
    assert result[0]["content"] == "you are a k8s agent"
    assert result[2]["content"] is None   # assistant tool_calls kept
    assert result[4]["content"] is None   # assistant tool_calls kept
    assert result[6]["content"] == "Found the root cause."


def test_trim_summarizes_oldest_tool_result_beyond_keep_window():
    msgs = _make_messages()
    result = trim_messages(msgs, keep_tool_results=1, token_cap=99999)
    # tc1 is beyond keep window — should be summarized
    assert result[3]["content"].startswith("[trimmed]")
    assert "tc1" in result[3]["content"]
    # tc2 is inside keep window — full content preserved
    assert result[5]["content"] == "B" * 2000


def test_trim_keeps_all_when_within_window():
    msgs = _make_messages()
    result = trim_messages(msgs, keep_tool_results=5, token_cap=99999)
    assert result[3]["content"] == "A" * 2000
    assert result[5]["content"] == "B" * 2000


def test_trim_hard_cap_drops_tool_results():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "tc1", "content": "X" * 10000},
        {"role": "tool", "tool_call_id": "tc2", "content": "Y" * 10000},
    ]
    # token_cap=10 means char_limit=40 — well below both tool results
    result = trim_messages(msgs, keep_tool_results=5, token_cap=10)
    assert result[0]["content"] == "sys"
    assert result[1]["content"] == "[dropped]"


def test_trim_does_not_modify_original_list():
    msgs = _make_messages()
    original_content = msgs[3]["content"]
    result = trim_messages(msgs, keep_tool_results=0, token_cap=99999)
    # Original list is not mutated
    assert msgs[3]["content"] == original_content
    # All tool results summarized when keep_tool_results=0
    assert result[3]["content"].startswith("[trimmed]")
    assert result[5]["content"].startswith("[trimmed]")


from app.services.cached_ai_client import CachingAIClient


def _openai_response(content: str = "hello", tool_calls=None):
    """Build a minimal mock OpenAI SDK v1.x completion response for testing."""
    msg = MagicMock()
    msg.tool_calls = tool_calls
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_caching_client_uses_fast_model_for_fast_tier():
    full_client = MagicMock()
    fast_client = MagicMock()
    fast_client.chat.completions.create.return_value = _openai_response("fast response")

    cac = CachingAIClient(
        provider="OPENAI",
        client=full_client,
        model="gpt-4o",
        fast_model="gpt-4o-mini",
        fast_client=fast_client,
        tiering_enabled=True,
    )
    text, tool_calls = asyncio.run(
        cac.complete([{"role": "user", "content": "hi"}], [], tier="fast", disable_trimming=True)
    )
    assert text == "fast response"
    assert tool_calls is None
    fast_client.chat.completions.create.assert_called_once()
    call_kwargs = fast_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4o-mini"
    full_client.chat.completions.create.assert_not_called()


def test_caching_client_falls_back_to_full_model_on_fast_failure():
    full_client = MagicMock()
    fast_client = MagicMock()
    fast_client.chat.completions.create.side_effect = Exception("model not found")
    full_client.chat.completions.create.return_value = _openai_response("full response")

    cac = CachingAIClient(
        provider="OPENAI",
        client=full_client,
        model="gpt-4o",
        fast_model="gpt-4o-mini",
        fast_client=fast_client,
        tiering_enabled=True,
    )
    text, _ = asyncio.run(
        cac.complete([{"role": "user", "content": "hi"}], [], tier="fast", disable_trimming=True)
    )
    assert text == "full response"
    full_client.chat.completions.create.assert_called_once()


def test_caching_client_uses_full_model_when_tiering_disabled():
    full_client = MagicMock()
    fast_client = MagicMock()
    full_client.chat.completions.create.return_value = _openai_response("full")

    cac = CachingAIClient(
        provider="OPENAI",
        client=full_client,
        model="gpt-4o",
        fast_model="gpt-4o-mini",
        fast_client=fast_client,
        tiering_enabled=False,
    )
    asyncio.run(
        cac.complete([{"role": "user", "content": "hi"}], [], tier="fast", disable_trimming=True)
    )
    full_client.chat.completions.create.assert_called_once()
    fast_client.chat.completions.create.assert_not_called()


def test_caching_client_calls_trim_messages_by_default():
    """trim_messages should run when disable_trimming=False and there are old tool results."""
    client = MagicMock()
    client.chat.completions.create.return_value = _openai_response("ok")

    cac = CachingAIClient(
        provider="OPENAI", client=client, model="gpt-4o", tiering_enabled=False
    )
    long_messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "tc1", "content": "A" * 100000},
        {"role": "tool", "tool_call_id": "tc2", "content": "B" * 100000},
        {"role": "user", "content": "query"},
    ]
    asyncio.run(
        cac.complete(long_messages, [], tier="full", disable_trimming=False,
                     trim_keep=1, trim_token_cap=500)
    )
    # The messages passed to the client should have been trimmed
    sent = client.chat.completions.create.call_args[1]["messages"]
    # tc1 should be trimmed (only keep 1 tool result), tc2 kept full
    assert sent[1]["content"].startswith("[trimmed]") or sent[1]["content"] == "[dropped]"


def _otool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": "",
            "parameters": {"type": "object", "properties": {}, "required": []}}}


def test_core_prompt_is_smaller_than_full():
    assert len(_AGENT_CORE_SYSTEM) < len(_GLOBAL_AGENT_STATIC_SYSTEM)


def test_image_pull_protocol_is_always_on_in_core():
    # Discovery-triggered (ImagePullBackOff appears in tool results, not the query),
    # so it must live in core and never be gated out.
    assert _FRAG_IMAGE_PULL in _AGENT_CORE_SYSTEM


def test_k8s_only_query_omits_service_and_minion_fragments():
    tools = [_otool("get_cluster_health"), _otool("search_pods")]
    prompt = build_agent_system_prompt(investigation=False, selected_tools=tools)
    assert _FRAG_SERVICE_TOOLS not in prompt
    assert _FRAG_MINION not in prompt
    assert _INVESTIGATION_PROTOCOL not in prompt
    assert prompt.startswith(_AGENT_CORE_SYSTEM)


def test_service_tools_selected_includes_service_fragment():
    tools = [_otool("get_cluster_health"), _otool("rabbitmq_list_queues")]
    prompt = build_agent_system_prompt(investigation=False, selected_tools=tools)
    assert _FRAG_SERVICE_TOOLS in prompt


def test_registry_tools_selected_includes_service_fragment():
    tools = [_otool("get_cluster_health"), _otool("registry_list_tags")]
    prompt = build_agent_system_prompt(investigation=False, selected_tools=tools)
    assert _FRAG_SERVICE_TOOLS in prompt


def test_minion_tools_selected_includes_minion_fragment():
    tools = [_otool("minion_list"), _otool("minion_exec_read")]
    prompt = build_agent_system_prompt(investigation=False, selected_tools=tools)
    assert _FRAG_MINION in prompt


def test_investigation_flag_appends_protocol():
    prompt = build_agent_system_prompt(investigation=True, selected_tools=[])
    assert _INVESTIGATION_PROTOCOL in prompt


def test_gemini_schema_shape_is_supported():
    gem = [{"function_declarations": [{"name": "redis_info"}]}]
    prompt = build_agent_system_prompt(investigation=False, selected_tools=gem)
    assert _FRAG_SERVICE_TOOLS in prompt


def test_full_constant_still_contains_all_fragments():
    # Backward-compat: pod/batch loops rely on the full constant
    assert _FRAG_SERVICE_TOOLS in _GLOBAL_AGENT_STATIC_SYSTEM
    assert _FRAG_MINION in _GLOBAL_AGENT_STATIC_SYSTEM
    assert _FRAG_IMAGE_PULL in _GLOBAL_AGENT_STATIC_SYSTEM
    assert _FRAG_DEPLOY in _GLOBAL_AGENT_STATIC_SYSTEM


def test_detect_intent_uses_fast_model_when_tiering_enabled(monkeypatch):
    """detect_intent should call the fast model when AI_TIERING_ENABLED=True."""
    from app.services.ai_service import AIService

    called_with_models = []

    def fake_get_setting(self, key):
        return {
            "ai_provider": "OPENAI",
            "ai_model": "gpt-4o",
            "ai_fast_model": "gpt-4o-mini",
            "ai_fast_base_url": None,
            "ai_fast_api_key": None,
        }.get(key)

    def fake_get_client(self, config_override=None):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = '{"type": "chat"}'
        mock_client.chat.completions.create.side_effect = (
            lambda **kw: (called_with_models.append(kw.get("model")), mock_resp)[1]
        )
        return mock_client

    with patch.object(AIService, "_get_setting", fake_get_setting), \
         patch.object(AIService, "_get_client", fake_get_client), \
         patch("app.services.ai_service.settings") as mock_settings:
        mock_settings.AI_TIERING_ENABLED = True
        svc = AIService()
        svc.detect_intent("what's wrong?", {})

    assert "gpt-4o-mini" in called_with_models
