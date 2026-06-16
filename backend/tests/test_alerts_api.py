# backend/tests/test_alerts_api.py
import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from unittest.mock import patch, AsyncMock

from app.main import app
from app.core.db import engine as real_engine
from app.models.alert_incident import AlertIncident
from app.models.user import User
from app.api import deps
from datetime import datetime, timezone


@pytest.fixture
def client():
    return TestClient(app)


def test_webhook_unknown_source_returns_404(client):
    resp = client.post("/api/v1/alerts/webhook/unknown_source", json={})
    assert resp.status_code == 404


def test_webhook_unconfigured_source_returns_503(client):
    # No secret configured in test DB → 503
    with patch("app.services.webhook_security._get_secrets", new_callable=AsyncMock, return_value={}):
        resp = client.post(
            "/api/v1/alerts/webhook/generic",
            json={"alert_name": "Test", "severity": "warning"},
            headers={"X-DokOps-Webhook-Secret": "some-token"},
        )
    assert resp.status_code == 503


def test_webhook_wrong_secret_returns_401(client):
    with patch("app.services.webhook_security._get_secrets", new_callable=AsyncMock, return_value={"generic": "correct-secret"}):
        resp = client.post(
            "/api/v1/alerts/webhook/generic",
            json={"alert_name": "Test", "severity": "warning"},
            headers={"X-DokOps-Webhook-Secret": "wrong-secret"},
        )
    assert resp.status_code == 401


def test_webhook_valid_request_returns_202(client):
    with patch("app.services.webhook_security._get_secrets", new_callable=AsyncMock, return_value={"generic": "test-secret"}):
        with patch("app.services.alert_handler_service.alert_handler_service.handle", new_callable=AsyncMock):
            resp = client.post(
                "/api/v1/alerts/webhook/generic",
                json={"alert_name": "CPUThrottle", "severity": "warning", "namespace": "default"},
                headers={"X-DokOps-Webhook-Secret": "test-secret"},
            )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


def test_list_incidents_requires_auth(client):
    resp = client.get("/api/v1/alerts/incidents")
    assert resp.status_code == 401


# ── RCA concurrency setting ─────────────────────────────────────────────────────

@pytest.fixture(name="superuser_client")
def superuser_client_fixture(isolated_session):
    """TestClient authed as a superuser, sharing isolated_session's DB across requests."""
    db_url = str(isolated_session.bind.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    async def get_async_session_override():
        async with _AsyncSessionLocal() as async_session:
            yield async_session

    mock_user = User(id=1, username="admin", hashed_password="x", is_superuser=True)
    app.dependency_overrides[deps.get_async_db] = get_async_session_override
    app.dependency_overrides[deps.get_current_active_superuser] = lambda: mock_user

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()
    asyncio.run(_async_engine.dispose())


def test_get_rca_concurrency_returns_default_when_unset(superuser_client):
    resp = superuser_client.get("/api/v1/alerts/rca-concurrency")
    assert resp.status_code == 200
    assert resp.json() == {"max_concurrent_rca": 5}


def test_put_rca_concurrency_persists_value(superuser_client):
    resp = superuser_client.put("/api/v1/alerts/rca-concurrency", json={"max_concurrent_rca": 9})
    assert resp.status_code == 200
    assert resp.json() == {"status": "saved", "max_concurrent_rca": 9}

    got = superuser_client.get("/api/v1/alerts/rca-concurrency")
    assert got.json() == {"max_concurrent_rca": 9}


def test_put_rca_concurrency_rejects_non_positive(superuser_client):
    resp = superuser_client.put("/api/v1/alerts/rca-concurrency", json={"max_concurrent_rca": 0})
    assert resp.status_code == 422
