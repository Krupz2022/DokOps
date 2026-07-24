# backend/tests/test_content_filter.py
from unittest.mock import AsyncMock, MagicMock, patch

AZURE_400 = Exception(
    "Error code: 400 - {'error': {'message': \"The response was filtered due to the "
    "prompt triggering Azure OpenAI's content management policy.\", 'code': "
    "'content_filter', 'status': 400, 'innererror': {'code': "
    "'ResponsibleAIPolicyViolation', 'content_filter_result': {'jailbreak': "
    "{'detected': True, 'filtered': True}}}}}"
)


def test_is_content_filter_error_detection() -> None:
    from app.services.ai_service import _is_content_filter_error

    assert _is_content_filter_error(AZURE_400)
    assert _is_content_filter_error(Exception("ResponsibleAIPolicyViolation"))
    assert not _is_content_filter_error(Exception("Error code: 429 - rate limit"))
    assert not _is_content_filter_error(Exception("connection reset"))


def _make_svc():
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
    return svc


async def test_content_filter_retry_strips_evidence_and_succeeds() -> None:
    """First call filtered -> retry without the prior-evidence block succeeds."""
    from app.services.context_manager import PRIOR_EVIDENCE_PREFIX

    svc = _make_svc()

    seen_message_lists: list = []

    async def fake_complete(messages, tools, **kw):
        seen_message_lists.append(list(messages))
        if len(seen_message_lists) == 1:
            raise AZURE_400
        return "Recovered answer after stripping.", None

    caching_client = MagicMock()
    caching_client.complete = fake_complete
    caching_client.full_model = "gpt-4o"
    svc._get_caching_client = MagicMock(return_value=caching_client)

    history = [
        {"role": "system", "content": f"{PRIOR_EVIDENCE_PREFIX}\n[get_pod_logs] scary verbatim logs"},
        {"role": "user", "content": "why is it failing?"},
    ]

    with patch("app.tools.registry.build_openai_tools_schema", return_value=[]):
        events = [e async for e in svc.run_global_agentic_loop(
            "why is it failing?", history=history,
        )]

    # Retry happened and the evidence block was stripped from the second call
    assert len(seen_message_lists) == 2
    assert any(
        str(m.get("content") or "").startswith(PRIOR_EVIDENCE_PREFIX)
        for m in seen_message_lists[0]
    )
    assert not any(
        str(m.get("content") or "").startswith(PRIOR_EVIDENCE_PREFIX)
        for m in seen_message_lists[1]
    )
    # The recovered draft proceeds down the NORMAL terminal path: the final
    # review runs on it (mocked here) and its answer is what gets yielded.
    svc._run_final_review.assert_awaited_once()
    assert svc._run_final_review.await_args.args[2] == "Recovered answer after stripping."
    results = [e for e in events if e["type"] == "result"]
    assert results and results[0]["message"] == "unused"


async def test_content_filter_double_failure_yields_friendly_message() -> None:
    """Filtered even after stripping -> one human sentence, never raw JSON."""
    svc = _make_svc()

    calls = {"n": 0}

    async def fake_complete(messages, tools, **kw):
        calls["n"] += 1
        raise AZURE_400

    caching_client = MagicMock()
    caching_client.complete = fake_complete
    caching_client.full_model = "gpt-4o"
    svc._get_caching_client = MagicMock(return_value=caching_client)

    with patch("app.tools.registry.build_openai_tools_schema", return_value=[]):
        events = [e async for e in svc.run_global_agentic_loop("why is it failing?")]

    assert calls["n"] == 2  # original + one stripped retry, then stop
    results = [e for e in events if e["type"] == "result"]
    assert len(results) == 1
    msg = results[0]["message"]
    assert "content filter" in msg.lower()
    assert "content_filter_result" not in msg  # no raw JSON to the user
    assert "400" not in msg
