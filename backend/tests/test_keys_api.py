import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import patch

from app.models.user import User
from app.models.activation_key import ActivationKey, KeyBlueprint  # noqa: F401
from app.models.blueprint import Blueprint

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
            resp = client.post("/api/v1/login/access-token", data={"username": "admin", "password": "x"})
            client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})
            yield client
            client.headers.pop("Authorization", None)


def test_create_key_returns_value_once_then_lists_without_it(admin_client, session):
    bp = Blueprint(name="iis", yaml_body="resources: []")
    session.add(bp); session.commit(); session.refresh(bp)

    resp = admin_client.post("/api/v1/keys/", json={
        "name": "win-web", "run_on_attach": True, "blueprint_ids": [bp.id],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"]                       # plaintext returned ONCE
    kid = body["key"]["id"]

    lst = admin_client.get("/api/v1/keys/").json()
    assert any(k["id"] == kid for k in lst)
    assert all("value" not in k for k in lst)  # never lists the secret

    detail = admin_client.get(f"/api/v1/keys/{kid}").json()
    assert detail["blueprint_ids"] == [bp.id]
    assert detail["run_on_attach"] is True


def test_update_replaces_blueprint_set_and_delete_cascades(admin_client, session):
    b1 = Blueprint(name="a", yaml_body="resources: []"); b2 = Blueprint(name="b", yaml_body="resources: []")
    session.add(b1); session.add(b2); session.commit(); session.refresh(b1); session.refresh(b2)
    kid = admin_client.post("/api/v1/keys/", json={"name": "k", "blueprint_ids": [b1.id]}).json()["key"]["id"]
    admin_client.put(f"/api/v1/keys/{kid}", json={"name": "k", "run_on_attach": False, "enabled": True, "blueprint_ids": [b2.id]})
    assert admin_client.get(f"/api/v1/keys/{kid}").json()["blueprint_ids"] == [b2.id]
    assert admin_client.delete(f"/api/v1/keys/{kid}").status_code == 200
    assert admin_client.get(f"/api/v1/keys/{kid}").status_code == 404
