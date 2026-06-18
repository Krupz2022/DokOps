import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.ai_service import AIService


def _tool(name: str, desc: str = "") -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": {}, "required": []}}}


def test_score_tool_counts_matching_words():
    score = AIService._score_tool(
        {"redis", "memory"}, _tool("redis_info", "show redis memory usage")
    )
    assert score == 2


def test_score_tool_zero_when_no_overlap():
    assert AIService._score_tool({"banana"}, _tool("get_nodes", "list nodes")) == 0


def test_selection_keeps_relevant_rest_tools_over_irrelevant():
    full_k8s = [
        _tool("get_cluster_health", "cluster health"),   # core
        _tool("get_quota_usage", "show namespace resource quota usage"),
        _tool("get_random_thing", "unrelated helper"),
    ]
    selected = AIService._select_dynamic_tools(
        "show me resource quota usage", [], full_k8s, [], [],
    )
    names = [t["function"]["name"] for t in selected]
    assert "get_quota_usage" in names


def test_selection_never_exceeds_safety_ceiling():
    full_k8s = [_tool(f"tool_{i}", f"desc {i}") for i in range(200)]
    # min_score=0 forces all tools through so the cap-truncation branch actually fires
    selected = AIService._select_dynamic_tools(
        "investigate everything", [], full_k8s, [], [], max_total=64, min_score=0,
    )
    assert len(selected) == 64


def test_schema_for_tools_returns_named_only():
    from app.tools import registry
    schema = registry.schema_for_tools(["get_cluster_health"])
    names = [t["function"]["name"] for t in schema]
    assert names == ["get_cluster_health"]


def test_discover_tools_matches_by_intent():
    from app.tools import registry
    res = registry.discover_tools("cluster health")
    assert res["success"] is True
    found = [t["name"] for t in res["data"]["tools"]]
    assert "get_cluster_health" in found


def test_selection_always_includes_discover_tools():
    from app.services.ai_service import AIService
    selected = AIService._select_dynamic_tools("anything", [], [], [], [])
    names = [t["function"]["name"] for t in selected]
    assert "discover_tools" in names


def test_discover_tools_survives_the_cap():
    # Many non-matching tools force the cap; discover_tools must still be present.
    full_k8s = [_tool(f"tool_{i}", f"desc {i}") for i in range(200)]
    selected = AIService._select_dynamic_tools(
        "investigate everything", [], full_k8s, [], [], max_total=64, min_score=0,
    )
    names = [t["function"]["name"] for t in selected]
    assert "discover_tools" in names
    assert len(selected) <= 64


def _mock_client(text: str):
    m = MagicMock()
    m.complete = AsyncMock(return_value=(text, None))
    return m


@pytest.mark.asyncio
async def test_classify_complexity_simple():
    out = await AIService().classify_complexity("get cluster health", _mock_client("SIMPLE"))
    assert out == "simple"


@pytest.mark.asyncio
async def test_classify_complexity_deep():
    out = await AIService().classify_complexity(
        "full root cause analysis across all namespaces", _mock_client("DEEP")
    )
    assert out == "deep"


@pytest.mark.asyncio
async def test_classify_complexity_defaults_to_investigate_on_error():
    broken = MagicMock()
    broken.complete = AsyncMock(side_effect=Exception("boom"))
    out = await AIService().classify_complexity("why failing", broken)
    assert out == "investigate"


def test_step_budgets_increase_with_complexity():
    b = AIService.STEP_BUDGETS
    assert b["simple"] < b["investigate"] < b["deep"]
