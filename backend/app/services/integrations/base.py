import base64
import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from cryptography.fernet import Fernet

from app.core.config import settings


def _get_fernet() -> Fernet:
    raw = settings.AUTH_SECRET_KEY.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt_credentials(data: Dict[str, Any]) -> str:
    """Serialize dict to JSON and Fernet-encrypt. Returns base64 ciphertext."""
    return _get_fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_credentials(token: str) -> Dict[str, Any]:
    """Fernet-decrypt and JSON-deserialize back to dict."""
    return json.loads(_get_fernet().decrypt(token.encode()).decode())


def build_auth_headers(auth_type: str, encrypted_creds: Optional[str]) -> Dict[str, str]:
    """
    Build HTTP headers for the given auth_type.

    auth_type values and required cred fields:
    - "none": no headers needed
    - "bearer": {"token": "..."}  → Authorization: Bearer ...
    - "basic": {"username": "...", "password": "..."}  → Authorization: Basic base64(user:pass)
    - "api_key": {"api_key": "...", "header_name": "X-Api-Key"}  → <header_name>: <api_key>
    """
    if auth_type == "none" or not encrypted_creds:
        return {}
    creds = decrypt_credentials(encrypted_creds)
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {creds['token']}"}
    if auth_type == "basic":
        encoded = base64.b64encode(f"{creds['username']}:{creds['password']}".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}
    if auth_type == "api_key":
        return {creds["header_name"]: creds["api_key"]}
    raise ValueError(f"Unsupported auth_type: {auth_type!r}")


class BaseIntegrationService(ABC):
    """Abstract base for all observability backend services."""

    @abstractmethod
    async def test_connection(self, base_url: str, headers: Dict[str, str]) -> Tuple[bool, str]:
        """Return (success, message) — True/False plus a human-readable status string."""
        ...

    @abstractmethod
    def get_tool_registry(self, base_url: str, headers: Dict[str, str]) -> Dict[str, Any]:
        """
        Return a TOOL_REGISTRY-compatible dict:
        {
          "tool_name": {
            "function": async_callable,
            "description": str,
            "inputs": [...],
            "operation_type": "read",
            "requires_confirmation": False,
          }
        }
        """
        ...
