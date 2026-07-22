"""fix_image_pull must produce a patch manifest, not a type error.

Regression: the tool fed describe_pod's output into dict lookups, but
get_pod_details returns a human-readable STRING — so every invocation died with
"'str' object has no attribute 'get'" and the agent could only tell the user
"the fix tool encountered an error". Observed in four separate live runs.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.tools.registry import _fix_image_pull_tool

pytestmark = pytest.mark.asyncio


def _pod(image="nginx:1.99-doesnotexist", owner_kind="ReplicaSet",
         owner_name="sample-api-5b98cc9f79"):
    return SimpleNamespace(
        spec=SimpleNamespace(containers=[SimpleNamespace(name="app", image=image)]),
        metadata=SimpleNamespace(owner_references=[
            SimpleNamespace(kind=owner_kind, name=owner_name),
        ]),
    )


def _core(pod):
    core = SimpleNamespace()
    core.read_namespaced_pod = AsyncMock(return_value=pod)
    return core


_SEARCH_OK = {
    "success": True,
    "data": {"matches": [{"registry": "hub.docker.com", "image": "nginx",
                          "tags": ["1.25.3", "latest", "alpine"]}]},
}


async def test_returns_manifest_for_deployment_owned_pod():
    with patch("app.services.k8s_service.k8s_service._get_api", return_value=_core(_pod())), \
         patch("app.tools.registry._search_container_image_tool",
               AsyncMock(return_value=_SEARCH_OK)):
        result = await _fix_image_pull_tool("sample-api-5b98cc9f79-xyz", "dokops-chaos")

    assert result["success"] is True, result.get("error")
    data = result["data"]
    assert data["broken_image"] == "nginx:1.99-doesnotexist"
    assert data["deployment"] == "sample-api"          # hash suffix stripped
    assert "kind: Deployment" in data["manifest"]
    assert "name: app" in data["manifest"]
    assert data["fixed_image"].startswith("nginx:")


async def test_unreadable_pod_yields_error_not_typeerror():
    core = SimpleNamespace()
    core.read_namespaced_pod = AsyncMock(side_effect=Exception("pod not found"))
    with patch("app.services.k8s_service.k8s_service._get_api", return_value=core):
        result = await _fix_image_pull_tool("ghost", "nowhere")

    assert result["success"] is False
    assert "pod not found" in result["error"]
    assert "attribute" not in result["error"]  # the old failure mode


async def test_mock_mode_yields_clear_error():
    with patch("app.services.k8s_service.k8s_service._get_api", return_value=None):
        result = await _fix_image_pull_tool("any", "any")

    assert result["success"] is False
    assert "cluster" in result["error"].lower()
