from typing import Optional
from urllib.parse import urlencode
import httpx

from .base import OIDCProvider


class GoogleProvider(OIDCProvider):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        allowed_domain: str,
        admin_group: str,
        service_account_json: Optional[str],
        redirect_uri: str,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._allowed_domain = allowed_domain
        self._admin_group = admin_group
        self._service_account_json = service_account_json
        self._redirect_uri = redirect_uri

    def get_name(self) -> str:
        return "google"

    def get_client_id(self) -> str:
        return self._client_id

    def get_authorization_url(self, state: str, nonce: str) -> str:
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "hd": self._allowed_domain,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                },
            )
            r.raise_for_status()
            return r.json()

    def get_jwks_uri(self) -> str:
        return "https://www.googleapis.com/oauth2/v3/certs"

    def get_expected_issuer(self) -> str:
        return "https://accounts.google.com"

    def validate_domain(self, claims: dict) -> bool:
        """Return False if the token's hosted domain doesn't match config."""
        hd = claims.get("hd", "")
        email = claims.get("email", "")
        domain_from_email = email.split("@")[-1] if "@" in email else ""
        return hd == self._allowed_domain or domain_from_email == self._allowed_domain

    def resolve_role_from_claims(self, claims: dict) -> str:
        return "user"

    async def resolve_google_role(self, email: str) -> str:
        """Call Google Directory API to check group membership. Returns 'admin' or 'user'."""
        if not self._service_account_json:
            return "user"
        try:
            import json
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            sa_info = json.loads(
                open(self._service_account_json).read()
                if not self._service_account_json.strip().startswith("{")
                else self._service_account_json
            )
            creds = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=["https://www.googleapis.com/auth/admin.directory.group.member.readonly"],
                subject=email,
            )
            service = build("admin", "directory_v1", credentials=creds, cache_discovery=False)
            groups = service.groups().list(userKey=email).execute()
            group_emails = [g.get("email", "") for g in groups.get("groups", [])]
            admin_group_email = f"{self._admin_group}@{self._allowed_domain}"
            return "admin" if admin_group_email in group_emails else "user"
        except Exception:
            return "user"

    def extract_identity(self, claims: dict) -> tuple[str, str, Optional[str]]:
        external_id = claims.get("sub", "")
        email = claims.get("email", "")
        username = email or external_id
        return external_id, username, email or None
