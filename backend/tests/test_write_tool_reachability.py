"""Regression guard: write tools must survive an obs-flavoured phrasing.

Reproduced live against minikube 2026-08-04. In a chat where the agent had
already used `update_configmap` successfully, the follow-up turn
"Now set LOG_LEVEL to debug in that same configmap" produced no
`pending_operation` at all -- the agent answered "I don't have a ConfigMap
write tool available". The approval card never appeared because the backend
never proposed the operation.

Two causes in `_select_dynamic_tools`, both fixed:

1. `k8s_write` matched tool *names* against
   ("scale","deploy","delete","create","patch","apply","restart").
   `update_configmap` contains none of them, so it was never a write tool --
   it fell into `k8s_rest`, reachable only through relevance ranking.

2. That relevance ranking was gated on `not is_obs`, and `_OBS_KEYWORDS`
   matches as a *substring* -- so "LOG_LEVEL" set is_obs and dropped the
   whole `k8s_rest` tail.

Together: any message containing "log"/"metric"/"search"/"query"/"trace"
made every update_* tool structurally unreachable, and whether the agent
recovered depended on it guessing `discover_tools` with a matching intent
string.

THIRD CAUSE, found 2026-08-05 and fixed elsewhere: every query below names
the MECHANISM ("configmap"), which is why relevance ranking finds the tool.
A user who names only the SYMPTOM does not -- "set the log level to debug for
checkout-api in payments" scores update_configmap 0, because _score_tool
counts query words appearing in the tool's description and none of
level/debug/checkout-api/payments do. Relevance ranking cannot close that
gap: it has no way to know the setting lives in a ConfigMap.

The fix is not another keyword list. presweep.build_config_sources reads the
pod spec and establishes the owner as a fact, and a non-empty owner map now
force-includes the config tools via _select_dynamic_tools(force_tools=...).
See tests/test_config_ownership.py.
"""
from app.services.ai_service import AIService
from app.tools import registry


def _names(query: str) -> set:
    selected = AIService._select_dynamic_tools(
        query=query,
        obs_tools_schema=[],
        full_k8s_schema=registry.build_openai_tools_schema(),
        mcp_schema=[],
        custom_tools_schema=[],
    )
    return {t["function"]["name"] for t in selected}


def test_update_configmap_survives_the_word_log():
    """The exact turn that failed in the live repro."""
    assert "update_configmap" in _names(
        "Now set LOG_LEVEL to debug in that same configmap so I can see more detail."
    )


def test_update_configmap_reachable_without_obs_wording():
    """The turn that worked, so the guard can't pass by selecting everything."""
    assert "update_configmap" in _names(
        "Fix it. Update the configmap to point at the real consul service."
    )


def test_update_tools_stay_relevance_reachable():
    """update_* must NOT be moved into k8s_write.

    k8s_write is only added when is_write fires on the query text. "set
    LOG_LEVEL to debug" carries no write keyword, so a write-only
    classification puts update_configmap in neither list. It has to stay in
    k8s_rest, where relevance ranking can find it by name.
    """
    write_intent = _names("update the checkout-config configmap")
    assert {n for n in write_intent if n.startswith("update_")}, (
        "no update_* tool selected for an explicit update request"
    )


def test_obs_wording_still_does_not_pull_unrelated_writes():
    """Cause 2's fix relaxes a gate -- it must not become 'select everything'.

    Relevance ranking is score-based, so a logs question that names no
    resource must not drag in deletion tools.
    """
    selected = _names("show me the elasticsearch logs for the last hour")
    assert "delete_namespace" not in selected
    assert "drain_node" not in selected


if __name__ == "__main__":  # ponytail: runnable without pytest
    test_update_configmap_survives_the_word_log()
    test_update_configmap_reachable_without_obs_wording()
    test_update_tools_stay_relevance_reachable()
    test_obs_wording_still_does_not_pull_unrelated_writes()
    print("all checks passed")
