# backend/tests/test_cluster_onboarding.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.encryption import decrypt, encrypt
from app.core.ssrf import validate_cluster_url


# ── Encryption ───────────────────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip():
    token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test"
    assert decrypt(encrypt(token)) == token


def test_different_ciphertexts_same_input():
    t = "same-token"
    assert encrypt(t) != encrypt(t)


def test_decrypt_invalid_raises_value_error():
    with pytest.raises(ValueError, match="Invalid or tampered"):
        decrypt("not-valid-ciphertext")


# ── SSRF ─────────────────────────────────────────────────────────────────────

def test_ssrf_rejects_http():
    with pytest.raises(ValueError, match="https"):
        validate_cluster_url("http://cluster.example.com")


def test_ssrf_rejects_metadata_ip():
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=[(2, 1, 6, '', ('169.254.169.254', 0))]):
        with pytest.raises(ValueError, match="Private IP"):
            validate_cluster_url("https://metadata.local")


def test_ssrf_rejects_private_ip_10x():
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=[(2, 1, 6, '', ('10.0.0.1', 0))]):
        with pytest.raises(ValueError, match="Private IP"):
            validate_cluster_url("https://internal-cluster.local")


def test_ssrf_allows_public():
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=[(2, 1, 6, '', ('203.0.113.10', 0))]):
        validate_cluster_url("https://public-cluster.example.com")


# ── Token connectivity flow ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_token_calls_k8s_and_saves():
    from app.services.cluster_service import verify_token_connection, ConnectTokenRequest

    req = ConnectTokenRequest(
        name="my-cluster",
        api_server="https://203.0.113.10:6443",
        token="test-token",
        provider="generic",
    )

    with patch("app.core.ssrf.socket.getaddrinfo", return_value=[(2, 1, 6, '', ('203.0.113.10', 0))]), \
         patch("app.services.cluster_service._test_k8s_connectivity", new_callable=AsyncMock) as mock_k8s, \
         patch("app.services.cluster_service.k8s_service.add_connection", new_callable=AsyncMock), \
         patch("app.services.cluster_service.Session") as MockSession:

        mock_db = MagicMock()
        MockSession.return_value.__enter__.return_value = mock_db
        mock_db.get.return_value = None  # for compensating delete path

        conn = await verify_token_connection(req, allow_private=False, added_by="admin")

        assert conn.name == "my-cluster"
        assert conn.provider == "generic"
        assert conn.token != "test-token"  # must be encrypted
        assert decrypt(conn.token) == "test-token"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_k8s.assert_called_once()
