# backend/tests/test_sso.py
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from sqlmodel import SQLModel, create_engine, Session, select
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.oauth_state import OAuthState
from app.models.user import User


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_oauth_state_create(session: Session):
    state = OAuthState(state="abc123", nonce="nonce456", provider="entra")
    session.add(state)
    session.commit()
    session.refresh(state)
    assert state.id is not None
    assert state.provider == "entra"
    assert isinstance(state.created_at, datetime)


def test_sso_config_defaults():
    from app.core.config import Settings
    s = Settings()
    assert s.SSO_ENABLED is False
    assert s.SSO_AUTO_PROVISION is True
    assert s.SSO_ALLOWED_DOMAINS == ""
    assert s.FRONTEND_URL == "http://localhost:5173"
    assert s.BACKEND_PUBLIC_URL == "http://localhost:8000"


def test_user_sso_fields(session: Session):
    from app.models.user import User
    user = User(
        username="alice@company.com",
        email="alice@company.com",
        provider="entra",
        external_id="aad-obj-id-123",
        role="user",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.hashed_password is None
    assert user.provider == "entra"
    assert user.external_id == "aad-obj-id-123"


# ---------------------------------------------------------------------------
# Task 4: Entra Provider Tests
# ---------------------------------------------------------------------------

def test_entra_build_auth_url():
    from app.services.providers.entra import EntraProvider
    provider = EntraProvider(
        client_id="client-id",
        client_secret="secret",
        tenant_id="tenant-abc",
        roles_claim="roles",
        admin_role="Admin",
        redirect_uri="http://localhost:8000/api/v1/auth/sso/entra/callback",
    )
    url = provider.get_authorization_url(state="state123", nonce="nonce456")
    assert "client-id" in url
    assert "tenant-abc" in url
    assert "state123" in url
    assert "openid" in url


@pytest.mark.asyncio
async def test_entra_exchange_code():
    from app.services.providers.entra import EntraProvider
    provider = EntraProvider(
        client_id="client-id",
        client_secret="secret",
        tenant_id="tenant-abc",
        roles_claim="roles",
        admin_role="Admin",
        redirect_uri="http://localhost:8000/api/v1/auth/sso/entra/callback",
    )
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "access_token": "at",
        "id_token": "idt",
        "refresh_token": "rt",
    }
    mock_response.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        tokens = await provider.exchange_code("code123")
    assert tokens["refresh_token"] == "rt"


def test_entra_resolve_role_admin():
    from app.services.providers.entra import EntraProvider
    provider = EntraProvider(
        client_id="c", client_secret="s", tenant_id="t",
        roles_claim="roles", admin_role="Admin",
        redirect_uri="http://x/cb",
    )
    claims = {"roles": ["Admin"], "email": "a@b.com", "oid": "obj123"}
    role = provider.resolve_role_from_claims(claims)
    assert role == "admin"


def test_entra_resolve_role_user_fallback():
    from app.services.providers.entra import EntraProvider
    provider = EntraProvider(
        client_id="c", client_secret="s", tenant_id="t",
        roles_claim="roles", admin_role="Admin",
        redirect_uri="http://x/cb",
    )
    role = provider.resolve_role_from_claims({})
    assert role == "user"


# ---------------------------------------------------------------------------
# Task 5: Google Provider Tests
# ---------------------------------------------------------------------------

def test_google_build_auth_url():
    from app.services.providers.google import GoogleProvider
    provider = GoogleProvider(
        client_id="google-client-id",
        client_secret="secret",
        allowed_domain="company.com",
        admin_group="dokops-admins",
        service_account_json=None,
        redirect_uri="http://localhost:8000/api/v1/auth/sso/google/callback",
    )
    url = provider.get_authorization_url(state="s1", nonce="n1")
    assert "accounts.google.com" in url
    assert "google-client-id" in url
    assert "hd=company.com" in url


def test_google_resolve_role_no_group():
    from app.services.providers.google import GoogleProvider
    provider = GoogleProvider(
        client_id="c", client_secret="s",
        allowed_domain="company.com",
        admin_group="dokops-admins",
        service_account_json=None,
        redirect_uri="http://x/cb",
    )
    role = provider.resolve_role_from_claims({"email": "alice@company.com"})
    assert role == "user"


def test_google_rejects_wrong_domain():
    from app.services.providers.google import GoogleProvider
    provider = GoogleProvider(
        client_id="c", client_secret="s",
        allowed_domain="company.com",
        admin_group="dokops-admins",
        service_account_json=None,
        redirect_uri="http://x/cb",
    )
    claims = {"email": "hacker@gmail.com", "hd": "gmail.com"}
    is_valid = provider.validate_domain(claims)
    assert is_valid is False


# ---------------------------------------------------------------------------
# Task 6: Authentik Provider Tests
# ---------------------------------------------------------------------------

def test_authentik_build_auth_url():
    from app.services.providers.authentik import AuthentikProvider
    provider = AuthentikProvider(
        client_id="ak-client",
        client_secret="secret",
        base_url="https://auth.company.com",
        roles_claim="roles",
        admin_role="Admin",
        redirect_uri="http://localhost:8000/api/v1/auth/sso/authentik/callback",
    )
    url = provider.get_authorization_url(state="s1", nonce="n1")
    assert "auth.company.com" in url
    assert "ak-client" in url


