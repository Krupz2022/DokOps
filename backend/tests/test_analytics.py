import asyncio
import os
import tempfile
from datetime import datetime
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.testclient import TestClient
import pytest

from app.models.analytics import AITokenUsage
from app.models.user import User  # noqa: F401 - Required for foreign key table creation
from app.core.token_context import set_token_context, push_token_usage, _token_queue

import app.models.analytics  # noqa
import app.models.audit      # noqa
import app.models.setting    # noqa


# ── Fixtures for API-level tests ─────────────────────────────────────────────

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
    from app.main import app as fastapi_app
    from app.api import deps

    db_url = str(session.bind.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    def get_session_override():
        return session

    async def get_async_session_override():
        async with _AsyncSessionLocal() as async_session:
            yield async_session

    fastapi_app.dependency_overrides[deps.get_db] = get_session_override
    fastapi_app.dependency_overrides[deps.get_async_db] = get_async_session_override
    client = TestClient(fastapi_app)
    yield client
    fastapi_app.dependency_overrides.clear()
    asyncio.run(_async_engine.dispose())


@pytest.fixture(name="superuser_token_headers")
def superuser_token_headers_fixture(session: Session, client: TestClient):
    from app.core import security

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


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_aitokenusage_table_creates():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AITokenUsage(user_id=1, source="chat", model="gpt-4o", input_tokens=100, output_tokens=50))
        db.commit()
        row = db.get(AITokenUsage, 1)
    assert row.source == "chat"
    assert row.input_tokens == 100


def test_push_token_usage_enqueues_record():
    # Drain any leftover items from queue first
    while not _token_queue.empty():
        try:
            _token_queue.get_nowait()
        except Exception:
            break

    set_token_context(user_id=42, source="chat")
    asyncio.get_event_loop().run_until_complete(push_token_usage("gpt-4o", 200, 80))
    record = _token_queue.get_nowait()
    assert record["user_id"] == 42
    assert record["source"] == "chat"
    assert record["model"] == "gpt-4o"
    assert record["input_tokens"] == 200
    assert record["output_tokens"] == 80


# ── API-level test ────────────────────────────────────────────────────────────

def test_get_token_analytics_returns_structure(client, superuser_token_headers):
    res = client.get("/api/v1/analytics/tokens?range=7d", headers=superuser_token_headers)
    assert res.status_code == 200
    data = res.json()
    assert "summary" in data
    assert "daily" in data
    assert "by_source" in data
    assert "by_model" in data
    assert "by_user" in data
