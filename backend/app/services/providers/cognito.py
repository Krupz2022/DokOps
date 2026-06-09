from typing import Optional
from urllib.parse import urlencode
import httpx

from .base import OIDCProvider


class CognitoProvider(OIDCProvider):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_pool_id: str,
        region: str,
        roles_claim: str,
        admin_role: str,
        redirect_uri: str,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_pool_id = user_pool_id
        self._region = region
        self._roles_claim = roles_claim
        self._admin_role = admin_role
        self._redirect_uri = redirect_uri
        self._domain = f"https://{user_pool_id}.auth.{region}.amazoncognito.com"

    def get_name(self) -> str:
        return "cognito"

    def get_client_id(self) -> str:
        return self._client_id

    def get_authorization_url(self, state: str, nonce: str) -> str:
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": "openid email profile",
            "state": state,
        }
        return f"{self._domain}/oauth2/authorize?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        import base64
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self._domain}/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                },
                headers={"Authorization": f"Basic {credentials}"},
            )
            r.raise_for_status()
            return r.json()

    def get_jwks_uri(self) -> str:
        return f"https://cognito-idp.{self._region}.amazonaws.com/{self._user_pool_id}/.well-known/jwks.json"

    def get_expected_issuer(self) -> str:
        return f"https://cognito-idp.{self._region}.amazonaws.com/{self._user_pool_id}"

    def resolve_role_from_claims(self, claims: dict) -> str:
        groups = claims.get(self._roles_claim, [])
        if isinstance(groups, str):
            groups = [groups]
        return "admin" if self._admin_role in groups else "user"

    def extract_identity(self, claims: dict) -> tuple[str, str, Optional[str]]:
        external_id = claims.get("sub", "")
        email = claims.get("email", "")
        username = claims.get("username") or email or external_id
        return external_id, username, email or None
