import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from jose import jwt, JWTError
from sqlmodel import Session, select
import httpx

from app.core.config import Settings, settings
from app.core.security import create_access_token
from app.models.oauth_state import OAuthState
from app.models.user import User
from app.core.encryption import encrypt
from app.services.providers.base import OIDCProvider
from app.services.providers.entra import EntraProvider
from app.services.providers.google import GoogleProvider
from app.services.providers.authentik import AuthentikProvider
from app.services.providers.cognito import CognitoProvider


def _make_redirect_uri(provider_name: str) -> str:
    backend_url = settings.BACKEND_PUBLIC_URL.rstrip("/")
    return f"{backend_url}/api/v1/auth/sso/{provider_name}/callback"


def get_active_providers(cfg: Settings = settings) -> list[OIDCProvider]:
    providers: list[OIDCProvider] = []

    if cfg.ENTRA_CLIENT_ID and cfg.ENTRA_CLIENT_SECRET and cfg.ENTRA_TENANT_ID:
        providers.append(EntraProvider(
            client_id=cfg.ENTRA_CLIENT_ID,
            client_secret=cfg.ENTRA_CLIENT_SECRET,
            tenant_id=cfg.ENTRA_TENANT_ID,
            roles_claim=cfg.ENTRA_ROLES_CLAIM,
            admin_role=cfg.ENTRA_ADMIN_ROLE,
            redirect_uri=_make_redirect_uri("entra"),
        ))

    if cfg.GOOGLE_CLIENT_ID and cfg.GOOGLE_CLIENT_SECRET and cfg.GOOGLE_ALLOWED_DOMAIN:
        providers.append(GoogleProvider(
            client_id=cfg.GOOGLE_CLIENT_ID,
            client_secret=cfg.GOOGLE_CLIENT_SECRET,
            allowed_domain=cfg.GOOGLE_ALLOWED_DOMAIN,
            admin_group=cfg.GOOGLE_ADMIN_GROUP,
            service_account_json=cfg.GOOGLE_SERVICE_ACCOUNT_JSON,
            redirect_uri=_make_redirect_uri("google"),
        ))

    if cfg.AUTHENTIK_CLIENT_ID and cfg.AUTHENTIK_CLIENT_SECRET and cfg.AUTHENTIK_BASE_URL:
        providers.append(AuthentikProvider(
            client_id=cfg.AUTHENTIK_CLIENT_ID,
            client_secret=cfg.AUTHENTIK_CLIENT_SECRET,
            base_url=cfg.AUTHENTIK_BASE_URL,
            roles_claim=cfg.AUTHENTIK_ROLES_CLAIM,
            admin_role=cfg.AUTHENTIK_ADMIN_ROLE,
            redirect_uri=_make_redirect_uri("authentik"),
        ))

    if (cfg.COGNITO_CLIENT_ID and cfg.COGNITO_CLIENT_SECRET
            and cfg.COGNITO_USER_POOL_ID and cfg.COGNITO_REGION):
        providers.append(CognitoProvider(
            client_id=cfg.COGNITO_CLIENT_ID,
            client_secret=cfg.COGNITO_CLIENT_SECRET,
            user_pool_id=cfg.COGNITO_USER_POOL_ID,
            region=cfg.COGNITO_REGION,
            roles_claim=cfg.COGNITO_ROLES_CLAIM,
            admin_role=cfg.COGNITO_ADMIN_ROLE,
            redirect_uri=_make_redirect_uri("cognito"),
        ))

    return providers


def get_provider_by_name(name: str) -> Optional[OIDCProvider]:
    for p in get_active_providers():
        if p.get_name() == name:
            return p
    return None


def begin_sso_flow(provider: OIDCProvider, db: Session) -> str:
    """Store CSRF state, return provider authorization URL."""
    _purge_old_states(db)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    db.add(OAuthState(state=state, nonce=nonce, provider=provider.get_name()))
    db.commit()
    return provider.get_authorization_url(state=state, nonce=nonce)


def _purge_old_states(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    old = db.exec(select(OAuthState).where(OAuthState.created_at < cutoff)).all()
    for s in old:
        db.delete(s)
    db.commit()


async def fetch_jwks(jwks_uri: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(jwks_uri)
        r.raise_for_status()
        return r.json()


_VALID_SSO_ROLES = frozenset({"admin", "user"})


def _safe_role(role) -> str:
    """Return role if it is in the known-safe allowlist, otherwise default to 'user'.
    Prevents SSO providers from granting arbitrary roles via claims."""
    if role in _VALID_SSO_ROLES:
        return role
    return "user"


def _assert_nonce(claims: dict, expected_nonce: str) -> None:
    """Raise ValueError if the ID token nonce doesn't match the expected value.
    Guards against OIDC token replay attacks."""
    token_nonce = claims.get("nonce")
    if not token_nonce or token_nonce != expected_nonce:
        raise ValueError(
            f"OIDC nonce mismatch: expected {expected_nonce!r}, got {token_nonce!r}"
        )


async def validate_id_token(id_token: str, provider: OIDCProvider) -> dict:
    jwks = await fetch_jwks(provider.get_jwks_uri())
    try:
        claims = jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256"],
            audience=provider.get_client_id(),
            issuer=provider.get_expected_issuer(),
            options={"verify_at_hash": False},
        )
        return claims
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")


def upsert_sso_user(
    db: Session,
    provider: str,
    external_id: str,
    email: Optional[str],
    username: str,
    role: str,
    refresh_token: Optional[str],
    auto_provision: bool,
) -> User:
    # 1. Match by provider + external_id
    user = db.exec(
        select(User).where(User.provider == provider, User.external_id == external_id)
    ).first()

    # 2. Fallback: match by email
    if not user and email:
        user = db.exec(select(User).where(User.email == email)).first()

    if user:
        # Preserve role/is_superuser set locally by an admin — only update on first provision.
        # SSO claims should not demote a user that was manually promoted (or vice versa).
        user.external_id = external_id
        user.provider = provider
        user.provider_refresh_token = encrypt(refresh_token) if refresh_token else None
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    if not auto_provision:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access not provisioned. Contact your DokOps administrator.",
        )

    safe = _safe_role(role)
    user = User(
        username=username,
        email=email,
        provider=provider,
        external_id=external_id,
        role=safe,
        is_superuser=(safe == "admin"),
        is_active=True,
        provider_refresh_token=encrypt(refresh_token) if refresh_token else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def mint_dokops_token(user: User) -> dict:
    token = create_access_token(subject=user.username, expires_delta=timedelta(minutes=60))
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "is_superuser": user.is_superuser,
        "role": user.role,
    }
