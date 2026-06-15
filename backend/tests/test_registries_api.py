# backend/tests/test_registries_api.py
import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.api import deps
from app.models.user import User
from app.core import security

import app.models.registry  # noqa — registers RegistryConnection table
import app.models.setting   # noqa
import app.models.audit     # noqa
import app.models.user      # noqa


# session: delegate to the shared temp-file fixture from conftest.py.
@pytest.fixture(name="session")
def session_fixture(isolated_session):
    return isolated_session


@pytest.fixture(name="client")
def client_fixture(isolated_session, monkeypatch):
    """Client with get_async_db override + registries router patch."""
    db_url = str(isolated_session.bind.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    async def get_async_session_override():
        async with _AsyncSessionLocal() as async_session:
            yield async_session

    fastapi_app.dependency_overrides[deps.get_async_db] = get_async_session_override
    # Patch the async sessionmaker used directly in registries router
    monkeypatch.setattr("app.api.v1.registries._db.AsyncSessionLocal", _AsyncSessionLocal)
    client = TestClient(fastapi_app)
    yield client
    fastapi_app.dependency_overrides.clear()
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
    resp = client.post(
        "/api/v1/login/access-token", data={"username": "admin", "password": "pass123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_list_registries_empty(client, auth_headers):
    resp = client.get("/api/v1/registries/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_add_registry(client, auth_headers):
    resp = client.post(
        "/api/v1/registries/",
        json={"name": "My ACR", "url": "mycompany.azurecr.io", "username": "user1", "password": "s3cr3t"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My ACR"
    assert data["url"] == "mycompany.azurecr.io"
    assert "password" not in data   # never returned
    assert "id" in data


def test_list_after_add(client, auth_headers):
    client.post(
        "/api/v1/registries/",
        json={"name": "ACR", "url": "acr.azurecr.io"},
        headers=auth_headers,
    )
    resp = client.get("/api/v1/registries/", headers=auth_headers)
    assert len(resp.json()) == 1


def test_delete_registry(client, auth_headers):
    add = client.post(
        "/api/v1/registries/",
        json={"name": "Temp", "url": "temp.example.io"},
        headers=auth_headers,
    )
    rid = add.json()["id"]
    del_resp = client.delete(f"/api/v1/registries/{rid}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True
    assert client.get("/api/v1/registries/", headers=auth_headers).json() == []


def test_delete_nonexistent(client, auth_headers):
    resp = client.delete("/api/v1/registries/no-such-id", headers=auth_headers)
    assert resp.status_code == 404


def test_get_settings_defaults_disabled(client, auth_headers):
    resp = client.get("/api/v1/registries/settings", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_update_settings_enable(client, auth_headers):
    resp = client.post(
        "/api/v1/registries/settings", json={"enabled": True}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    # persisted
    get_resp = client.get("/api/v1/registries/settings", headers=auth_headers)
    assert get_resp.json()["enabled"] is True


def test_update_settings_toggle_off(client, auth_headers):
    client.post("/api/v1/registries/settings", json={"enabled": True}, headers=auth_headers)
    resp = client.post(
        "/api/v1/registries/settings", json={"enabled": False}, headers=auth_headers
    )
    assert resp.json()["enabled"] is False


def test_add_registry_strips_trailing_slash(client, auth_headers):
    resp = client.post(
        "/api/v1/registries/",
        json={"name": "Harbor", "url": "harbor.example.io/"},
        headers=auth_headers,
    )
    assert resp.json()["url"] == "harbor.example.io"
