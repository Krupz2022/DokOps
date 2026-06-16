import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.models.external_knowledge_source import ExternalKnowledgeSource
from app.core.encryption import encrypt

MOCK_SOURCE = ExternalKnowledgeSource(
    id="abc123",
    name="Company Wiki",
    provider="azure_ai_search",
    enabled=True,
    config=encrypt(json.dumps({
        "endpoint": "https://x.search.windows.net",
        "api_key": "supersecret",
        "index_name": "kb",
        "top_k": 3,
        "semantic_config": "",
    })),
)


@pytest.fixture
def superuser_client():
    from app.api.deps import get_current_user, get_current_active_superuser
    from app.models.user import User
    mock_admin = User(id=1, username="admin", is_superuser=True, is_active=True, role="admin", hashed_password="x")
    app.dependency_overrides[get_current_user] = lambda: mock_admin
    app.dependency_overrides[get_current_active_superuser] = lambda: mock_admin
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def regular_client():
    from app.api.deps import get_current_user
    from app.models.user import User
    mock_user = User(id=2, username="user", is_superuser=False, is_active=True, role="viewer", hashed_password="x")
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield TestClient(app)
    app.dependency_overrides.clear()


@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_list_sources_masks_api_key(mock_svc, superuser_client):
    mock_svc.list_sources.return_value = [MOCK_SOURCE]
    resp = superuser_client.get("/api/v1/knowledge-sources")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["config"]["api_key"] == "••••••"
    assert "supersecret" not in resp.text


@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_create_source_requires_superuser(mock_svc, regular_client):
    resp = regular_client.post("/api/v1/knowledge-sources", json={
        "name": "Wiki",
        "provider": "azure_ai_search",
        "config": {"endpoint": "https://x.search.windows.net", "api_key": "k", "index_name": "i", "top_k": 3, "semantic_config": ""},
    })
    assert resp.status_code == 403


@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_create_source_success(mock_svc, superuser_client):
    mock_svc.create_source.return_value = MOCK_SOURCE
    resp = superuser_client.post("/api/v1/knowledge-sources", json={
        "name": "Company Wiki",
        "provider": "azure_ai_search",
        "config": {"endpoint": "https://x.search.windows.net", "api_key": "k", "index_name": "kb", "top_k": 3, "semantic_config": ""},
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Company Wiki"


@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_test_config_success(mock_svc, superuser_client):
    mock_svc.test_config.return_value = True
    resp = superuser_client.post("/api/v1/knowledge-sources/test-config", json={
        "endpoint": "https://x.search.windows.net",
        "api_key": "k",
        "index_name": "idx",
        "top_k": 3,
        "semantic_config": "",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "connected"


@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_test_config_failure_returns_503(mock_svc, superuser_client):
    mock_svc.test_config.side_effect = Exception("connection refused")
    resp = superuser_client.post("/api/v1/knowledge-sources/test-config", json={
        "endpoint": "https://x.search.windows.net",
        "api_key": "k",
        "index_name": "idx",
        "top_k": 3,
        "semantic_config": "",
    })
    assert resp.status_code == 503


@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_delete_source_not_found_returns_404(mock_svc, superuser_client):
    mock_svc.delete_source.return_value = False
    resp = superuser_client.delete("/api/v1/knowledge-sources/nonexistent")
    assert resp.status_code == 404


@patch("app.api.v1.knowledge_sources.external_rag_service")
def test_toggle_source(mock_svc, superuser_client):
    from app.models.external_knowledge_source import ExternalKnowledgeSource
    from app.core.encryption import encrypt
    updated = ExternalKnowledgeSource(
        id="abc123",
        name="Company Wiki",
        provider="azure_ai_search",
        enabled=False,
        config=encrypt(json.dumps({"endpoint": "https://x.search.windows.net", "api_key": "supersecret", "index_name": "kb", "top_k": 3, "semantic_config": ""})),
    )
    mock_svc.update_source.return_value = updated
    resp = superuser_client.patch("/api/v1/knowledge-sources/abc123/toggle", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
