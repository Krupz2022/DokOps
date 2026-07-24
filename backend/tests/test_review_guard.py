# backend/tests/test_review_guard.py
from unittest.mock import AsyncMock, MagicMock, patch


def test_review_prompt_forbids_meta_commentary():
    from app.services.ai_service import _FINAL_REVIEW_PROMPT
    lowered = _FINAL_REVIEW_PROMPT.lower()
    assert "never mention" in lowered
    assert "draft" in lowered


async def test_prior_evidence_seeds_reviewer_observations():
    """History evidence from earlier turns must reach the final reviewer."""
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

    caching_client = MagicMock()
    caching_client.complete = AsyncMock(
        return_value=("The app dials consul-server:8501 and is refused.", None)
    )
    caching_client.full_model = "gpt-4o"
    svc._get_caching_client = MagicMock(return_value=caching_client)

    review = AsyncMock(return_value={
        "root_cause": "bad consul port",
        "evidence": ["[get_pod_logs] Connection refused (consul-server:8501)"],
        "recommended_fix": "point ConsulLocation at the reachable port",
        "answer": "final reviewed answer",
    })
    svc._run_final_review = review

    evidence_msg = {
        "role": "system",
        "content": (
            f"{PRIOR_EVIDENCE_PREFIX}\n"
            "[get_pod_logs] HttpRequestException: Connection refused (consul-server:8501)"
        ),
    }
    history = [
        evidence_msg,
        {"role": "user", "content": "why is api-pod failing?"},
        {"role": "assistant", "content": "It crashes connecting to Consul."},
    ]

    with patch("app.tools.registry.build_openai_tools_schema", return_value=[]):
        events = [e async for e in svc.run_global_agentic_loop(
            "is it still failing?", history=history,
        )]

    review.assert_awaited_once()
    observations = review.await_args.args[1]
    assert any("consul-server:8501" in o for o in observations)
    results = [e for e in events if e["type"] == "result"]
    assert results and results[0]["message"] == "final reviewed answer"
