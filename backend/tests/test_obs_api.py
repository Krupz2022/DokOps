# backend/tests/test_obs_api.py
import asyncio
import os
import tempfile
import pytest
from unittest.mock import patch, AsyncMock
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps
from app.models.user import User
from app.core import security


@pytest.fixture(name="session")
def session_fixture():
    # Use a temp file so both sync and async engines share the same DB.
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    import app.models.integration  # noqa
    import app.models.audit        # noqa
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(name="client")
def client_fixture(session: Session, monkeypatch):
    db_url = str(session.bind.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url)
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    def get_session_override():
        return session

    async def get_async_session_override():
        async with _AsyncSessionLocal() as async_session:
            yield async_session

    app.dependency_overrides[deps.get_db] = get_session_override
    app.dependency_overrides[deps.get_async_db] = get_async_session_override
    # Patch the async sessionmaker used directly in integrations_obs
    monkeypatch.setattr("app.api.v1.integrations_obs._db.AsyncSessionLocal", _AsyncSessionLocal)
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    asyncio.run(_async_engine.dispose())


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
