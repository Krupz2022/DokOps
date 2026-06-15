import asyncio
from datetime import datetime
from sqlmodel import SQLModel, create_engine, Session
from fastapi.testclient import TestClient
import pytest

from app.models.analytics import AITokenUsage
from app.models.user import User  # noqa: F401 - Required for foreign key table creation
from app.core.token_context import set_token_context, push_token_usage, _token_queue

import app.models.analytics  # noqa
import app.models.audit      # noqa
import app.models.setting    # noqa


# ── Fixtures for API-level tests — delegate to shared conftest fixtures ───────

@pytest.fixture(name="session")
def session_fixture(isolated_session):
    return isolated_session


@pytest.fixture(name="client")
def client_fixture(isolated_client):
    return isolated_client


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
    asyncio.run(push_token_usage("gpt-4o", 200, 80))
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
