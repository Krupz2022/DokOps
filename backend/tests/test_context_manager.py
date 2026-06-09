import asyncio
import pytest
from unittest.mock import MagicMock
from app.services.context_manager import ContextManager, CONTEXT_WINDOWS, _CHARS_PER_TOKEN

@pytest.fixture
def ctx():
    mgr = ContextManager()
    mgr._get_setting = MagicMock(return_value=None)  # no DB in unit tests
    return mgr


def test_count_tokens_unknown_provider_uses_char_estimate(ctx):
    result = ctx.count_tokens("hello world", "UNKNOWN")
    assert result == len("hello world") // 4


def test_count_tokens_openai_uses_tiktoken_path(ctx):
    """Verify the tiktoken code path is taken for OPENAI, not the char estimate."""
    from unittest.mock import patch, MagicMock
    mock_enc = MagicMock()
    mock_enc.encode.return_value = [1, 2, 3, 4, 5]  # 5 tokens
    with patch("app.services.context_manager._get_tiktoken_enc", return_value=mock_enc):
        result = ctx.count_tokens("some text here", "OPENAI")
    assert result == 5
    mock_enc.encode.assert_called_once_with("some text here")


def test_count_tokens_unknown_provider_does_not_use_tiktoken(ctx):
    """Verify non-OPENAI/AZURE providers use char estimate, not tiktoken."""
    from unittest.mock import patch
    with patch("app.services.context_manager._get_tiktoken_enc") as mock_enc:
        result = ctx.count_tokens("hello world", "GEMINI")
    mock_enc.assert_not_called()
    assert result == len("hello world") // _CHARS_PER_TOKEN


def test_check_budget_empty_messages(ctx):
    used, limit, pct = ctx.check_budget([], "OPENAI")
    assert used == 0
    assert limit == CONTEXT_WINDOWS["OPENAI"]
    assert pct == 0.0


def test_check_budget_calculates_percentage(ctx):
    messages = [{"role": "user", "content": "a" * 4000}]  # ~1000 tokens
    used, limit, pct = ctx.check_budget(messages, "OPENAI")
    assert used > 0
    assert limit == 128_000
    assert 0.0 < pct < 1.0


def test_check_budget_unknown_provider_uses_fallback(ctx):
    messages = [{"role": "user", "content": "test"}]
    used, limit, pct = ctx.check_budget(messages, "UNKNOWN")
    assert limit == 32_000


def test_check_budget_none_content_handled(ctx):
    messages = [{"role": "tool", "content": None}]
    used, limit, pct = ctx.check_budget(messages, "OPENAI")
    assert used == 0


@pytest.fixture
def mock_caching_client():
    client = MagicMock()
    async def mock_complete(messages, tools, tier="full", disable_trimming=False):
        return ("summarized content here", [])
    client.complete = mock_complete
    return client


@pytest.fixture
def mock_caching_client_failing():
    client = MagicMock()
    async def mock_complete(*a, **kw):
        raise RuntimeError("fast model unavailable")
    client.complete = mock_complete
    return client


def test_trim_tool_result_under_budget_passthrough(ctx, mock_caching_client):
    short_result = "error: pod not found"
    result = asyncio.run(
        ctx.trim_tool_result("get_pod_logs", short_result, "OPENAI", mock_caching_client)
    )
    assert result == short_result  # unchanged


def test_trim_tool_result_over_budget_summarizes(ctx, mock_caching_client):
    ctx._get_setting = MagicMock(return_value="10")  # budget = 10 tokens
    long_result = "log line\n" * 500  # definitely over 10 tokens
    result = asyncio.run(
        ctx.trim_tool_result("get_pod_logs", long_result, "OPENAI", mock_caching_client)
    )
    assert result.startswith("[Summarized ~")
    assert "summarized content here" in result


