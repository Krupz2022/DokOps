"""
Tests for Knowledge Sources API v2 — provider validation + updated test-config signature.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1.knowledge_sources import _mask_config


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def superuser_client():
    from app.api.deps import get_current_user, get_current_active_superuser
    from app.models.user import User
    mock_admin = User(
        id=1, username="admin", is_superuser=True, is_active=True,
        role="admin", hashed_password="x",
    )
    app.dependency_overrides[get_current_user] = lambda: mock_admin
    app.dependency_overrides[get_current_active_superuser] = lambda: mock_admin
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Unit tests for _mask_config ───────────────────────────────────────────────

def test_mask_config_masks_api_key():
    result = _mask_config({"api_key": "secret", "index_name": "kb"})
    assert result["api_key"] == "••••••"
    assert result["index_name"] == "kb"


def test_mask_config_masks_password():
    result = _mask_config({"password": "secret", "username": "u"})
    assert result["password"] == "••••••"
    assert result["username"] == "u"


def test_mask_config_masks_api_token():
    result = _mask_config({"api_token": "tok", "endpoint": "http://x"})
    assert result["api_token"] == "••••••"
    assert result["endpoint"] == "http://x"


# ── API tests ─────────────────────────────────────────────────────────────────

@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_test_config_passes_provider(mock_svc, superuser_client):
    """POST /test-config must call service.test_config(provider, config) with correct args."""
    mock_svc.test_config = AsyncMock(return_value=True)
    config_payload = {"host": "localhost", "port": 9200, "index": "my-index"}
    resp = superuser_client.post(
        "/api/v1/knowledge-sources/test-config",
        json={"provider": "opensearch", "config": config_payload},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "connected"
    mock_svc.test_config.assert_called_once_with("opensearch", config_payload)


@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_create_rejects_unknown_provider(mock_svc, superuser_client):
    """POST /knowledge-sources with unknown provider must return 400."""
    resp = superuser_client.post(
        "/api/v1/knowledge-sources",
        json={"name": "t", "provider": "unknown_db", "config": {}},
    )
    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "provider" in detail.lower()
