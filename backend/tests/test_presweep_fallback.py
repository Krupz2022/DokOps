# backend/tests/test_presweep_fallback.py
from unittest.mock import AsyncMock, MagicMock, patch


async def test_resolve_namespace_matches_real_namespace_in_text(monkeypatch):
    """The cluster-name fallback finds a namespace mentioned anywhere in text."""
    from app.services import presweep

    fake_ns = MagicMock()
    fake_ns.metadata.name = "namespace1"
    fake_core = MagicMock()
    fake_core.list_namespace = AsyncMock(return_value=MagicMock(items=[fake_ns]))
    monkeypatch.setattr(presweep.k8s_service, "_get_api", lambda name: fake_core)

    assert await presweep.resolve_namespace(
        "pod api-pod-234654 in namespace1 is CrashLoopBackOff"
    ) == "namespace1"
    assert await presweep.resolve_namespace("ok can u please fix this ?") is None


async def test_agent_loop_falls_back_to_history_for_namespace():
    """When the query names no namespace, the loop retries resolution against
    recent history text and runs the presweep on the result."""
    from types import SimpleNamespace
    from app.services.ai_service import AIService

    svc = AIService.__new__(AIService)
    svc._get_client = MagicMock(return_value=MagicMock())
    svc._get_setting = MagicMock(side_effect=lambda k: {
        "ai_provider": "OPENAI", "ai_model": "gpt-4o", "rag_enabled": "false",
    }.get(k))
    svc._get_custom_tools_definitions = MagicMock(return_value=[])
    svc._run_prerequisite_check = AsyncMock(return_value=([], [], ""))
    svc.classify_complexity = AsyncMock(return_value="investigate")

    complete = AsyncMock(return_value=("Done — nothing else to add.", None))
    caching_client = MagicMock()
    caching_client.complete = complete
    caching_client.full_model = "gpt-4o"
    svc._get_caching_client = MagicMock(return_value=caching_client)

    history = [
        {"role": "user", "content": "check whats failing"},
        {"role": "assistant", "content": "api-pod-234654 in namespace1 is CrashLoopBackOff"},
    ]

    resolve = AsyncMock(side_effect=[None, "namespace1"])
    build = AsyncMock(return_value="PRE-FLIGHT SWEEP of namespace 'namespace1' — facts here\n")

    with patch("app.services.presweep.resolve_namespace", resolve), \
         patch("app.services.presweep.build_presweep", build), \
         patch("app.tools.registry.build_openai_tools_schema", return_value=[]):
        events = [e async for e in svc.run_global_agentic_loop(
            "ok can u please fix this ?", history=history,
        )]

    assert resolve.await_count == 2
    # Second resolution call ran against history text, not the bare query
    second_arg = resolve.await_args_list[1].args[0]
    assert "namespace1" in second_arg
    build.assert_awaited_once_with("namespace1")
    assert any(e["type"] == "result" for e in events)
