import hashlib
import pytest
from datetime import datetime as dt
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from unittest.mock import patch

from app.models.user import User
from app.models.setting import SystemSetting
from app.core import security


# Delegate to the shared dual-engine fixtures defined in conftest.py.
@pytest.fixture(name="session")
def session_fixture(isolated_session):
    return isolated_session


@pytest.fixture(name="client")
def client_fixture(isolated_client):
    return isolated_client


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(session: Session, client: TestClient):
    user = User(
        username="admin",
        hashed_password=security.get_password_hash("adminpass"),
        is_active=True,
        is_superuser=True,
        role="admin",
    )
    session.add(user)
    session.commit()
    resp = client.post("/api/v1/login/access-token", data={"username": "admin", "password": "adminpass"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_get_compat_config_defaults(client: TestClient, auth_headers: dict):
    resp = client.get("/api/v1/system/openai-compat", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["has_key"] is False
    assert data["created_at"] is None


def test_get_compat_config_unauthenticated(client: TestClient):
    resp = client.get("/api/v1/system/openai-compat")
    assert resp.status_code == 401


def test_patch_compat_config_enables(client: TestClient, auth_headers: dict):
    resp = client.patch("/api/v1/system/openai-compat", json={"enabled": True}, headers=auth_headers)
    assert resp.status_code == 200
    get_resp = client.get("/api/v1/system/openai-compat", headers=auth_headers)
    assert get_resp.json()["enabled"] is True


def test_regenerate_key_format(client: TestClient, auth_headers: dict):
    resp = client.post("/api/v1/system/openai-compat/regenerate-key", headers=auth_headers)
    assert resp.status_code == 200
    key = resp.json()["key"]
    assert key.startswith("sk-dokops-")
    assert len(key) == len("sk-dokops-") + 64  # token_hex(32) = 64 hex chars


def test_regenerate_key_stores_hash(client: TestClient, auth_headers: dict, session: Session):
    resp = client.post("/api/v1/system/openai-compat/regenerate-key", headers=auth_headers)
    plaintext = resp.json()["key"]
    row = session.exec(select(SystemSetting).where(SystemSetting.key == "openai_compat_api_key_hash")).first()
    assert row is not None
    assert row.value == hashlib.sha256(plaintext.encode()).hexdigest()


def test_regenerate_key_updates_created_at(client: TestClient, auth_headers: dict, session: Session):
    client.post("/api/v1/system/openai-compat/regenerate-key", headers=auth_headers)
    row = session.exec(select(SystemSetting).where(SystemSetting.key == "openai_compat_key_created_at")).first()
    assert row is not None
    dt.fromisoformat(row.value)  # raises ValueError if malformed
    assert row.value


def test_get_compat_config_reflects_key(client: TestClient, auth_headers: dict):
    client.post("/api/v1/system/openai-compat/regenerate-key", headers=auth_headers)
    resp = client.get("/api/v1/system/openai-compat", headers=auth_headers)
    data = resp.json()
    assert data["has_key"] is True
    assert data["created_at"] is not None


def test_patch_compat_config_disables(client: TestClient, auth_headers: dict):
    # Enable first
    client.patch("/api/v1/system/openai-compat", json={"enabled": True}, headers=auth_headers)
    # Then disable
    resp = client.patch("/api/v1/system/openai-compat", json={"enabled": False}, headers=auth_headers)
    assert resp.status_code == 200
    get_resp = client.get("/api/v1/system/openai-compat", headers=auth_headers)
    assert get_resp.json()["enabled"] is False


# ── Router tests ───────────────────────────────────────────────────────────────

def _setup_compat_enabled(session: Session, key_plaintext: str) -> None:
    """Helper: enable compat API and store a key hash in the test DB."""
    key_hash = hashlib.sha256(key_plaintext.encode()).hexdigest()
    for k, v in [
        ("openai_compat_enabled", "true"),
        ("openai_compat_api_key_hash", key_hash),
        ("openai_compat_key_created_at", "2026-05-13T00:00:00"),
    ]:
        session.add(SystemSetting(key=k, value=v))
    session.commit()


def test_models_endpoint_requires_auth(client: TestClient, session: Session):
    _setup_compat_enabled(session, "sk-dokops-testkey")
    resp = client.get("/v1/models")
    assert resp.status_code == 401


def test_models_endpoint_returns_dokops(client: TestClient, session: Session):
    _setup_compat_enabled(session, "sk-dokops-testkey")
    resp = client.get("/v1/models", headers={"Authorization": "Bearer sk-dokops-testkey"})
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["data"]]
    assert "dokops" in ids


def test_chat_completions_disabled_returns_403(client: TestClient, session: Session):
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"Authorization": "Bearer sk-dokops-testkey"},
    )
    assert resp.status_code == 403


