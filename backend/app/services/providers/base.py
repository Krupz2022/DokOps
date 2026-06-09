from abc import ABC, abstractmethod
from typing import Optional


class OIDCProvider(ABC):
    """Common interface all SSO providers implement."""

    @abstractmethod
    def get_name(self) -> str:
        """Short identifier: entra | google | authentik | cognito"""
        ...

    @abstractmethod
    def get_authorization_url(self, state: str, nonce: str) -> str:
        """Build the provider login redirect URL."""
        ...

    @abstractmethod
    async def exchange_code(self, code: str) -> dict:
        """POST to token endpoint, return raw token response dict."""
        ...

    @abstractmethod
    def get_jwks_uri(self) -> str:
        """Return the JWKS endpoint URL for this provider."""
        ...

    @abstractmethod
    def get_expected_issuer(self) -> str:
        """Return the expected `iss` claim value."""
        ...

    @abstractmethod
    def get_client_id(self) -> str:
        ...

    @abstractmethod
    def resolve_role_from_claims(self, claims: dict) -> str:
        """Return 'admin' or 'user' based on JWT claims. Never raises."""
        ...

    @abstractmethod
    def extract_identity(self, claims: dict) -> tuple[str, str, Optional[str]]:
        """Return (external_id, username, email) from decoded claims."""
        ...
