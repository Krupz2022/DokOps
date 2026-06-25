# backend/tests/test_binary_source_api.py
"""Tests for Task 4: binary upload + download endpoints.

TDD: written before implementation so they initially fail.

Endpoints under test:
  POST /api/v1/blueprints/{blueprint_id}/sources/{name}/upload   (superuser)
  GET  /api/v1/blueprints/{blueprint_id}/sources                  (enriched list)
  GET  /minion/source/{source_id}?token=<key>                     (minion download)
"""
import base64
import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import patch

from app.models.user import User
from app.models.blueprint import Blueprint, BlueprintSource  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401

_FAKE_HASH = "FAKE_BCRYPT_HASH_FOR_TESTING"
_VALID_TOKEN = "s3cr3t-enroll-token"
_WRONG_TOKEN = "wrong-token"


# ---------------------------------------------------------------------------
# Shared fixtures (delegate to conftest isolated_session / isolated_client)
# ---------------------------------------------------------------------------

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


@pytest.fixture(name="blueprint_id")
def blueprint_id_fixture(admin_client):
    """Create a blueprint and return its id."""
    resp = admin_client.post("/api/v1/blueprints/", json={"name": "bin-test", "yaml_body": "resources: []"})
    assert resp.status_code == 200
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Upload endpoint tests
# ---------------------------------------------------------------------------

def test_upload_binary_source(admin_client, blueprint_id):
    """Upload a small binary file; endpoint stores it as base64."""
    raw = b"\x00\x01\x02\x03BIN"
    resp = admin_client.post(
        f"/api/v1/blueprints/{blueprint_id}/sources/data.bin/upload",
        files={"file": ("data.bin", io.BytesIO(raw), "application/octet-stream")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["encoding"] == "base64"
    assert base64.b64decode(body["content"]) == raw


def test_upload_rejects_oversized_file(admin_client, blueprint_id):
    """Files over 50 MB must be rejected with 413."""
    big = b"x" * (50 * 1024 * 1024 + 1)
    resp = admin_client.post(
        f"/api/v1/blueprints/{blueprint_id}/sources/huge.bin/upload",
        files={"file": ("huge.bin", io.BytesIO(big), "application/octet-stream")},
    )
    assert resp.status_code == 413


def test_upload_404_for_missing_blueprint(admin_client):
    """Upload to a non-existent blueprint returns 404."""
    raw = b"hello"
    resp = admin_client.post(
        "/api/v1/blueprints/no-such-id/sources/x.bin/upload",
        files={"file": ("x.bin", io.BytesIO(raw), "application/octet-stream")},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# list_sources enriched response tests
# ---------------------------------------------------------------------------

def test_list_sources_text_has_content(admin_client, blueprint_id):
    """Text sources include content field and a utf-8 byte size."""
    admin_client.put(
        f"/api/v1/blueprints/{blueprint_id}/sources/nginx.conf",
        json={"content": "server {}"},
    )
    srcs = admin_client.get(f"/api/v1/blueprints/{blueprint_id}/sources").json()
    assert len(srcs) == 1
    s = srcs[0]
    assert s["name"] == "nginx.conf"
    assert s["content"] == "server {}"
    assert s["encoding"] == "utf-8"
    assert s["size"] == len("server {}".encode("utf-8"))


def test_list_sources_binary_hides_content(admin_client, blueprint_id):
    """Binary (base64) sources have content='' and size=decoded byte length."""
    raw = b"\x00\x01\x02BIN"
    admin_client.post(
        f"/api/v1/blueprints/{blueprint_id}/sources/data.bin/upload",
        files={"file": ("data.bin", io.BytesIO(raw), "application/octet-stream")},
    )
    srcs = admin_client.get(f"/api/v1/blueprints/{blueprint_id}/sources").json()
    s = next(x for x in srcs if x["name"] == "data.bin")
    assert s["content"] == ""
    assert s["encoding"] == "base64"
    assert s["size"] == len(raw)


# ---------------------------------------------------------------------------
# /minion/source/{source_id} download endpoint tests
# ---------------------------------------------------------------------------

def _create_binary_source(session, blueprint_id, name="asset.bin", raw=b"\xDE\xAD\xBE\xEF"):
    """Directly insert a BlueprintSource and return its id."""
    src = BlueprintSource(
        blueprint_id=blueprint_id,
        name=name,
        content=base64.b64encode(raw).decode(),
        encoding="base64",
    )
    session.add(src)
    session.commit()
    session.refresh(src)
    return src.id, raw


def test_download_no_token_returns_401(admin_client, session, blueprint_id):
    """A request with no token must return 401."""
    sid, _ = _create_binary_source(session, blueprint_id)
    assert admin_client.get(f"/minion/source/{sid}").status_code == 401


def test_download_wrong_token_returns_401(admin_client, session, blueprint_id):
    """A request with the wrong token must return 401."""
    sid, _ = _create_binary_source(session, blueprint_id)
    with patch("app.main.get_auto_accept_key_hash", return_value="sha256_placeholder"):
        with patch("app.main.verify_token", return_value=False):
            resp = admin_client.get(f"/minion/source/{sid}?token={_WRONG_TOKEN}")
    assert resp.status_code == 401


def test_download_valid_token_returns_raw_bytes(admin_client, session, blueprint_id):
    """A valid token returns the exact raw binary bytes."""
    raw = b"\xDE\xAD\xBE\xEF\xCA\xFE"
    sid, _ = _create_binary_source(session, blueprint_id, raw=raw)
    with patch("app.main.get_auto_accept_key_hash", return_value="some_hash"):
        with patch("app.main.verify_token", return_value=True):
            resp = admin_client.get(f"/minion/source/{sid}?token={_VALID_TOKEN}")
    assert resp.status_code == 200
    assert resp.content == raw
    assert resp.headers["content-type"] == "application/octet-stream"


def test_download_missing_source_returns_404(admin_client):
    """Requesting a non-existent source id returns 404."""
    with patch("app.main.get_auto_accept_key_hash", return_value="some_hash"):
        with patch("app.main.verify_token", return_value=True):
            resp = admin_client.get(f"/minion/source/does-not-exist?token={_VALID_TOKEN}")
    assert resp.status_code == 404


def test_download_text_source_returns_utf8_bytes(admin_client, session, blueprint_id):
    """Text (utf-8 encoded) sources are returned as their utf-8 byte sequence."""
    src = BlueprintSource(
        blueprint_id=blueprint_id,
        name="readme.txt",
        content="hello world",
        encoding="utf-8",
    )
    session.add(src)
    session.commit()
    session.refresh(src)
    with patch("app.main.get_auto_accept_key_hash", return_value="some_hash"):
        with patch("app.main.verify_token", return_value=True):
            resp = admin_client.get(f"/minion/source/{src.id}?token={_VALID_TOKEN}")
    assert resp.status_code == 200
    assert resp.content == b"hello world"
