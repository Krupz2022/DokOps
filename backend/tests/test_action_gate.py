# backend/tests/test_action_gate.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


_NO_MATCH_QUERIES = [
    "show me the deployments in prod",
    "why is my application crashing",
    "check the application logs",
    "argocd applications out of sync",
    "what caused the deletion of the pod",
    "get the applied configuration",
    "list pods in default",
    "why does the ingress prefix rewrite break",
]

_MATCH_QUERIES = [
    "ok can u please fix this ?",
    "please fix the deployment",
    "scale it to 3",
    "restart the api deployment",
    "apply this manifest",
    "delete the stuck pod",
    "update the configmap",
]


@pytest.mark.parametrize("query", _NO_MATCH_QUERIES)
def test_write_intent_regex_does_not_match_read_only_queries(query):
    """Truncated stems (e.g. `appl`, `delet`) with a trailing `\\w*` used to match
    nouns like "deployments" and "application" — false-triggering the action gate
    on plainly read-only questions. The regex must be word-bounded, unstemmed
    verb forms only."""
    from app.services.ai_service import ai_service

    assert ai_service._WRITE_INTENT_RE.search(query.lower()) is None


@pytest.mark.parametrize("query", _MATCH_QUERIES)
def test_write_intent_regex_matches_write_requests(query):
    from app.services.ai_service import ai_service

    assert ai_service._WRITE_INTENT_RE.search(query.lower()) is not None


async def test_fix_queries_floor_to_investigate():
    """'fix' phrasing must never classify simple, even if the LLM says SIMPLE."""
    from app.services.ai_service import ai_service

    caching_client = MagicMock()
    caching_client.complete = AsyncMock(return_value=("SIMPLE", None))
    assert await ai_service.classify_complexity("ok can u please fix this ?", caching_client) == "investigate"
    # Genuinely simple queries still classify simple
    assert await ai_service.classify_complexity("list pods in default", caching_client) == "simple"


async def test_action_gate_forces_second_attempt():
    """A write-intent turn ending in prose gets exactly one forced retry. The
    final message must carry BOTH the first-attempt analysis (captured before
    the gate fired) AND the 'Blocked:' reply — the gate's retry prompt tells
    the model "Do not restate your analysis", so the analysis only survives if
    it is stitched back on here; the reviewer must also be short-circuited for
    it, not just happen to skip it for lack of evidence.

    Seed prior-turn evidence via history (role="system", PRIOR_EVIDENCE_PREFIX)
    so raw_observations is non-empty, the way it normally is in production (a
    presweep or earlier tool evidence exists on most turns). If the short-circuit
    in the terminal branch were removed, this non-empty observations list would
    make the code fall into _run_final_review and rewrite the "Blocked:" prose
    into reviewed markdown — this test must fail in that case.
    """
    from app.services.ai_service import AIService
    from app.services.context_manager import PRIOR_EVIDENCE_PREFIX

    svc = AIService.__new__(AIService)
    svc._get_client = MagicMock(return_value=MagicMock())
    svc._get_setting = MagicMock(side_effect=lambda k: {
        "ai_provider": "OPENAI", "ai_model": "gpt-4o", "rag_enabled": "false",
    }.get(k))
    svc._get_custom_tools_definitions = MagicMock(return_value=[])
    svc._run_prerequisite_check = AsyncMock(return_value=([], [], ""))
    svc.classify_complexity = AsyncMock(return_value="investigate")
    # Would rewrite "Blocked:..." into prose if ever awaited — the short-circuit
    # must prevent that from happening.
    svc._run_final_review = AsyncMock(return_value={"answer": "REWRITTEN BY REVIEWER"})

    history = [{
        "role": "system",
        "content": f"{PRIOR_EVIDENCE_PREFIX}\n[get_service] consul-server port 8501",
    }]

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
        events = [e async for e in svc.run_global_agentic_loop(
            "ok can u please fix this ?", history=history,
        )]

    # Gate fired: two loop completions, second saw the forced-action instruction
    assert len(loop_calls) == 2
    gate_texts = [m["content"] for m in loop_calls[1] if m.get("role") == "user"]
    assert any("TAKE AN ACTION" in (t or "") for t in gate_texts)

    svc._run_final_review.assert_not_awaited()

    results = [e for e in events if e["type"] == "result"]
    assert len(results) == 1
    message = results[0]["message"]
    # Pre-gate analysis must be preserved, not discarded ...
    assert "I recommend changing the port to 8500." in message
    # ... alongside the terse blocker itself.
    assert "Blocked: the correct Consul port is unverified" in message


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
