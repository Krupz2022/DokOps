# backend/tests/test_blueprint_api.py
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import patch

from app.models.user import User
from app.models.minion import Minion
from app.models.blueprint import Blueprint, BlueprintAssignment, BlueprintRun, ResourceResult  # noqa: F401
from app.models.patch import Organisation, MinionGroup, MinionGroupMember  # noqa: F401
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
            session.add(Minion(id="web-01", hostname="web-01", status="active"))
            session.commit()
            resp = client.post("/api/v1/login/access-token",
                               data={"username": "admin", "password": "x"})
            client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})
            yield client
            client.headers.pop("Authorization", None)


def test_apply_requires_god_mode(admin_client):
    # God mode OFF -> test=False rejected with 403
    with patch("app.api.deps.is_god_mode_active", return_value=False):
        resp = admin_client.post("/api/v1/minions/web-01/blueprint/run", json={"test": False})
    assert resp.status_code == 403


def test_dry_run_open_and_dispatches(admin_client):
    async def fake_dispatch(minion_id, run_id, states, sources, test, timeout=300):
        return {"results": []}
    with patch("app.services.minion_service.manager.dispatch_blueprint", side_effect=fake_dispatch):
        with patch("app.services.minion_service.manager.is_connected", return_value=True):
            resp = admin_client.post("/api/v1/minions/web-01/blueprint/run", json={"test": True})
    assert resp.status_code == 200
    assert "run_id" in resp.json()


def test_run_with_resource_ids_filters_and_orders(admin_client, session):
    # web-01 compiles two resources; running with an explicit ordered subset
    # must dispatch only those, in the requested order.
    yaml_body = (
        "resources:\n"
        "  - id: vault-pkg\n    type: pkg\n"
        "  - id: vault-un\n    type: pkg\n"
    )
    bp = Blueprint(name="vault", yaml_body=yaml_body)
    session.add(bp)
    session.commit()
    session.refresh(bp)
    session.add(BlueprintAssignment(blueprint_id=bp.id, scope_type="minion", scope_id="web-01"))
    session.commit()

    captured = {}
    async def fake_dispatch(minion_id, run_id, states, sources, test, timeout=300):
        captured["states"] = states
        return {"results": []}
    with patch("app.services.minion_service.manager.dispatch_blueprint", side_effect=fake_dispatch):
        with patch("app.services.minion_service.manager.is_connected", return_value=True):
            resp = admin_client.post(
                "/api/v1/minions/web-01/blueprint/run",
                json={"test": True, "resource_ids": ["vault-un"]},
            )
    assert resp.status_code == 200
    assert [s["id"] for s in captured["states"]] == ["vault-un"]


def test_preview_returns_states(admin_client):
    resp = admin_client.get("/api/v1/minions/web-01/blueprint")
    assert resp.status_code == 200
    assert "resources" in resp.json() and "sources" in resp.json()


def test_run_returns_immediately_without_blocking(admin_client):
    # dispatch is fire-and-forget: the POST must return run_id without awaiting agent results
    called = {}
    async def fake_dispatch(minion_id, run_id, states, sources, test):
        called["run_id"] = run_id  # returns immediately, no result await
    with patch("app.services.minion_service.manager.dispatch_blueprint", side_effect=fake_dispatch):
        with patch("app.services.minion_service.manager.is_connected", return_value=True):
            resp = admin_client.post("/api/v1/minions/web-01/blueprint/run", json={"test": True})
    assert resp.status_code == 200
    assert resp.json()["run_id"] == called["run_id"]


def test_stream_endpoint_emits_buffered_events(admin_client):
    from app.services.minion_service import run_hub
    run_hub.publish("run-xyz", {"kind": "resource_start", "id": "a"})
    run_hub.publish("run-xyz", {"kind": "done", "results": []})
    # token via query param (EventSource style)
    import re
    tok = admin_client.headers["Authorization"].split()[1]
    with admin_client.stream("GET", f"/api/v1/minions/blueprint/runs/run-xyz/stream?token={tok}") as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())
    assert "resource_start" in body and '"kind": "done"' in body.replace(" ", "") or "done" in body