def test_trim_tool_result_fast_model_failure_truncates(ctx, mock_caching_client_failing):
    ctx._get_setting = MagicMock(return_value="10")  # budget = 10 tokens
    long_result = "x" * 5000
    result = asyncio.run(
        ctx.trim_tool_result("get_pod_logs", long_result, "OPENAI", mock_caching_client_failing)
    )
    assert result.startswith("[Truncated")
    assert len(result) <= 10 * _CHARS_PER_TOKEN + 150  # truncated + header


def test_compact_conversation_under_threshold_no_op(ctx, mock_caching_client):
    ctx._get_setting = MagicMock(return_value="6")  # keep_recent = 6
    messages = [
        {"role": "system", "content": "you are an agent"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result_msgs, summary = asyncio.run(
        ctx.compact_conversation(messages, "OPENAI", mock_caching_client)
    )
    # Only 2 non-system messages, keep_recent=6, nothing to compact
    assert result_msgs == messages
    assert summary == ""


def test_compact_conversation_protects_recent_messages(ctx, mock_caching_client):
    ctx._get_setting = MagicMock(return_value="2")  # keep_recent = 2 pairs
    messages = [
        {"role": "system", "content": "system prompt"},
    ]
    # Add 6 user/assistant pairs (12 messages)
    for i in range(6):
        messages.append({"role": "user", "content": f"user msg {i}"})
        messages.append({"role": "assistant", "content": f"assistant msg {i}"})

    result_msgs, summary = asyncio.run(
        ctx.compact_conversation(messages, "OPENAI", mock_caching_client)
    )
    # System prompt preserved
    assert result_msgs[0]["role"] == "system"
    assert result_msgs[0]["content"] == "system prompt"
    # Summary injected
    assert any("[Investigation Summary]" in str(m.get("content", "")) for m in result_msgs)
    # Last 4 messages (2 pairs) preserved verbatim
    assert result_msgs[-1]["content"] == "assistant msg 5"
    assert result_msgs[-2]["content"] == "user msg 5"
    assert summary == "summarized content here"


def test_compact_conversation_fast_model_failure_returns_original(ctx, mock_caching_client_failing):
    ctx._get_setting = MagicMock(return_value="1")
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    result_msgs, summary = asyncio.run(
        ctx.compact_conversation(messages, "OPENAI", mock_caching_client_failing)
    )
    assert result_msgs == messages
    assert summary == ""


def test_trim_preserves_error_messages_in_prompt(ctx, mock_caching_client):
    """Verify the summarization prompt instructs preservation of error messages."""
    ctx._get_setting = MagicMock(return_value="5")  # tiny budget forces summarization

    captured_prompt = []
    async def mock_complete(messages, tools, tier="full", disable_trimming=False):
        captured_prompt.extend(messages)
        return ("OOMKilled exit code 137 — pod killed due to memory limit", [])

    mock_caching_client.complete = mock_complete

    long_result = "OOMKilled exit code 137\n" + ("normal log line\n" * 200)
    result = asyncio.run(
        ctx.trim_tool_result("get_pod_logs", long_result, "OPENAI", mock_caching_client)
    )
    # Summarization prompt must contain key preservation instructions
    system_content = captured_prompt[0]["content"]
    assert "Preserve ALL" in system_content
    assert "exit codes" in system_content
    # Result must include the preserved error info
    assert "OOMKilled" in result


def test_compact_conversation_summary_uses_investigation_summary_header(ctx, mock_caching_client):
    """Verify [Investigation Summary] header is applied to the summary message."""
    ctx._get_setting = MagicMock(return_value="1")  # keep_recent=1 pair
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
    ]
    result_msgs, _ = asyncio.run(
        ctx.compact_conversation(messages, "OPENAI", mock_caching_client)
    )
    summary_msgs = [
        m for m in result_msgs
        if "[Investigation Summary]" in str(m.get("content", ""))
    ]
    assert len(summary_msgs) == 1
    assert summary_msgs[0]["role"] == "system"


def test_check_budget_gemini_uses_900k_limit(ctx):
    messages = [{"role": "user", "content": "a" * 400}]
    used, limit, pct = ctx.check_budget(messages, "GEMINI")
    assert limit == 900_000
    assert pct < 0.001  # tiny percentage of 900k
