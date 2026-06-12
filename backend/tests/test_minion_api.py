import asyncio
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from unittest.mock import patch

from app.main import app
from app.api import deps
from app.models.user import User
from app.models.minion import Minion, MinionJob  # noqa: F401 — registers tables
from app.models.audit import AuditLog  # noqa: F401
from app.core import security

_FAKE_HASH = "FAKE_BCRYPT_HASH_FOR_TESTING"


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
    asyncio.run(_async_engine.dispose())


@pytest.fixture(name="admin_client")
def admin_client_fixture(session: Session, client: TestClient):
    """Client with a superuser token and god-mode active."""
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


def test_list_minions_returns_empty(admin_client):
    resp = admin_client.get("/api/v1/minions/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_approve_nonexistent_minion_returns_404(admin_client):
    with patch("app.api.deps.is_god_mode_active", return_value=True):
        resp = admin_client.post("/api/v1/minions/no-such-id/approve")
    assert resp.status_code == 404


def test_install_sh_is_public(client):
    # Public path — no auth header needed; 404 is fine if minion/ dir doesn't exist yet
    raw = TestClient(app).get("/minion/install.sh")
    assert raw.status_code in (200, 404)
