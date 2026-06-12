# backend/tests/test_registry_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.registry_service import (
    RegistryService,
    _strip_digest,
    _parse_image,
    BUILT_IN_REGISTRIES,
    FETCH_ALLOWLIST,
)


# --- Pure-function unit tests (no I/O) ---

def test_strip_digest_removes_sha():
    assert _strip_digest("nginx@sha256:abc123def456") == "nginx"


def test_strip_digest_leaves_tag_alone():
    assert _strip_digest("nginx:1.25-alpine") == "nginx:1.25-alpine"


def test_strip_digest_handles_full_ref():
    assert _strip_digest("ghcr.io/foo/bar@sha256:deadbeef") == "ghcr.io/foo/bar"


def test_parse_image_official_image():
    registry, path, tag = _parse_image("nginx")
    assert registry == "hub.docker.com"
    assert path == "library/nginx"
    assert tag == "latest"


def test_parse_image_user_scoped():
    registry, path, tag = _parse_image("myrepo/myapp:v2")
    assert registry == "hub.docker.com"
    assert path == "myrepo/myapp"
    assert tag == "v2"


def test_parse_image_ghcr():
    registry, path, tag = _parse_image("ghcr.io/owner/repo:latest")
    assert registry == "ghcr.io"
    assert path == "owner/repo"
    assert tag == "latest"


def test_parse_image_acr():
    registry, path, tag = _parse_image("mycompany.azurecr.io/myapp:prod")
    assert registry == "mycompany.azurecr.io"
    assert path == "myapp"
    assert tag == "prod"


def test_parse_image_strips_digest():
    registry, path, tag = _parse_image("nginx@sha256:abc123")
    assert registry == "hub.docker.com"
    assert path == "library/nginx"


def test_built_in_registries_list():
    names = [r["url"] for r in BUILT_IN_REGISTRIES]
    assert "hub.docker.com" in names
    assert "ghcr.io" in names
    assert "quay.io" in names
    assert "registry.k8s.io" in names


def test_fetch_allowlist_contains_github():
    assert "raw.githubusercontent.com" in FETCH_ALLOWLIST
    assert "api.github.com" in FETCH_ALLOWLIST


# --- RegistryService unit tests (mocked I/O) ---

@pytest.mark.asyncio
async def test_is_enabled_false_when_no_setting():
    from app.models.setting import SystemSetting
    svc = RegistryService()
    with patch("app.services.registry_service.AsyncSessionLocal") as mock_session_cls:
        mock_db = AsyncMock()
        mock_db.get.return_value = None
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        assert await svc.is_enabled() is False


@pytest.mark.asyncio
async def test_is_enabled_true():
    from app.models.setting import SystemSetting
    svc = RegistryService()
    with patch("app.services.registry_service.AsyncSessionLocal") as mock_session_cls:
        mock_db = AsyncMock()
        mock_db.get.return_value = SystemSetting(key="registry_lookup_enabled", value="true")
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        assert await svc.is_enabled() is True


@pytest.mark.asyncio
async def test_search_image_docker_hub():
    svc = RegistryService()
    mock_tags = ["latest", "1.25", "1.24", "alpine"]
    with patch("app.services.registry_service._search_docker_hub", new=AsyncMock(return_value=mock_tags)), \
         patch.object(svc, "_get_user_registries", new=AsyncMock(return_value=[])):
        results = await svc.search_image("nginx")
    assert len(results) == 1
    assert results[0]["registry"] == "hub.docker.com"
    assert results[0]["tags"] == mock_tags
    assert "library/nginx" in results[0]["full_image"]


@pytest.mark.asyncio
async def test_search_image_returns_empty_on_no_results():
    svc = RegistryService()
    with patch("app.services.registry_service._search_docker_hub", new=AsyncMock(return_value=[])), \
         patch.object(svc, "_get_user_registries", new=AsyncMock(return_value=[])):
        results = await svc.search_image("definitely-does-not-exist-xyz")
    assert results == []


@pytest.mark.asyncio
async def test_search_image_ghcr():
    svc = RegistryService()
    mock_tags = ["v1.0", "v1.1", "latest"]
    with patch("app.services.registry_service._oci_get_tags", new=AsyncMock(return_value=mock_tags)):
        results = await svc.search_image("ghcr.io/owner/repo:latest")
    assert results[0]["registry"] == "ghcr.io"
    assert results[0]["tags"] == mock_tags


@pytest.mark.asyncio
async def test_fetch_url_blocked_domain():
    svc = RegistryService()
    with patch.object(svc, "_get_fetch_allowlist", new=AsyncMock(return_value={"hub.docker.com"})):
        with pytest.raises(ValueError, match="not in the registry fetch allowlist"):
            await svc.fetch_url("https://evil.example.com/script")


@pytest.mark.asyncio
async def test_fetch_url_allowed_domain():
    svc = RegistryService()
    mock_resp = MagicMock()
    mock_resp.text = "tag list content here"
    with patch("httpx.AsyncClient") as mock_cls:
        inst = AsyncMock()
        inst.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=inst)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await svc.fetch_url("https://hub.docker.com/r/library/nginx")
    assert result == "tag list content here"


@pytest.mark.asyncio
async def test_fetch_url_truncates_large_response():
    svc = RegistryService()
    long_text = "x" * 5000
    mock_resp = MagicMock()
    mock_resp.text = long_text
    with patch("httpx.AsyncClient") as mock_cls:
        inst = AsyncMock()
        inst.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=inst)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await svc.fetch_url("https://hub.docker.com/r/library/nginx")
    assert len(result) <= 4100  # 4000 chars + truncation notice
    assert "(truncated)" in result
