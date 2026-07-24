# backend/tests/test_action_gate.py
from unittest.mock import AsyncMock, MagicMock, patch


async def test_fix_queries_floor_to_investigate():
    """'fix' phrasing must never classify simple, even if the LLM says SIMPLE."""
    from app.services.ai_service import ai_service

    caching_client = MagicMock()
    caching_client.complete = AsyncMock(return_value=("SIMPLE", None))
    assert await ai_service.classify_complexity("ok can u please fix this ?", caching_client) == "investigate"
    # Genuinely simple queries still classify simple
    assert await ai_service.classify_complexity("list pods in default", caching_client) == "simple"


async def test_action_gate_forces_second_attempt():
    """A write-intent turn ending in prose gets exactly one forced retry."""
    from app.services.ai_service import AIService

    svc = AIService.__new__(AIService)
    svc._get_client = MagicMock(return_value=MagicMock())
    svc._get_setting = MagicMock(side_effect=lambda k: {
        "ai_provider": "OPENAI", "ai_model": "gpt-4o", "rag_enabled": "false",
    }.get(k))
    svc._get_custom_tools_definitions = MagicMock(return_value=[])
    svc._run_prerequisite_check = AsyncMock(return_value=([], [], ""))
    svc.classify_complexity = AsyncMock(return_value="investigate")
    # No tool evidence this turn -> review is skipped; result passes through.
    svc._run_final_review = AsyncMock(return_value={"answer": "unused"})

    loop_calls: list = []

    async def fake_complete(messages, tools, **kw):
        loop_calls.append([dict(m) for m in messages])
        if len(loop_calls) == 1:
            return "I recommend changing the port to 8500.", None
        return "Blocked: the correct Consul port is unverified — need get_service output.", None

    caching_client = MagicMock()
    caching_client.complete = fake_complete
    caching_client.full_model = "gpt-4o"
    svc._get_caching_client = MagicMock(return_value=caching_client)

    with patch("app.tools.registry.build_openai_tools_schema", return_value=[]):
        events = [e async for e in svc.run_global_agentic_loop("ok can u please fix this ?")]

    # Gate fired: two loop completions, second saw the forced-action instruction
    assert len(loop_calls) == 2
    gate_texts = [m["content"] for m in loop_calls[1] if m.get("role") == "user"]
    assert any("TAKE AN ACTION" in (t or "") for t in gate_texts)

    results = [e for e in events if e["type"] == "result"]
    assert len(results) == 1
    assert results[0]["message"].startswith("Blocked:")


async def test_action_gate_fires_only_once():
    """The gate must not loop forever when the model keeps answering in prose."""
    from app.services.ai_service import AIService

    svc = AIService.__new__(AIService)
    svc._get_client = MagicMock(return_value=MagicMock())
    svc._get_setting = MagicMock(side_effect=lambda k: {
        "ai_provider": "OPENAI", "ai_model": "gpt-4o", "rag_enabled": "false",
    }.get(k))
    svc._get_custom_tools_definitions = MagicMock(return_value=[])
    svc._run_prerequisite_check = AsyncMock(return_value=([], [], ""))
    svc.classify_complexity = AsyncMock(return_value="investigate")
    svc._run_final_review = AsyncMock(return_value={"answer": "unused"})

    calls = {"n": 0}

    async def fake_complete(messages, tools, **kw):
        calls["n"] += 1
        return "Still just prose.", None

    caching_client = MagicMock()
    caching_client.complete = fake_complete
    caching_client.full_model = "gpt-4o"
    svc._get_caching_client = MagicMock(return_value=caching_client)

    with patch("app.tools.registry.build_openai_tools_schema", return_value=[]):
        events = [e async for e in svc.run_global_agentic_loop("please fix the deployment")]

    assert calls["n"] == 2  # initial + one gated retry, then done
    assert len([e for e in events if e["type"] == "result"]) == 1
