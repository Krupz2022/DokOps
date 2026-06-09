# backend/tests/test_alerts_api.py
import json
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from unittest.mock import patch, AsyncMock

from app.main import app
from app.core.db import engine as real_engine
from app.models.alert_incident import AlertIncident
from datetime import datetime, timezone


@pytest.fixture
def client():
    return TestClient(app)


def test_webhook_unknown_source_returns_404(client):
    resp = client.post("/api/v1/alerts/webhook/unknown_source", json={})
    assert resp.status_code == 404


def test_webhook_unconfigured_source_returns_503(client):
    # No secret configured in test DB → 503
    with patch("app.services.webhook_security._get_secrets", return_value={}):
        resp = client.post(
            "/api/v1/alerts/webhook/generic",
            json={"alert_name": "Test", "severity": "warning"},
            headers={"X-DokOps-Webhook-Secret": "some-token"},
        )
    assert resp.status_code == 503


def test_webhook_wrong_secret_returns_401(client):
    with patch("app.services.webhook_security._get_secrets", return_value={"generic": "correct-secret"}):
        resp = client.post(
            "/api/v1/alerts/webhook/generic",
            json={"alert_name": "Test", "severity": "warning"},
            headers={"X-DokOps-Webhook-Secret": "wrong-secret"},
        )
    assert resp.status_code == 401


def test_webhook_valid_request_returns_202(client):
    with patch("app.services.webhook_security._get_secrets", return_value={"generic": "test-secret"}):
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
