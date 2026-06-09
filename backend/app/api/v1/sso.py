from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.api import deps
from app.core.config import settings
from app.services import sso_service
from app.models.oauth_state import OAuthState

router = APIRouter()


@router.get("/providers")
def list_providers() -> list[dict]:
    """Return active SSO providers for the login page."""
    return [
        {"name": p.get_name(), "label": _provider_label(p.get_name())}
        for p in sso_service.get_active_providers()
    ]


@router.get("/{provider}/login")
def sso_login(provider: str, db: Session = Depends(deps.get_db)) -> Any:
    """Redirect browser to provider authorization URL."""
    p = sso_service.get_provider_by_name(provider)
    if not p:
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider}' not configured")
    auth_url = sso_service.begin_sso_flow(provider=p, db=db)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/{provider}/callback")
async def sso_callback(
    provider: str,
    code: str,
    state: str,
    db: Session = Depends(deps.get_db),
) -> Any:
    """Handle OIDC callback: validate, resolve role, mint DokOps JWT, redirect frontend."""
    # 1. Validate CSRF state
    state_record = db.exec(select(OAuthState).where(OAuthState.state == state)).first()
    if not state_record or state_record.provider != provider:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")
    # Capture nonce before deleting the record
    expected_nonce = state_record.nonce
    db.delete(state_record)
    db.commit()

    # 2. Get provider
    p = sso_service.get_provider_by_name(provider)
    if not p:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not configured")

    # 3. Exchange code for tokens
    try:
        tokens = await p.exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")

    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="No id_token in provider response")

    # 4. Validate JWT signature + claims
    claims = await sso_service.validate_id_token(id_token, p)

    # 4b. Validate OIDC nonce to prevent token replay attacks
    if expected_nonce:
        try:
            sso_service._assert_nonce(claims, expected_nonce)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # 5. Domain check (Google)
    if hasattr(p, "validate_domain") and not p.validate_domain(claims):
        raise HTTPException(status_code=403, detail="Email domain not allowed")

    # 6. Global domain allowlist check
    if settings.SSO_ALLOWED_DOMAINS:
        allowed = [d.strip() for d in settings.SSO_ALLOWED_DOMAINS.split(",")]
        email = claims.get("email", "")
        domain = email.split("@")[-1] if "@" in email else ""
        if domain not in allowed:
            raise HTTPException(status_code=403, detail="Email domain not in allowed list")

    # 7. Resolve role
    if hasattr(p, "resolve_google_role"):
        email = claims.get("email", "")
        role = await p.resolve_google_role(email)
    else:
        role = p.resolve_role_from_claims(claims)

    # 8. Extract identity
    external_id, username, email = p.extract_identity(claims)

    # 9. Upsert user
    user = sso_service.upsert_sso_user(
        db=db,
        provider=provider,
        external_id=external_id,
        email=email,
        username=username,
        role=role,
        refresh_token=tokens.get("refresh_token"),
        auto_provision=settings.SSO_AUTO_PROVISION,
    )

    # 10. Mint DokOps JWT and redirect to frontend
    token_data = sso_service.mint_dokops_token(user)
    from urllib.parse import urlencode
    params = urlencode({
        "token": token_data["access_token"],
        "username": token_data["username"],
        "role": token_data["role"],
        "is_superuser": str(token_data["is_superuser"]).lower(),
    })
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(url=f"{frontend_url}/auth-callback?{params}", status_code=302)


def _provider_label(name: str) -> str:
    return {
        "entra": "Microsoft Entra ID",
        "google": "Google Workspace",
        "authentik": "Authentik",
        "cognito": "AWS Cognito",
    }.get(name, name.title())