def test_chat_completions_wrong_key_returns_401(client: TestClient, session: Session):
    _setup_compat_enabled(session, "sk-dokops-testkey")
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"Authorization": "Bearer sk-dokops-WRONGKEY"},
    )
    assert resp.status_code == 401


def test_chat_completions_no_user_message_returns_400(client: TestClient, session: Session):
    _setup_compat_enabled(session, "sk-dokops-testkey")
    with patch("app.api.openai_compat.k8s_service") as mock_k8s:
        mock_k8s.mock_mode = False
        mock_k8s.default_context = "minikube"
        mock_k8s.get_contexts.return_value = ["minikube"]
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "system", "content": "you are helpful"}]},
            headers={"Authorization": "Bearer sk-dokops-testkey"},
        )
    assert resp.status_code == 400


def test_chat_completions_unknown_cluster_hint_returns_400(client: TestClient, session: Session):
    _setup_compat_enabled(session, "sk-dokops-testkey")
    with patch("app.api.openai_compat.k8s_service") as mock_k8s:
        mock_k8s.mock_mode = False
        mock_k8s.get_contexts.return_value = ["minikube"]
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [
                {"role": "system", "content": "cluster_id: nonexistent"},
                {"role": "user", "content": "hello"},
            ]},
            headers={"Authorization": "Bearer sk-dokops-testkey"},
        )
    assert resp.status_code == 400
    assert "nonexistent" in resp.json()["detail"]["error"]["message"]


def test_chat_completions_nonstreaming_returns_openai_format(client: TestClient, session: Session):
    _setup_compat_enabled(session, "sk-dokops-testkey")

    async def fake_loop(*args, **kwargs):
        yield {"type": "step", "message": "Checking pods..."}
        yield {"type": "result", "message": "All pods are healthy."}

    with patch("app.api.openai_compat.k8s_service") as mock_k8s, \
         patch("app.api.openai_compat.ai_service.run_global_agentic_loop", side_effect=fake_loop):
        mock_k8s.mock_mode = False
        mock_k8s.default_context = "minikube"
        mock_k8s.get_contexts.return_value = ["minikube"]
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "check cluster"}], "stream": False},
            headers={"Authorization": "Bearer sk-dokops-testkey"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"] == "All pods are healthy."
    assert data["choices"][0]["finish_reason"] == "stop"
    assert "id" in data
    assert "created" in data


def test_chat_completions_cluster_hint_resolution(client: TestClient, session: Session):
    _setup_compat_enabled(session, "sk-dokops-testkey")

    captured_context = {}

    async def capturing_loop(*args, **kwargs):
        captured_context["context"] = kwargs.get("context")
        yield {"type": "result", "message": "ok"}

    with patch("app.api.openai_compat.k8s_service") as mock_k8s, \
         patch("app.api.openai_compat.ai_service.run_global_agentic_loop", side_effect=capturing_loop):
        mock_k8s.mock_mode = False
        mock_k8s.default_context = "minikube"
        mock_k8s.get_contexts.return_value = ["minikube", "production"]
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [
                {"role": "system", "content": "cluster_name: production"},
                {"role": "user", "content": "hello"},
            ], "stream": False},
            headers={"Authorization": "Bearer sk-dokops-testkey"},
        )

    assert resp.status_code == 200
    assert captured_context["context"] == "production"


def test_chat_completions_streaming_returns_sse(client: TestClient, session: Session):
    _setup_compat_enabled(session, "sk-dokops-testkey")

    async def fake_loop(*args, **kwargs):
        yield {"type": "step", "message": "Checking..."}
        yield {"type": "result", "message": "Cluster is healthy."}

    with patch("app.api.openai_compat.k8s_service") as mock_k8s, \
         patch("app.api.openai_compat.ai_service.run_global_agentic_loop", side_effect=fake_loop):
        mock_k8s.mock_mode = False
        mock_k8s.default_context = "minikube"
        mock_k8s.get_contexts.return_value = ["minikube"]
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "check cluster"}], "stream": True},
            headers={"Authorization": "Bearer sk-dokops-testkey"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "chat.completion.chunk" in body
    assert "[DONE]" in body
    assert "Cluster is healthy." in body
    # step events should NOT appear as content chunks
    assert "Checking..." not in body or ": Checking..." in body  # only as SSE comment
