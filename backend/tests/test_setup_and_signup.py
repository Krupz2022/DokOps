# backend/tests/test_setup_and_signup.py
import asyncio
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from unittest.mock import patch

from app.main import app
from app.api import deps
from app.models.user import User
from app.models.setting import SystemSetting
from app.core import security


@pytest.fixture(name="session")
def session_fixture():
    # Use a temp file so both sync and async engines share the same DB.
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(name="client")
def client_fixture(session: Session):
    db_url = str(session.bind.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    def get_session_override():
        return session

    async def get_async_session_override():
        async with _AsyncSessionLocal() as async_session:
            yield async_session

    app.dependency_overrides[deps.get_db] = get_session_override
    app.dependency_overrides[deps.get_async_db] = get_async_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    # Dispose the async engine before the session fixture tears down and unlinks
    # the temp DB file — aiosqlite holds an open handle until dispose() is called,
    # causing WinError 32 (file in use) on Windows if we unlink first.
    asyncio.run(_async_engine.dispose())


@pytest.fixture(name="admin_client")
def admin_client_fixture(session: Session, client: TestClient):
    """Client with a superuser token pre-loaded."""
    with patch("app.core.security.get_password_hash", return_value=_FAKE_HASH):
        with patch("app.core.security.verify_password", return_value=True):
            admin = User(
                username="admin",
                hashed_password=_FAKE_HASH,
                is_superuser=True,
                role="admin",
                is_active=True,
            )
            session.add(admin)
            session.commit()

            resp = client.post(
                "/api/v1/login/access-token",
                data={"username": "admin", "password": "adminpass"},
            )
            token = resp.json()["access_token"]
            client.headers.update({"Authorization": f"Bearer {token}"})
            yield client
            client.headers.pop("Authorization", None)


# ── GET /system/status ────────────────────────────────────────────────────────

def test_status_no_users_returns_setup_incomplete(client):
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["setup_complete"] is False
    assert data["signup_enabled"] is False
    assert data["signup_default_role"] == "user"
    assert "god_mode_active" in data  # existing field must be preserved


def test_status_with_users_returns_setup_complete(session, client):
    # Use a pre-computed hash to avoid bcrypt 5.x / passlib incompatibility in tests
    # that only need a user row to exist, not to authenticate.
    session.add(User(
        username="someone",
        hashed_password="$2b$12$notarealhashbutfixedlengthXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        is_superuser=False,
        role="user",
        is_active=True,
    ))
    session.commit()

    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200
    assert resp.json()["setup_complete"] is True


def test_status_reflects_signup_settings(session, client):
    session.add(SystemSetting(key="signup_enabled", value="true"))
    session.add(SystemSetting(key="signup_default_role", value="admin"))
    session.commit()

    resp = client.get("/api/v1/system/status")
    data = resp.json()
    assert data["signup_enabled"] is True
    assert data["signup_default_role"] == "admin"


# ── POST /system/setup ────────────────────────────────────────────────────────

_FAKE_HASH = "FAKE_BCRYPT_HASH_FOR_TESTING"  # placeholder, not used for auth


def test_setup_creates_admin_and_returns_token(client):
    with patch("app.api.v1.system._security.get_password_hash", return_value=_FAKE_HASH):
        resp = client.post(
            "/api/v1/system/setup",
            json={"username": "myadmin", "password": "securepass"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["username"] == "myadmin"
    assert data["is_superuser"] is True
    assert data["role"] == "admin"


def test_setup_blocked_when_users_exist(session, client):
    session.add(User(
        username="existing",
        hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        is_superuser=True,
        role="admin",
        is_active=True,
    ))
    session.commit()

    resp = client.post(
        "/api/v1/system/setup",
        json={"username": "hacker", "password": "attempt"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Setup already complete"


def test_setup_token_is_valid(client):
    """Token returned by /setup should authenticate subsequent requests."""
    with patch("app.api.v1.system._security.get_password_hash", return_value=_FAKE_HASH):
        resp = client.post(
            "/api/v1/system/setup",
            json={"username": "firstadmin", "password": "mypassword"},
        )
    token = resp.json()["access_token"]
    me_resp = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "firstadmin"


# ── PUT /system/settings ──────────────────────────────────────────────────────

def test_update_settings_requires_superuser(client):
    # Unauthenticated request should be rejected
    settings_resp = client.put(
        "/api/v1/system/settings",
        json={"signup_enabled": True, "signup_default_role": "user"},
    )
    assert settings_resp.status_code in (401, 403)


def test_update_settings_persists(admin_client, client):
    resp = admin_client.put(
        "/api/v1/system/settings",
        json={"signup_enabled": True, "signup_default_role": "admin"},
    )
    assert resp.status_code == 200

    status_resp = client.get("/api/v1/system/status")
    data = status_resp.json()
    assert data["signup_enabled"] is True
    assert data["signup_default_role"] == "admin"


def test_update_settings_can_disable_signup(admin_client, client):
    # First enable
    resp1 = admin_client.put(
        "/api/v1/system/settings",
        json={"signup_enabled": True, "signup_default_role": "user"},
    )
    assert resp1.status_code == 200
    # Then disable
    admin_client.put(
        "/api/v1/system/settings",
        json={"signup_enabled": False, "signup_default_role": "user"},
    )
    status_resp = client.get("/api/v1/system/status")
    assert status_resp.json()["signup_enabled"] is False


def test_update_settings_rejects_invalid_role(admin_client):
    resp = admin_client.put(
        "/api/v1/system/settings",
        json={"signup_enabled": True, "signup_default_role": "superuser"},
    )
    assert resp.status_code == 400


# ── POST /register ────────────────────────────────────────────────────────────

def test_register_blocked_when_signups_disabled(client):
    # signup_enabled not set → defaults to disabled
    resp = client.post(
        "/api/v1/register",
        json={"username": "newuser", "password": "newpass"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Public signups are disabled"


def test_register_creates_user_with_default_role(session, client):
    session.add(SystemSetting(key="signup_enabled", value="true"))
    session.add(SystemSetting(key="signup_default_role", value="user"))
    session.commit()

    with patch("app.core.security.get_password_hash", return_value=_FAKE_HASH):
        resp = client.post(
            "/api/v1/register",
            json={"username": "newuser", "password": "newpass"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["username"] == "newuser"
    assert data["role"] == "user"
    assert data["is_superuser"] is False


def test_register_respects_admin_default_role(session, client):
    session.add(SystemSetting(key="signup_enabled", value="true"))
    session.add(SystemSetting(key="signup_default_role", value="admin"))
    session.commit()

    with patch("app.core.security.get_password_hash", return_value=_FAKE_HASH):
        resp = client.post(
            "/api/v1/register",
            json={"username": "poweruser", "password": "pass"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "admin"
    assert data["is_superuser"] is True


def test_register_rejects_duplicate_username(session, client):
    session.add(SystemSetting(key="signup_enabled", value="true"))
    session.add(User(
        username="taken",
        hashed_password=_FAKE_HASH,
        is_superuser=False,
        role="user",
        is_active=True,
    ))
    session.commit()

    resp = client.post(
        "/api/v1/register",
        json={"username": "taken", "password": "newpass"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Username already taken"


def test_register_token_is_valid(session, client):
    session.add(SystemSetting(key="signup_enabled", value="true"))
    session.commit()

    with patch("app.core.security.get_password_hash", return_value=_FAKE_HASH):
        resp = client.post(
            "/api/v1/register",
            json={"username": "freshuser", "password": "mypass"},
        )
    token = resp.json()["access_token"]
    me_resp = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "freshuser"
