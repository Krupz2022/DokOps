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
    selected = AIService._select_dynamic_tools(
        "investigate everything", [], full_k8s, [], [], max_total=64,
    )
    assert len(selected) <= 64