def test_authentik_resolve_role():
    from app.services.providers.authentik import AuthentikProvider
    provider = AuthentikProvider(
        client_id="c", client_secret="s",
        base_url="https://auth.company.com",
        roles_claim="roles", admin_role="Admin",
        redirect_uri="http://x/cb",
    )
    assert provider.resolve_role_from_claims({"roles": ["Admin"]}) == "admin"
    assert provider.resolve_role_from_claims({"roles": ["User"]}) == "user"
    assert provider.resolve_role_from_claims({}) == "user"


# ---------------------------------------------------------------------------
# Task 7: AWS Cognito Provider Tests
# ---------------------------------------------------------------------------

def test_cognito_build_auth_url():
    from app.services.providers.cognito import CognitoProvider
    provider = CognitoProvider(
        client_id="cog-client",
        client_secret="secret",
        user_pool_id="us-east-1_abc123",
        region="us-east-1",
        roles_claim="cognito:groups",
        admin_role="Admin",
        redirect_uri="http://localhost:8000/api/v1/auth/sso/cognito/callback",
    )
    url = provider.get_authorization_url(state="s1", nonce="n1")
    assert "amazoncognito.com" in url or "us-east-1" in url
    assert "cog-client" in url


def test_cognito_resolve_role():
    from app.services.providers.cognito import CognitoProvider
    provider = CognitoProvider(
        client_id="c", client_secret="s",
        user_pool_id="us-east-1_abc",
        region="us-east-1",
        roles_claim="cognito:groups",
        admin_role="Admin",
        redirect_uri="http://x/cb",
    )
    assert provider.resolve_role_from_claims({"cognito:groups": ["Admin", "User"]}) == "admin"
    assert provider.resolve_role_from_claims({"cognito:groups": ["User"]}) == "user"
    assert provider.resolve_role_from_claims({}) == "user"


# ---------------------------------------------------------------------------
# Task 8: SSO Service Tests
# ---------------------------------------------------------------------------

def test_get_active_providers_empty():
    from app.services.sso_service import get_active_providers
    from app.core.config import Settings
    s = Settings()
    providers = get_active_providers(s)
    assert providers == []


def test_get_active_providers_with_entra(monkeypatch):
    from app.services.sso_service import get_active_providers
    from app.core.config import Settings
    monkeypatch.setenv("ENTRA_CLIENT_ID", "eid")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "esec")
    monkeypatch.setenv("ENTRA_TENANT_ID", "etid")
    s = Settings()
    providers = get_active_providers(s)
    names = [p.get_name() for p in providers]
    assert "entra" in names


def test_begin_sso_flow_stores_state(session: Session):
    from app.services.sso_service import begin_sso_flow
    from app.services.providers.entra import EntraProvider
    from app.models.oauth_state import OAuthState

    provider = EntraProvider(
        client_id="c", client_secret="s", tenant_id="t",
        roles_claim="roles", admin_role="Admin",
        redirect_uri="http://x/cb",
    )
    url = begin_sso_flow(provider=provider, db=session)
    assert "https://login.microsoftonline.com" in url
    states = session.exec(select(OAuthState)).all()
    assert len(states) == 1
    assert states[0].provider == "entra"


def test_upsert_user_creates_new(session: Session):
    from app.services.sso_service import upsert_sso_user
    user = upsert_sso_user(
        db=session,
        provider="entra",
        external_id="oid-abc",
        email="alice@company.com",
        username="alice@company.com",
        role="user",
        refresh_token="rt123",
        auto_provision=True,
    )
    assert user.id is not None
    assert user.provider == "entra"
    assert user.role == "user"


def test_upsert_user_rejected_when_provision_off(session: Session):
    from app.services.sso_service import upsert_sso_user
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        upsert_sso_user(
            db=session,
            provider="entra",
            external_id="oid-xyz",
            email="stranger@company.com",
            username="stranger@company.com",
            role="user",
            refresh_token="rt",
            auto_provision=False,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Task 9: SSO Router Tests
# ---------------------------------------------------------------------------

@pytest.fixture(name="client")
def client_fixture(session: Session):
    from app.main import app
    from app.api import deps
    app.dependency_overrides[deps.get_db] = lambda: session
    client = TestClient(app, follow_redirects=False)
    yield client
    app.dependency_overrides.clear()


def test_providers_endpoint_empty(client: TestClient):
    r = client.get("/api/v1/auth/sso/providers")
    assert r.status_code == 200
    assert r.json() == []


def test_login_redirect_unknown_provider(client: TestClient):
    r = client.get("/api/v1/auth/sso/unknown/login")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Task 10: System Status + Auth Guard Tests
# ---------------------------------------------------------------------------

def test_system_status_has_sso_enabled(client: TestClient):
    r = client.get("/api/v1/system/status")
    assert r.status_code == 200
    assert "sso_enabled" in r.json()
    assert r.json()["sso_enabled"] is False


def test_register_blocked_when_sso_enabled(client: TestClient):
    import app.core.config as cfg_module
    original = cfg_module.settings.SSO_ENABLED
    cfg_module.settings.SSO_ENABLED = True
    try:
        r = client.post("/api/v1/register", json={"username": "x", "password": "y"})
        assert r.status_code == 403
    finally:
        cfg_module.settings.SSO_ENABLED = original
