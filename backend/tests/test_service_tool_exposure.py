"""Regression guard for the destructive-only service-tool exposure bug fixed
2026-08-04 (fix wave 3, "Fix 2").

In `_select_dynamic_tools`, `k8s_rest` already excluded service-prefixed
tools (redis_*, rabbitmq_*, couchdb_*, ...) via `_all_service_prefixes`, but
`k8s_write` had no such exclusion. `k8s_write`'s keyword list
("scale", "deploy", "delete", "create", "patch", "apply", "restart") matches
substrings in tool *names*, not just Kubernetes tool names -- so any service
tool whose name happens to contain one of those words (redis_delete_key,
couchdb_delete_db, rabbitmq_delete_queue, ...) leaked into the tool schema
for ANY write-intent query, regardless of which service (if any) the query
named. Every read-only service tool (redis_info, couchdb_server_info, ...)
stayed correctly gated behind a keyword match against
AIService._SERVICE_TOOL_MAP. That asymmetry -- only the destructive tools
leak -- is backwards for a platform whose stated philosophy is least
privilege by default (CLAUDE.md section 3).

The fix gives k8s_write the same service-prefix exclusion k8s_rest already
had. Service tools -- destructive or not -- now reach the model only via
the service path (keyword match in AIService._SERVICE_TOOL_MAP) or
discover_tools.
"""
from app.services.ai_service import AIService
from app.tools import registry

# Derived from AIService._SERVICE_TOOL_MAP rather than hardcoded, so a new
# service family added to the map is automatically covered by these tests.
_SERVICE_PREFIXES = sorted(set(AIService._SERVICE_TOOL_MAP.values()))


def _select(query: str, history=None):
    full_k8s_schema = registry.build_openai_tools_schema()
    return AIService._select_dynamic_tools(
        query=query,
        obs_tools_schema=[],
        full_k8s_schema=full_k8s_schema,
        mcp_schema=[],
        custom_tools_schema=[],
        history=history,
    )


def _names(selected):
    return {t["function"]["name"] for t in selected}


def test_write_intent_query_naming_no_service_gets_no_service_tools():
    """'delete the failing pod in payments' is a write-intent Kubernetes query
    that names no backend service. Before the fix, k8s_write's loose
    substring match on "delete" pulled in every service tool whose name
    contains "delete" (redis_delete_key, couchdb_delete_db,
    rabbitmq_delete_queue, ...) even though the query never mentioned Redis,
    CouchDB or RabbitMQ. No service-prefixed tool should be offered here."""
    selected_names = _names(_select("delete the failing pod in payments"))

    leaked = [
        n for n in selected_names
        if any(n.startswith(pfx) for pfx in _SERVICE_PREFIXES)
    ]
    assert not leaked, (
        f"write-intent query naming no service leaked service tools: {sorted(leaked)} -- "
        "k8s_write must exclude service-prefixed tools the same way k8s_rest does"
    )
    # Spell out the exact tools named in the bug report so a regression is
    # unambiguous, not just "some service tool leaked".
    for destructive in ("redis_delete_key", "couchdb_delete_db", "rabbitmq_delete_queue"):
        assert destructive not in selected_names, (
            f"{destructive} must not be reachable on a write-intent query that "
            "names no service -- destructive service tools were leaking through "
            "k8s_write's keyword match while every read-only service tool stayed "
            "correctly gated"
        )


def test_other_write_verbs_naming_no_service_also_get_no_service_tools():
    """Same bug, different k8s_write keywords ('restart', 'patch', 'scale',
    'create', 'apply') -- each of these also appears inside a real service
    tool name, so each was an independent leak path before the fix."""
    queries = [
        "restart the crashing deployment",
        "patch the deployment's memory limit",
        "scale the frontend deployment to 3 replicas",
        "create a new namespace for staging",
        "apply this manifest to the cluster",
    ]
    for query in queries:
        selected_names = _names(_select(query))
        leaked = [
            n for n in selected_names
            if any(n.startswith(pfx) for pfx in _SERVICE_PREFIXES)
        ]
        assert not leaked, f"query {query!r} leaked service tools: {sorted(leaked)}"


def test_redis_query_still_offers_redis_tools():
    """Pin that Fix 2 did not over-correct: a query that DOES name a service
    ('redis') must still get redis tools via the service path in
    _select_dynamic_tools (matched_service_prefixes / is_service branch),
    independent of k8s_write's now-excluded service tools. This is the
    eval's redis_uses_redis_tools scenario query
    ("redis memory usage looks high, what is filling it").

    Note: this does NOT assert Kubernetes core tools are absent from the
    schema -- the is_service branch deliberately still adds k8s_core "for
    context" (see _select_dynamic_tools), so e.g. get_cluster_health remains
    in the offered schema even for a pure Redis question. The eval's
    must_not_call list polices what the *model* chooses to call with a real
    LLM in the loop, not what _select_dynamic_tools offers -- that is a
    separate, non-deterministic concern out of scope for this test.
    """
    selected_names = _names(_select("redis memory usage looks high, what is filling it"))

    assert "redis_info" in selected_names or "redis_keyspace_stats" in selected_names, (
        "redis service tools must still be offered when the query names redis"
    )
    # The service path in _select_dynamic_tools injects ALL matched-prefix
    # tools unconditionally (read AND write), so redis_delete_key remains
    # reachable here -- correctly, because the query named the service.
    assert "redis_delete_key" in selected_names, (
        "service path should still offer the full redis_* tool set, including "
        "write tools, once the query actually names redis -- only the "
        "no-service-named case should be gated"
    )


def test_redis_write_intent_query_still_offers_redis_tools():
    """A write-intent query that DOES name redis ('restart redis') must still
    get the full redis tool set via the service path -- confirms the k8s_write
    exclusion only removes the leak for queries that name no service, not for
    queries that legitimately ask about a named service with write intent."""
    selected_names = _names(_select("restart redis to clear the memory leak"))
    assert "redis_info" in selected_names
    assert "redis_delete_key" in selected_names
