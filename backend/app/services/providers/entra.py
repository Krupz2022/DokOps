from typing import Optional
from urllib.parse import urlencode
import httpx

from .base import OIDCProvider


class EntraProvider(OIDCProvider):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        roles_claim: str,
        admin_role: str,
        redirect_uri: str,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._tenant_id = tenant_id
        self._roles_claim = roles_claim
        self._admin_role = admin_role
        self._redirect_uri = redirect_uri

    def get_name(self) -> str:
        return "entra"

    def get_client_id(self) -> str:
        return self._client_id

    def get_authorization_url(self, state: str, nonce: str) -> str:
        base = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/authorize"
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
        }
        return f"{base}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, data=data)
            r.raise_for_status()
            return r.json()

    def get_jwks_uri(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant_id}/discovery/v2.0/keys"

    def get_expected_issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant_id}/v2.0"

    def resolve_role_from_claims(self, claims: dict) -> str:
        roles = claims.get(self._roles_claim, [])
        if isinstance(roles, str):
            roles = [roles]
        return "admin" if self._admin_role in roles else "user"

    def extract_identity(self, claims: dict) -> tuple[str, str, Optional[str]]:
        external_id = claims.get("oid") or claims.get("sub", "")
        email = claims.get("email") or claims.get("preferred_username", "")
        username = email or external_id
        return external_id, username, email or None
