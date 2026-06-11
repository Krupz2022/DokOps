# backend/tests/test_chat.py
import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlmodel.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from unittest.mock import patch

from app.main import app
from app.api import deps
from app.models.user import User
from app.models.chat import ChatMessage
from app.core import security


@pytest.fixture(name="session")
def session_fixture():
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


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(session: Session, client: TestClient):
    user = User(
        username="testuser",
        hashed_password=security.get_password_hash("testpass"),
        is_active=True,
        role="user",
    )
    session.add(user)
    session.commit()
    resp = client.post("/api/v1/login/access-token", data={"username": "testuser", "password": "testpass"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_conversation(client: TestClient, auth_headers: dict):
    resp = client.post("/api/v1/chat/conversations", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["title"] == "New Chat"


def test_list_conversations(client: TestClient, auth_headers: dict):
    client.post("/api/v1/chat/conversations", headers=auth_headers)
    client.post("/api/v1/chat/conversations", headers=auth_headers)
    resp = client.get("/api/v1/chat/conversations", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_conversation(client: TestClient, auth_headers: dict):
    create_resp = client.post("/api/v1/chat/conversations", headers=auth_headers)
    conv_id = create_resp.json()["id"]
    resp = client.get(f"/api/v1/chat/conversations/{conv_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == conv_id
    assert "messages" in resp.json()


def test_rename_conversation(client: TestClient, auth_headers: dict):
    create_resp = client.post("/api/v1/chat/conversations", headers=auth_headers)
    conv_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/chat/conversations/{conv_id}", json={"title": "My Chat"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["title"] == "My Chat"


def test_delete_conversation(client: TestClient, auth_headers: dict):
    create_resp = client.post("/api/v1/chat/conversations", headers=auth_headers)
    conv_id = create_resp.json()["id"]
    resp = client.delete(f"/api/v1/chat/conversations/{conv_id}", headers=auth_headers)
    assert resp.status_code == 200
    get_resp = client.get(f"/api/v1/chat/conversations/{conv_id}", headers=auth_headers)
    assert get_resp.status_code == 404


def test_send_message_streams_events(client: TestClient, auth_headers: dict):
    """Sending a message returns SSE stream with at least one event."""
    create_resp = client.post("/api/v1/chat/conversations", headers=auth_headers)
    conv_id = create_resp.json()["id"]

    fake_events = [
        {"type": "step", "message": "Searching..."},
        {"type": "result", "message": "Done."},
    ]

    async def fake_loop(*args, **kwargs):
        for e in fake_events:
            yield e

    with patch("app.api.v1.chat.ai_service.run_global_agentic_loop", new=fake_loop):
        resp = client.post(
            f"/api/v1/chat/conversations/{conv_id}/message",
            json={"content": "What is wrong?"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    body = resp.text
    assert "Searching..." in body
    assert "Done." in body


def test_send_message_saves_to_db(client: TestClient, auth_headers: dict, session: Session):
    """User message and AI messages are persisted after streaming."""
    create_resp = client.post("/api/v1/chat/conversations", headers=auth_headers)
    conv_id = create_resp.json()["id"]

    async def fake_loop(*args, **kwargs):
        yield {"type": "result", "message": "All good."}

    with patch("app.api.v1.chat.ai_service.run_global_agentic_loop", new=fake_loop):
        client.post(
            f"/api/v1/chat/conversations/{conv_id}/message",
            json={"content": "Status?"},
            headers=auth_headers,
        )

    msgs = session.exec(select(ChatMessage).where(ChatMessage.conversation_id == conv_id)).all()
    roles = [m.role for m in msgs]
    assert "user" in roles
    assert "assistant" in roles


def test_send_message_emits_token_usage_event(client: TestClient, auth_headers: dict):
    """SSE stream ends with a token_usage event containing conversation_total."""
    create_resp = client.post("/api/v1/chat/conversations", headers=auth_headers)
    conv_id = create_resp.json()["id"]

    async def fake_loop(*args, **kwargs):
        yield {"type": "result", "message": "All good."}

    with patch("app.api.v1.chat.ai_service.run_global_agentic_loop", new=fake_loop):
        resp = client.post(
            f"/api/v1/chat/conversations/{conv_id}/message",
            json={"content": "Status?"},
            headers=auth_headers,
        )

    events = [
        json.loads(line[6:])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    token_events = [e for e in events if e.get("type") == "token_usage"]
    assert len(token_events) == 1
    te = token_events[0]
    assert "conversation_total" in te
    assert te["conversation_total"] > 0
    assert te["source"] in ("provider", "estimate")
    assert "input_tokens" in te
    assert "output_tokens" in te
    assert te["total_tokens"] == te["input_tokens"] + te["output_tokens"]


def test_get_conversation_includes_total_tokens(client: TestClient, auth_headers: dict, session: Session):
    """GET conversation response includes total_tokens field summed from messages."""
    from app.models.chat import ChatMessage as CM

    create_resp = client.post("/api/v1/chat/conversations", headers=auth_headers)
    conv_id = create_resp.json()["id"]

    # Manually insert messages with known token counts
    session.add(CM(conversation_id=conv_id, role="user", content="hello", message_type="text", token_count=10))
    session.add(CM(conversation_id=conv_id, role="assistant", content="hi", message_type="text", token_count=5))
    session.commit()

    resp = client.get(f"/api/v1/chat/conversations/{conv_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_tokens" in data
    assert data["total_tokens"] == 15
