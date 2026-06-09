# backend/tests/test_cluster_service.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.cluster_service import (
    verify_token_connection,
    ConnectTokenRequest,
)


@pytest.mark.asyncio
async def test_verify_token_rejects_private_ip():
    req = ConnectTokenRequest(
        name="test",
        api_server="https://10.0.0.1",
        token="fake-token",
        provider="generic",
    )
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=[(2, 1, 6, '', ('10.0.0.1', 0))]):
        with pytest.raises(ValueError, match="Private IP"):
            await verify_token_connection(req, allow_private=False)


@pytest.mark.asyncio
async def test_verify_token_rejects_http():
    req = ConnectTokenRequest(
        name="test",
        api_server="http://cluster.example.com",
        token="fake-token",
        provider="generic",
    )
    with pytest.raises(ValueError, match="https"):
        await verify_token_connection(req, allow_private=False)
