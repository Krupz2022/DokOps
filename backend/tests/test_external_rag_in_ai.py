import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.mark.asyncio
async def test_external_rag_retrieve_all_called_during_agent_chat():
    """retrieve_all is called once per agent_chat invocation."""
    from app.services.ai_service import AIService
    svc = AIService()

    # Patch the heavy dependencies so the test stays unit-level
    with patch.object(svc, "_get_setting", return_value=""), \
         patch.object(svc, "_get_caching_client") as mock_client_factory, \
         patch("app.services.ai_service._build_kubeconfig_for_cluster", return_value=None), \
         patch("app.services.ai_service.sanitize_for_llm", side_effect=lambda x: x), \
         patch("app.services.ai_service.toolset_service") as mock_toolsets, \
         patch("app.services.external_rag_service.external_rag_service") as mock_ext_rag:

        mock_ext_rag.retrieve_all.return_value = '<retrieved_document index="1" source="Wiki">test chunk</retrieved_document>'

        mock_toolsets.get_tool_definitions.return_value = []
        mock_toolsets.get_custom_tools_definitions = MagicMock(return_value=[])

        mock_caching = MagicMock()
        mock_caching.chat_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="answer", tool_calls=None))],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5),
        )
        mock_client_factory.return_value = mock_caching

        try:
            async for _ in svc.run_global_agentic_loop(
                query="what's wrong with my pod",
                history=[],
                context=None,
            ):
                pass
        except Exception:
            pass  # we only care that retrieve_all was called

        mock_ext_rag.retrieve_all.assert_called_once_with("what's wrong with my pod")
