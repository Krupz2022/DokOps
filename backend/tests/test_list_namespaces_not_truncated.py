import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


def _ns(name):
    n = MagicMock()
    n.metadata.name = name
    n.status.phase = "Active"
    # Real clusters carry these; they used to be serialised into the observation
    # and blew past the LLM char cap.
    n.metadata.labels = {
        "kubernetes.io/metadata.name": name,
        "istio-injection": "enabled",
        "app.kubernetes.io/managed-by": "argocd",
        "team": "platform-engineering",
    }
    n.metadata.creation_timestamp = "2026-01-15 08:31:04+00:00"
    return n


async def test_twenty_namespaces_survive_the_llm_char_cap():
    """The bug: str(result) exceeded sanitize_for_llm's 4000-char head slice,
    silently dropping the last few namespaces before the model ever saw them."""
    from app.tools import k8s_tools
    from app.services.sanitizer import sanitize_for_llm

    names = [f"team-namespace-number-{i:02d}" for i in range(20)]
    api = MagicMock()
    api.list_namespace = AsyncMock(return_value=MagicMock(items=[_ns(n) for n in names]))

    with patch.object(k8s_tools.k8s_service, "_get_api", return_value=api):
        res = await k8s_tools.list_namespaces()

    assert res["data"]["total"] == 20
    # Same call the chat agent makes: sanitize_for_llm(str(exec_res)) with defaults.
    observation = sanitize_for_llm(str(res))
    missing = [n for n in names if n not in observation]
    assert not missing, f"truncated away: {missing}"
