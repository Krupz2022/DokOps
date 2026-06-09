import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.ai_service import AIService, _INVESTIGATION_PROTOCOL, _FINAL_REVIEW_PROMPT


def _mock_client(response):
    """Returns a mock CachingAIClient that returns (response, None) from complete()."""
    mock = MagicMock()
    mock.complete = AsyncMock(return_value=(response, None))
    return mock


# ── classify_investigation ───────────────────────────────────────────────────

class TestClassifyInvestigation:
    def setup_method(self):
        self.svc = AIService()

    @pytest.mark.asyncio
    async def test_investigate_query_returns_true(self):
        result = await self.svc.classify_investigation(
            "why is payments-api crashing?", _mock_client("INVESTIGATE")
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_simple_query_returns_false(self):
        result = await self.svc.classify_investigation(
            "get cluster health", _mock_client("SIMPLE")
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self):
        result = await self.svc.classify_investigation(
            "what is wrong", _mock_client("investigate")
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_model_error_returns_false(self):
        broken = MagicMock()
        broken.complete = AsyncMock(side_effect=Exception("timeout"))
        result = await self.svc.classify_investigation("why is pod failing?", broken)
        assert result is False

    @pytest.mark.asyncio
    async def test_unexpected_response_returns_false(self):
        result = await self.svc.classify_investigation(
            "get logs", _mock_client("UNKNOWN_WORD")
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_none_response_returns_false(self):
        result = await self.svc.classify_investigation(
            "investigate pod", _mock_client(None)
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_uses_tier_fast(self):
        mock = MagicMock()
        mock.complete = AsyncMock(return_value=("SIMPLE", None))
        await self.svc.classify_investigation("get health", mock)
        call_kwargs = mock.complete.call_args[1]
        assert call_kwargs.get("tier") == "fast"


# ── _run_final_review ────────────────────────────────────────────────────────

class TestRunFinalReview:
    def setup_method(self):
        self.svc = AIService()
        self.query = "why is payments-api crashing?"
        self.obs = ["Pod logs show OOMKill", "Memory limit: 128Mi, usage: 127Mi"]
        self.draft = "The pod is crashing due to OOMKill."

    def _review_json(self, root_cause="OOMKill — 128Mi limit", evidence=None,
                     fix="Increase memory limit to 256Mi", answer="Pod OOMKilled."):
        return json.dumps({
            "root_cause": root_cause,
            "evidence": evidence or ["OOMKill in logs"],
            "recommended_fix": fix,
            "answer": answer,
        })

    @pytest.mark.asyncio
    async def test_returns_structured_dict_on_success(self):
        result = await self.svc._run_final_review(
            self.query, self.obs, self.draft, _mock_client(self._review_json())
        )
        assert result["root_cause"] == "OOMKill — 128Mi limit"
        assert result["recommended_fix"] == "Increase memory limit to 256Mi"
        assert isinstance(result["evidence"], list)
        assert result["answer"] == "Pod OOMKilled."

    @pytest.mark.asyncio
    async def test_model_error_returns_draft(self):
        broken = MagicMock()
        broken.complete = AsyncMock(side_effect=Exception("timeout"))
        result = await self.svc._run_final_review(self.query, self.obs, self.draft, broken)
        assert result == {"answer": self.draft}

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_draft(self):
        result = await self.svc._run_final_review(
            self.query, self.obs, self.draft, _mock_client("not valid json at all")
        )
        assert result == {"answer": self.draft}

    @pytest.mark.asyncio
    async def test_json_embedded_in_prose_is_extracted(self):
        review = {"root_cause": "disk full", "evidence": ["df 100%"],
                  "recommended_fix": "clean /var/log", "answer": "Disk full."}
        prose = f"Here is the review:\n```json\n{json.dumps(review)}\n```"
        result = await self.svc._run_final_review(
            self.query, self.obs, self.draft, _mock_client(prose)
        )
        assert result["root_cause"] == "disk full"

    @pytest.mark.asyncio
    async def test_malformed_json_in_match_returns_draft(self):
        """Regex finds {…} block but json.loads raises — fallback to draft."""
        malformed = "Result: { root_cause: 'missing quotes', }"  # invalid JSON
        result = await self.svc._run_final_review(
            self.query, self.obs, self.draft, _mock_client(malformed)
        )
        assert result == {"answer": self.draft}

    @pytest.mark.asyncio
    async def test_uses_tier_fast(self):
        mock = MagicMock()
        mock.complete = AsyncMock(return_value=(self._review_json(), None))
        await self.svc._run_final_review(self.query, self.obs, self.draft, mock)
        call_kwargs = mock.complete.call_args[1]
        assert call_kwargs.get("tier") == "fast"

    @pytest.mark.asyncio
    async def test_observations_capped_at_10(self):
        """Only first 10 observations are forwarded to keep the review prompt small."""
        mock = MagicMock()
        mock.complete = AsyncMock(return_value=(self._review_json(), None))
        many_obs = [f"obs {i}" for i in range(20)]
        await self.svc._run_final_review(self.query, many_obs, self.draft, mock)
        call_args = mock.complete.call_args[0]
        messages_sent = call_args[0]  # first positional arg is the messages list
        user_message = next(m for m in messages_sent if m.get("role") == "user")
        user_content = user_message["content"]
        # obs 10-19 must NOT appear in the prompt
        assert "obs 10" not in user_content
        assert "obs 9" in user_content

# ── Integration: hooks 1 + 2 ─────────────────────────────────────────────────

from unittest.mock import patch, AsyncMock as _AsMock, MagicMock as _MM


def _build_loop_patches(classify_result: bool, complete_response: str = "Done."):
    """Returns a dict of mock objects for the loop's dependencies."""
    mock_caching = _MM()
    mock_caching.full_model = "gpt-4o"
    mock_caching.complete = _AsMock(return_value=(complete_response, None))

    mock_ctx_mgr = _MM()
    mock_ctx_mgr.check_budget.return_value = (100, 128_000, 0.001)
    mock_ctx_mgr.trim_tool_result = _AsMock(side_effect=lambda n, r, p, c: r)

    mock_registry = _MM()
    mock_registry.build_openai_tools_schema.return_value = []
    mock_registry.RAG_TOOL_REGISTRY = {}
    mock_registry.TOOL_REGISTRY = {}
    mock_registry.execute_tool_async = _AsMock(return_value="result")

    mock_mcp = _MM()
    mock_mcp.build_openai_tools_schema.return_value = []
    mock_mcp.get_all_tools_for_prompt.return_value = ""

    mock_int_mgr = _MM()
    mock_int_mgr.get_active_tool_registry.return_value = {}
    mock_int_mgr.get_tools_description_for_prompt.return_value = ""

    mock_topo = _MM()
    mock_topo.get_cluster_overview.return_value = "cluster: test-cluster"

    mock_k8s = _MM()
    mock_k8s.default_context = None

    return {
        "caching_client": mock_caching,
        "ctx_mgr": mock_ctx_mgr,
        "registry": mock_registry,
        "mcp": mock_mcp,
        "int_mgr": mock_int_mgr,
        "topo": mock_topo,
        "k8s": mock_k8s,
        "classify_result": classify_result,
    }


# Patch targets: these must match where each name is imported FROM inside the function body.
_PATCH_CTX_MGR    = 'app.services.context_manager.context_manager'
_PATCH_MCP        = 'app.services.mcp_client_service.mcp_client_service'
_PATCH_INT_MGR    = 'app.services.integration_manager.integration_manager'
_PATCH_TOPO       = 'app.services.topology_service.topology_service'
_PATCH_K8S        = 'app.services.k8s_service.k8s_service'


async def _run_loop(svc, query, patches):
    events = []
    with patch.object(svc, '_get_caching_client', return_value=patches["caching_client"]), \
         patch.object(svc, 'classify_investigation', new=_AsMock(return_value=patches["classify_result"])), \
         patch.object(svc, '_get_setting', return_value=None), \
         patch.object(svc, '_get_custom_tools_definitions', return_value=[]), \
         patch(_PATCH_CTX_MGR, patches["ctx_mgr"]), \
         patch('app.tools.registry.build_openai_tools_schema', return_value=[]), \
         patch('app.tools.registry.RAG_TOOL_REGISTRY', {}), \
         patch('app.tools.registry.TOOL_REGISTRY', patches["registry"].TOOL_REGISTRY), \
         patch('app.tools.registry.execute_tool_async', patches["registry"].execute_tool_async), \
         patch(_PATCH_MCP, patches["mcp"]), \
         patch(_PATCH_INT_MGR, patches["int_mgr"]), \
         patch(_PATCH_TOPO, patches["topo"]), \
         patch(_PATCH_K8S, patches["k8s"]):
        async for event in svc._run_global_agentic_loop_inner(query=query):
            events.append(event)
    return events


class TestInvestigationModeHooks:
    def setup_method(self):
        self.svc = AIService()

    @pytest.mark.asyncio
    async def test_investigation_protocol_injected_when_mode_true(self):
        """_INVESTIGATION_PROTOCOL must appear in the system message when mode=True."""
        captured = []
        patches = _build_loop_patches(classify_result=True)
        orig_complete = patches["caching_client"].complete

        async def capture_and_return(messages, tools, **kwargs):
            if not captured:
                captured.extend(messages)
            return await orig_complete(messages, tools, **kwargs)

        patches["caching_client"].complete = capture_and_return

        await _run_loop(self.svc, "why is payments-api crashing?", patches)

        assert captured, "complete() was never called"
        system_content = captured[0]["content"]
        assert "INVESTIGATION MODE" in system_content
        assert "PHASE 1" in system_content

    @pytest.mark.asyncio
    async def test_investigation_protocol_not_injected_when_mode_false(self):
        """_INVESTIGATION_PROTOCOL must NOT appear in system message when mode=False."""
        captured = []
        patches = _build_loop_patches(classify_result=False)
        orig_complete = patches["caching_client"].complete

        async def capture_and_return(messages, tools, **kwargs):
            if not captured:
                captured.extend(messages)
            return await orig_complete(messages, tools, **kwargs)

        patches["caching_client"].complete = capture_and_return

        await _run_loop(self.svc, "get cluster health", patches)

        assert captured
        system_content = captured[0]["content"]
        assert "INVESTIGATION MODE" not in system_content

    @pytest.mark.asyncio
    async def test_classify_investigation_called_at_loop_start(self):
        """classify_investigation must be called once per loop invocation."""
        patches = _build_loop_patches(classify_result=False)
        classify_mock = _AsMock(return_value=False)

        with patch.object(self.svc, '_get_caching_client', return_value=patches["caching_client"]), \
             patch.object(self.svc, 'classify_investigation', new=classify_mock), \
             patch.object(self.svc, '_get_setting', return_value=None), \
             patch.object(self.svc, '_get_custom_tools_definitions', return_value=[]), \
             patch(_PATCH_CTX_MGR, patches["ctx_mgr"]), \
             patch('app.tools.registry.build_openai_tools_schema', return_value=[]), \
             patch('app.tools.registry.RAG_TOOL_REGISTRY', {}), \
             patch('app.tools.registry.TOOL_REGISTRY', patches["registry"].TOOL_REGISTRY), \
             patch('app.tools.registry.execute_tool_async', patches["registry"].execute_tool_async), \
             patch(_PATCH_MCP, patches["mcp"]), \
             patch(_PATCH_INT_MGR, patches["int_mgr"]), \
             patch(_PATCH_TOPO, patches["topo"]), \
             patch(_PATCH_K8S, patches["k8s"]):
            async for _ in self.svc._run_global_agentic_loop_inner(query="get health"):
                pass

        classify_mock.assert_called_once()
        call_args = classify_mock.call_args[0]
        assert call_args[0] == "get health"


# ── Integration: hook 3 (final review) ───────────────────────────────────────

class TestFinalReviewHook:
    def setup_method(self):
        self.svc = AIService()

    @pytest.mark.asyncio
    async def test_final_review_called_when_mode_true_and_observations_exist(self):
        """When investigation_mode=True and tool observations exist, _run_final_review is called."""
        # Simulate: first call returns a tool_call, second returns text (final answer)
        tool_call_stub = _MM()
        tool_call_stub.id = "tc_001"
        tool_call_stub.function = _MM()
        tool_call_stub.function.name = "get_cluster_health"
        tool_call_stub.function.arguments = "{}"

        call_count = 0

        async def multi_turn(messages, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None, [tool_call_stub]
            return "The pod is crashing due to OOMKill.", None

        patches = _build_loop_patches(classify_result=True)
        patches["caching_client"].complete = multi_turn
        patches["registry"].TOOL_REGISTRY = {"get_cluster_health": _MM()}
        patches["registry"].execute_tool_async = _AsMock(return_value="Health: degraded")

        review_output = {
            "root_cause": "OOMKill",
            "evidence": ["Health: degraded"],
            "recommended_fix": "Increase memory",
            "answer": "Pod OOMKilled — increase memory limit.",
        }
        final_review_mock = _AsMock(return_value=review_output)

        with patch.object(self.svc, '_get_caching_client', return_value=patches["caching_client"]), \
             patch.object(self.svc, 'classify_investigation', new=_AsMock(return_value=True)), \
             patch.object(self.svc, '_run_final_review', new=final_review_mock), \
             patch.object(self.svc, '_get_setting', return_value=None), \
             patch.object(self.svc, '_get_custom_tools_definitions', return_value=[]), \
             patch(_PATCH_CTX_MGR, patches["ctx_mgr"]), \
             patch('app.tools.registry.build_openai_tools_schema', return_value=[]), \
             patch('app.tools.registry.RAG_TOOL_REGISTRY', {}), \
             patch('app.tools.registry.TOOL_REGISTRY', patches["registry"].TOOL_REGISTRY), \
             patch('app.tools.registry.execute_tool_async', patches["registry"].execute_tool_async), \
             patch(_PATCH_MCP, patches["mcp"]), \
             patch(_PATCH_INT_MGR, patches["int_mgr"]), \
             patch(_PATCH_TOPO, patches["topo"]), \
             patch(_PATCH_K8S, patches["k8s"]):
            events = []
            async for event in self.svc._run_global_agentic_loop_inner(
                query="why is payments-api crashing?"
            ):
                events.append(event)

        # _run_final_review must have been called
        final_review_mock.assert_called_once()

        # Result event must carry structured output
        result_events = [e for e in events if e.get("type") == "result"]
        assert result_events, "No result event emitted"
        result = result_events[-1]
        assert result["message"] == "Pod OOMKilled — increase memory limit."
        assert "structured" in result, f"'structured' key missing from result: {result}"
        assert result["structured"]["root_cause"] == "OOMKill"
        assert result["structured"]["recommended_fix"] == "Increase memory"

    @pytest.mark.asyncio
    async def test_final_review_not_called_when_mode_false(self):
        """When investigation_mode=False, _run_final_review is never called."""
        patches = _build_loop_patches(classify_result=False, complete_response="Cluster is healthy.")
        final_review_mock = _AsMock(return_value={"answer": "x"})

        with patch.object(self.svc, '_get_caching_client', return_value=patches["caching_client"]), \
             patch.object(self.svc, 'classify_investigation', new=_AsMock(return_value=False)), \
             patch.object(self.svc, '_run_final_review', new=final_review_mock), \
             patch.object(self.svc, '_get_setting', return_value=None), \
             patch.object(self.svc, '_get_custom_tools_definitions', return_value=[]), \
             patch(_PATCH_CTX_MGR, patches["ctx_mgr"]), \
             patch('app.tools.registry.build_openai_tools_schema', return_value=[]), \
             patch('app.tools.registry.RAG_TOOL_REGISTRY', {}), \
             patch('app.tools.registry.TOOL_REGISTRY', patches["registry"].TOOL_REGISTRY), \
             patch('app.tools.registry.execute_tool_async', patches["registry"].execute_tool_async), \
             patch(_PATCH_MCP, patches["mcp"]), \
             patch(_PATCH_INT_MGR, patches["int_mgr"]), \
             patch(_PATCH_TOPO, patches["topo"]), \
             patch(_PATCH_K8S, patches["k8s"]):
            async for _ in self.svc._run_global_agentic_loop_inner(query="get cluster health"):
                pass

        final_review_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_review_skipped_when_no_tool_observations(self):
        """When investigation_mode=True but no tool observations, result is yielded directly."""
        patches = _build_loop_patches(classify_result=True, complete_response="Done with no tools.")
        final_review_mock = _AsMock(return_value={"answer": "x"})

        with patch.object(self.svc, '_get_caching_client', return_value=patches["caching_client"]), \
             patch.object(self.svc, 'classify_investigation', new=_AsMock(return_value=True)), \
             patch.object(self.svc, '_run_final_review', new=final_review_mock), \
             patch.object(self.svc, '_get_setting', return_value=None), \
             patch.object(self.svc, '_get_custom_tools_definitions', return_value=[]), \
             patch(_PATCH_CTX_MGR, patches["ctx_mgr"]), \
             patch('app.tools.registry.build_openai_tools_schema', return_value=[]), \
             patch('app.tools.registry.RAG_TOOL_REGISTRY', {}), \
             patch('app.tools.registry.TOOL_REGISTRY', patches["registry"].TOOL_REGISTRY), \
             patch('app.tools.registry.execute_tool_async', patches["registry"].execute_tool_async), \
             patch(_PATCH_MCP, patches["mcp"]), \
             patch(_PATCH_INT_MGR, patches["int_mgr"]), \
             patch(_PATCH_TOPO, patches["topo"]), \
             patch(_PATCH_K8S, patches["k8s"]):
            events = []
            async for event in self.svc._run_global_agentic_loop_inner(
                query="why is pod failing?"
            ):
                events.append(event)

        final_review_mock.assert_not_called()
        result_events = [e for e in events if e.get("type") == "result"]
        assert result_events[-1]["message"] == "Done with no tools."
