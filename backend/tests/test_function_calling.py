import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace


# ── Schema builder tests ──────────────────────────────────────────────────────

def test_build_openai_tools_schema_structure():
    from app.tools.registry import build_openai_tools_schema
    schema = build_openai_tools_schema()
    assert isinstance(schema, list)
    assert len(schema) > 0
    first = schema[0]
    assert first["type"] == "function"
    assert "name" in first["function"]
    assert "description" in first["function"]
    assert first["function"]["parameters"]["type"] == "object"
    assert "properties" in first["function"]["parameters"]
    assert first["function"]["parameters"]["required"] == []


def test_build_openai_tools_schema_known_tool():
    from app.tools.registry import build_openai_tools_schema
    schema = build_openai_tools_schema()
    names = [t["function"]["name"] for t in schema]
    assert "get_pod_logs" in names
    tool = next(t for t in schema if t["function"]["name"] == "get_pod_logs")
    props = tool["function"]["parameters"]["properties"]
    assert "pod_name" in props
    assert props["pod_name"]["type"] == "string"


def test_build_openai_tools_schema_extra_tools():
    from app.tools.registry import build_openai_tools_schema
    extra = [{"name": "my_custom_tool", "description": "Does something custom"}]
    schema = build_openai_tools_schema(extra_tools=extra)
    names = [t["function"]["name"] for t in schema]
    assert "my_custom_tool" in names
    custom = next(t for t in schema if t["function"]["name"] == "my_custom_tool")
    assert custom["function"]["description"] == "Does something custom"
    assert custom["function"]["parameters"]["properties"] == {}


def test_build_gemini_tools_schema_structure():
    from app.tools.registry import build_gemini_tools_schema
    schema = build_gemini_tools_schema()
    assert isinstance(schema, list)
    assert len(schema) == 1
    assert "function_declarations" in schema[0]
    decls = schema[0]["function_declarations"]
    assert isinstance(decls, list)
    assert len(decls) > 0


def test_build_gemini_tools_schema_known_tool():
    from app.tools.registry import build_gemini_tools_schema
    schema = build_gemini_tools_schema()
    decls = schema[0]["function_declarations"]
    names = [d["name"] for d in decls]
    assert "get_pod_logs" in names
    tool = next(d for d in decls if d["name"] == "get_pod_logs")
    props = tool["parameters"]["properties"]
    assert "pod_name" in props
    assert props["pod_name"]["type"] == "STRING"


def test_build_gemini_tools_schema_extra_tools():
    from app.tools.registry import build_gemini_tools_schema
    extra = [{"name": "my_custom_tool", "description": "Does something"}]
    schema = build_gemini_tools_schema(extra_tools=extra)
    decls = schema[0]["function_declarations"]
    names = [d["name"] for d in decls]
    assert "my_custom_tool" in names


# ── _call_model tests ─────────────────────────────────────────────────────────

def _make_openai_text_response(text: str):
    """Build a minimal mock OpenAI completion response with text only."""
    msg = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


def _make_openai_tool_response(tool_name: str, arguments: dict):
    """Build a minimal mock OpenAI completion response with a tool call."""
    import json
    tc = SimpleNamespace(
        id="call_abc123",
        function=SimpleNamespace(name=tool_name, arguments=json.dumps(arguments)),
    )
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


async def test_call_model_openai_returns_text():
    from app.services.ai_service import AIService
    svc = AIService.__new__(AIService)
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_openai_text_response("Here is my answer.")
    text, tool_calls = await svc._call_model(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        provider="OPENAI",
        client=mock_client,
        model="gpt-4o",
    )
    assert text == "Here is my answer."
    assert tool_calls is None


async def test_call_model_openai_returns_tool_calls():
    from app.services.ai_service import AIService
    svc = AIService.__new__(AIService)
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_openai_tool_response(
        "get_pod_logs", {"pod_name": "api-pod"}
    )
    text, tool_calls = await svc._call_model(
        messages=[{"role": "user", "content": "check logs"}],
        tools=[{"type": "function", "function": {"name": "get_pod_logs", "parameters": {}}}],
        provider="OPENAI",
        client=mock_client,
        model="gpt-4o",
    )
    assert text is None
    assert tool_calls is not None
    assert len(tool_calls) == 1
    assert tool_calls[0].function.name == "get_pod_logs"


async def test_call_model_custom_falls_back_when_tools_unsupported():
    """When the model raises an error containing 'tool', retry without tools."""
    from app.services.ai_service import AIService
    svc = AIService.__new__(AIService)
    mock_client = MagicMock()

    def raise_on_tools(**kwargs):
        if "tools" in kwargs:
            raise Exception("This model does not support tool calls")
        return _make_openai_text_response("Fallback answer.")

    mock_client.chat.completions.create.side_effect = raise_on_tools

    text, tool_calls = await svc._call_model(
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "get_pod_logs", "parameters": {}}}],
        provider="CUSTOM",
        client=mock_client,
        model="llama3",
    )
    assert text == "Fallback answer."
    assert tool_calls is None
    # Should have been called twice: once with tools (fails), once without
    assert mock_client.chat.completions.create.call_count == 2


# ── Loop refactor tests ───────────────────────────────────────────────────────

