# backend/tests/test_blueprints_api.py
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import patch

from app.models.user import User
from app.models.blueprint import Blueprint, BlueprintSource, BlueprintAssignment  # noqa: F401
from app.models.minion import Minion  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401

_FAKE_HASH = "FAKE_BCRYPT_HASH_FOR_TESTING"


@pytest.fixture(name="session")
def session_fixture(isolated_session):
    return isolated_session


@pytest.fixture(name="client")
def client_fixture(isolated_client):
    return isolated_client


@pytest.fixture(name="admin_client")
def admin_client_fixture(session: Session, client: TestClient):
    with patch("app.core.security.get_password_hash", return_value=_FAKE_HASH):
        with patch("app.core.security.verify_password", return_value=True):
            session.add(User(username="admin", hashed_password=_FAKE_HASH,
                             is_superuser=True, role="admin", is_active=True))
            session.commit()
            resp = client.post("/api/v1/login/access-token",
                               data={"username": "admin", "password": "x"})
            client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})
            yield client
            client.headers.pop("Authorization", None)


def test_create_and_get_state_file(admin_client):
    resp = admin_client.post("/api/v1/blueprints/", json={"name": "nginx", "yaml_body": "resources: []"})
    assert resp.status_code == 200
    sid = resp.json()["id"]
    got = admin_client.get(f"/api/v1/blueprints/{sid}")
    assert got.status_code == 200
    assert got.json()["name"] == "nginx"


def test_upsert_source_and_assignment(admin_client):
    sid = admin_client.post("/api/v1/blueprints/", json={"name": "web", "yaml_body": "resources: []"}).json()["id"]
    s = admin_client.put(f"/api/v1/blueprints/{sid}/sources/nginx.conf", json={"content": "server {}"})
    assert s.status_code == 200
    a = admin_client.post(f"/api/v1/blueprints/{sid}/assignments", json={"scope_type": "minion", "scope_id": "web-01"})
    assert a.status_code == 200
    assert a.json()["scope_id"] == "web-01"


def test_list_sources_and_assignments(admin_client):
    sid = admin_client.post("/api/v1/blueprints/", json={"name": "web", "yaml_body": "resources: []"}).json()["id"]
    admin_client.put(f"/api/v1/blueprints/{sid}/sources/nginx.conf", json={"content": "server {}"})
    admin_client.post(f"/api/v1/blueprints/{sid}/assignments", json={"scope_type": "minion", "scope_id": "web-01"})

    srcs = admin_client.get(f"/api/v1/blueprints/{sid}/sources")
    assert srcs.status_code == 200
    assert [s["name"] for s in srcs.json()] == ["nginx.conf"]

    asns = admin_client.get(f"/api/v1/blueprints/{sid}/assignments")
    assert asns.status_code == 200
    assert asns.json()[0]["scope_id"] == "web-01"


def test_list_sources_404_for_missing_blueprint(admin_client):
    assert admin_client.get("/api/v1/blueprints/nope/sources").status_code == 404
