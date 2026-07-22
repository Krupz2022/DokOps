"""SSO callback must replace the auth cookie, not leave a previous user's cookie in place.

Regression: password login sets an httpOnly `access_token` cookie and
deps.get_current_user prefers the cookie over the Authorization header.  The SSO
callback only handed the token back via the redirect URL, so a browser that had
previously logged in as the setup admin kept authenticating as that admin after
signing in through Entra.
"""
import pytest
from jose import jwt

import app.main  # noqa: F401  — registers every SQLModel table before create_all
from app.core import security
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models.oauth_state import OAuthState
from app.models.user import User


class _FakeProvider:
    def get_name(self):
        return "entra"

    async def exchange_code(self, code):
        return {"id_token": "fake", "refresh_token": None}

    def resolve_role_from_claims(self, claims):
        return "user"

    def extract_identity(self, claims):
        return "oid-123", "sso.user@example.com", "sso.user@example.com"


@pytest.fixture(name="sso_client")
def sso_client_fixture(isolated_client, isolated_session, monkeypatch):
    from app.services import sso_service

    monkeypatch.setattr(sso_service, "get_provider_by_name", lambda name: _FakeProvider())

    async def _fake_validate(id_token, provider):
        return {"nonce": "n-1", "email": "sso.user@example.com", "oid": "oid-123"}

    monkeypatch.setattr(sso_service, "validate_id_token", _fake_validate)
    monkeypatch.setattr(settings, "SSO_AUTO_PROVISION", True)
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "")

    isolated_session.add(OAuthState(state="s-1", nonce="n-1", provider="entra"))
    isolated_session.add(User(
        username="setup-admin",
        email="admin@example.com",
        hashed_password=security.get_password_hash("x"),
        role="admin",
        is_superuser=True,
        is_active=True,
    ))
    isolated_session.commit()
    return isolated_client


def test_callback_overwrites_stale_admin_cookie(sso_client):
    # Browser still holds the setup admin's httpOnly cookie from an earlier login.
    sso_client.cookies.set("access_token", security.create_access_token("setup-admin"))

    resp = sso_client.get(
        "/api/v1/auth/sso/entra/callback",
        params={"code": "c", "state": "s-1"},
        follow_redirects=False,
    )

    assert resp.status_code == 302, resp.text
    cookie = resp.cookies.get("access_token")
    assert cookie, "SSO callback must set the access_token cookie"
    claims = jwt.decode(cookie, settings.AUTH_SECRET_KEY, algorithms=[ALGORITHM])
    assert claims["sub"] == "sso.user@example.com"


def test_sso_user_is_not_admin(sso_client):
    sso_client.cookies.set("access_token", security.create_access_token("setup-admin"))
    sso_client.get(
        "/api/v1/auth/sso/entra/callback",
        params={"code": "c", "state": "s-1"},
        follow_redirects=False,
    )

    status = sso_client.get("/api/v1/system/status")
    assert status.json()["is_superuser"] is False
