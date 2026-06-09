# backend/tests/test_obs_api.py
import pytest
from unittest.mock import patch, AsyncMock
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps
from app.models.user import User
from app.core import security


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    import app.models.integration  # noqa
    import app.models.audit        # noqa
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session, monkeypatch):
    def get_session_override():
        return session

    app.dependency_overrides[deps.get_db] = get_session_override
    # Also patch the module-level engine used in integrations_obs for Session(engine) calls
    monkeypatch.setattr("app.api.v1.integrations_obs.engine", session.bind)
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(session: Session, client: TestClient):
    user = User(
        username="admin",
        hashed_password=security.get_password_hash("pass123"),
        is_active=True,
        is_superuser=True,
        role="admin",
    )
    session.add(user)
    session.commit()
    resp = client.post("/api/v1/login/access-token", data={"username": "admin", "password": "pass123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_integrations_empty(client, auth_headers):
    resp = client.get("/api/v1/integrations/obs/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_connect_integration(client, auth_headers):
    payload = {
        "backend": "prometheus",
        "display_name": "My Prom",
        "base_url": "http://prometheus:9090",
        "auth_type": "none",
    }
    with patch("app.api.v1.integrations_obs.PrometheusService") as MockSvc:
        MockSvc.return_value.test_connection = AsyncMock(return_value=(True, "Connected"))
        resp = client.post("/api/v1/integrations/obs/connect", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["backend"] == "prometheus"
    assert data["is_active"] is True


def test_connect_integration_bad_backend(client, auth_headers):
    payload = {
        "backend": "unknown_backend",
        "display_name": "X",
        "base_url": "http://x:9090",
        "auth_type": "none",
    }
    resp = client.post("/api/v1/integrations/obs/connect", json=payload, headers=auth_headers)
    assert resp.status_code == 422


def test_disconnect_integration(client, auth_headers):
    payload = {"backend": "loki", "display_name": "Loki", "base_url": "http://loki:3100", "auth_type": "none"}
    with patch("app.api.v1.integrations_obs.LokiService") as MockSvc:
        MockSvc.return_value.test_connection = AsyncMock(return_value=(True, "Connected"))
        resp = client.post("/api/v1/integrations/obs/connect", json=payload, headers=auth_headers)
    row_id = resp.json()["id"]

    resp2 = client.delete(f"/api/v1/integrations/obs/{row_id}", headers=auth_headers)
    assert resp2.status_code == 200
    assert resp2.json()["deleted"] is True