async def test_global_loop_executes_tool_and_returns_result():
    """Loop calls a tool, feeds result back, then returns final text answer."""
    import json
    from app.services.ai_service import AIService

    svc = AIService.__new__(AIService)

    call_count = 0
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="get_cluster_health", arguments="{}"),
    )

    async def mock_call_model(messages, tools, provider, client, model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None, [tool_call]   # first turn: call a tool
        return "Cluster is healthy.", None  # second turn: final answer

    svc._call_model = mock_call_model
    svc._get_client = MagicMock(return_value=MagicMock())
    svc._get_setting = MagicMock(side_effect=lambda k: {
        "ai_provider": "OPENAI", "ai_model": "gpt-4o",
        "rag_enabled": "false",
    }.get(k))
    svc._get_custom_tools_definitions = MagicMock(return_value=[])

    async def _mock_complete(msgs, tools, **kw):
        return await mock_call_model(msgs, tools, "OPENAI", None, "gpt-4o")

    mock_caching_client = MagicMock()
    mock_caching_client.complete = _mock_complete
    svc._get_caching_client = MagicMock(return_value=mock_caching_client)

    mock_tool_result = {"success": True, "data": "All nodes ready.", "error": None}

    with patch("app.tools.registry.execute_tool_async", new=AsyncMock(return_value=mock_tool_result)), \
         patch("app.tools.registry.TOOL_REGISTRY", {"get_cluster_health": {
             "function": MagicMock(), "description": "health", "inputs": [],
             "operation_type": "read", "requires_confirmation": False,
         }}), \
         patch("app.tools.registry.build_openai_tools_schema", return_value=[]), \
         patch("app.services.mcp_client_service.mcp_client_service.get_all_tools_for_prompt", return_value=""):
        events = [e async for e in svc.run_global_agentic_loop("Is the cluster healthy?")]

    result_events = [e for e in events if e["type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["message"] == "Cluster is healthy."
    assert call_count == 2


async def test_pod_loop_executes_tool_and_returns_result():
    """Pod loop calls get_logs tool then returns final answer."""
    import json
    from app.services.ai_service import AIService

    svc = AIService.__new__(AIService)

    call_count = 0
    tool_call = SimpleNamespace(
        id="call_pod_1",
        function=SimpleNamespace(name="get_logs", arguments='{"pod_name": "api-pod"}'),
    )

    async def mock_call_model(messages, tools, provider, client, model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None, [tool_call]
        return "Pod is OOMKilled. Increase memory limit.", None

    svc._call_model = mock_call_model
    svc._get_client = MagicMock(return_value=MagicMock())
    svc._get_setting = MagicMock(side_effect=lambda k: {
        "ai_provider": "OPENAI", "ai_model": "gpt-4o",
    }.get(k))
    svc._get_custom_tools_definitions = MagicMock(return_value=[])

    async def _mock_complete_pod(msgs, tools, **kw):
        return await mock_call_model(msgs, tools, "OPENAI", None, "gpt-4o")

    mock_caching_client = MagicMock()
    mock_caching_client.complete = _mock_complete_pod
    svc._get_caching_client = MagicMock(return_value=mock_caching_client)

    mock_logs = "Error: OOMKilled - container exceeded memory limit"

    with patch("app.tools.registry.build_openai_tools_schema", return_value=[]), \
         patch("app.services.k8s_service.k8s_service.get_pod_logs", new=AsyncMock(return_value=mock_logs)):
        events = [e async for e in svc.run_agentic_loop("default", "api-pod", "Why is this pod crashing?")]

    result_events = [e for e in events if e["type"] == "result"]
    assert len(result_events) == 1
    assert "OOMKilled" in result_events[0]["message"]


async def test_batch_loop_executes_tool_and_returns_result():
    """Batch loop calls a tool for a pod then returns final answer."""
    import json
    from app.services.ai_service import AIService

    svc = AIService.__new__(AIService)

    call_count = 0
    tool_call = SimpleNamespace(
        id="call_batch_1",
        function=SimpleNamespace(
            name="get_pod_logs",
            arguments='{"namespace": "default", "pod_name": "api-pod"}',
        ),
    )

    async def mock_call_model(messages, tools, provider, client, model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None, [tool_call]
        return "Both pods have OOMKilled errors.", None

    svc._call_model = mock_call_model
    svc._get_client = MagicMock(return_value=MagicMock())
    svc._get_setting = MagicMock(side_effect=lambda k: {
        "ai_provider": "OPENAI", "ai_model": "gpt-4o",
    }.get(k))
    svc._get_custom_tools_definitions = MagicMock(return_value=[])

    async def _mock_complete_batch(msgs, tools, **kw):
        return await mock_call_model(msgs, tools, "OPENAI", None, "gpt-4o")

    mock_caching_client = MagicMock()
    mock_caching_client.complete = _mock_complete_batch
    svc._get_caching_client = MagicMock(return_value=mock_caching_client)

    pods = [{"namespace": "default", "pod_name": "api-pod"}]
    mock_logs = {"success": True, "data": "OOMKilled", "error": None}

    with patch("app.tools.registry.execute_tool_async", new=AsyncMock(return_value=mock_logs)), \
         patch("app.tools.registry.build_openai_tools_schema", return_value=[]):
        events = [e async for e in svc.run_batch_agentic_loop(pods, "Why are pods crashing?")]

    result_events = [e for e in events if e["type"] == "result"]
    assert len(result_events) == 1
    assert "OOMKilled" in result_events[0]["message"]
