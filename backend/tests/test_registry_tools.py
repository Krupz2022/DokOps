# backend/tests/test_registry_tools.py
import pytest
from unittest.mock import AsyncMock, patch


def test_registry_tools_in_tool_registry():
    from app.tools.registry import TOOL_REGISTRY
    assert "search_container_image" in TOOL_REGISTRY
    assert "fetch_url" in TOOL_REGISTRY


def test_registry_tools_are_read_only():
    from app.tools.registry import TOOL_REGISTRY
    assert TOOL_REGISTRY["search_container_image"]["requires_confirmation"] is False
    assert TOOL_REGISTRY["fetch_url"]["requires_confirmation"] is False


def test_registry_tools_have_image_name_input():
    from app.tools.registry import TOOL_REGISTRY
    assert "image_name" in TOOL_REGISTRY["search_container_image"]["inputs"]
    assert "url" in TOOL_REGISTRY["fetch_url"]["inputs"]


@pytest.mark.asyncio
async def test_search_container_image_disabled():
    with patch("app.tools.registry._registry_svc") as mock_svc:
        mock_svc.is_enabled.return_value = False
        from app.tools import registry as reg_module
        result = await reg_module._search_container_image_tool("nginx")
    assert result["success"] is False
    assert "disabled" in result["error"].lower()


@pytest.mark.asyncio
async def test_search_container_image_returns_matches():
    mock_matches = [
        {"registry": "hub.docker.com", "full_image": "library/nginx", "tags": ["latest", "1.25"]}
    ]
    with patch("app.tools.registry._registry_svc") as mock_svc:
        mock_svc.is_enabled.return_value = True
        mock_svc.search_image = AsyncMock(return_value=mock_matches)
        from app.tools import registry as reg_module
        result = await reg_module._search_container_image_tool("nginx")
    assert result["success"] is True
    assert result["data"]["matches"] == mock_matches


@pytest.mark.asyncio
async def test_search_container_image_no_matches():
    with patch("app.tools.registry._registry_svc") as mock_svc:
        mock_svc.is_enabled.return_value = True
        mock_svc.search_image = AsyncMock(return_value=[])
        from app.tools import registry as reg_module
        result = await reg_module._search_container_image_tool("ghost-image-xyz")
    assert result["success"] is True
    assert result["data"]["matches"] == []
    assert "No results" in result["data"]["message"]


@pytest.mark.asyncio
async def test_fetch_url_disabled():
    with patch("app.tools.registry._registry_svc") as mock_svc:
        mock_svc.is_enabled.return_value = False
        from app.tools import registry as reg_module
        result = await reg_module._fetch_url_tool("https://hub.docker.com/r/library/nginx")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_fetch_url_blocked_domain():
    with patch("app.tools.registry._registry_svc") as mock_svc:
        mock_svc.is_enabled.return_value = True
        mock_svc.fetch_url = AsyncMock(
            side_effect=ValueError("not in the registry fetch allowlist")
        )
        from app.tools import registry as reg_module
        result = await reg_module._fetch_url_tool("https://evil.example.com/payload")
    assert result["success"] is False
    assert "allowlist" in result["error"]


@pytest.mark.asyncio
async def test_fetch_url_success():
    with patch("app.tools.registry._registry_svc") as mock_svc:
        mock_svc.is_enabled.return_value = True
        mock_svc.fetch_url = AsyncMock(return_value="tag: v1.25")
        from app.tools import registry as reg_module
        result = await reg_module._fetch_url_tool("https://hub.docker.com/r/library/nginx")
    assert result["success"] is True
    assert result["data"]["content"] == "tag: v1.25"
