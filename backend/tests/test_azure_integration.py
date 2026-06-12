import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


async def _make_async_session():
    """Create an in-memory async engine + session factory for a single test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    import app.models.integration  # noqa — registers AzureConnection + AzureFeatureConfig
    import app.models.audit        # noqa
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def test_encrypt_decrypt_roundtrip():
    from app.services.azure_service import encrypt_secret, decrypt_secret
    original = "my-super-secret-value-123"
    encrypted = encrypt_secret(original)
    assert encrypted != original
    assert decrypt_secret(encrypted) == original


def test_encrypt_produces_different_output_each_time():
    from app.services.azure_service import encrypt_secret
    a = encrypt_secret("same-value")
    b = encrypt_secret("same-value")
    # Fernet uses random IV so same input produces different ciphertext
    assert a != b


def test_decrypt_raises_on_garbage():
    from app.services.azure_service import decrypt_secret
    from cryptography.fernet import InvalidToken
    with pytest.raises(Exception):
        decrypt_secret("not-valid-fernet-data")


@pytest.mark.asyncio
async def test_toggle_feature_rejects_invalid_key():
    from app.services.azure_service import toggle_feature
    engine, factory = await _make_async_session()
    with patch("app.services.azure_service.AsyncSessionLocal", factory):
        with pytest.raises(ValueError, match="Unknown feature key"):
            await toggle_feature("not_a_real_feature", True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_toggle_feature_accepts_valid_keys():
    from app.services.azure_service import toggle_feature, disconnect
    engine, factory = await _make_async_session()
    with patch("app.services.azure_service.AsyncSessionLocal", factory):
        await disconnect()
        result = await toggle_feature("cost_optimization", True)
    assert result.feature_key == "cost_optimization"
    assert result.enabled is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_status_when_not_connected():
    from app.services.azure_service import get_status, disconnect
    engine, factory = await _make_async_session()
    with patch("app.services.azure_service.AsyncSessionLocal", factory):
        await disconnect()
        status = await get_status()
    assert status["connected"] is False
    assert status["tenant_id"] is None
    assert status["features"] == {}
    await engine.dispose()


@pytest.mark.asyncio
async def test_toggle_feature_persists():
    from app.services.azure_service import toggle_feature, disconnect
    engine, factory = await _make_async_session()
    with patch("app.services.azure_service.AsyncSessionLocal", factory):
        await disconnect()
        await toggle_feature("cost_optimization", True)
        await toggle_feature("cost_optimization", False)
        result = await toggle_feature("cost_optimization", True)
    assert result.enabled is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_cost_data_raises_when_not_connected():
    from app.services.azure_service import get_cost_data, disconnect
    engine, factory = await _make_async_session()
    with patch("app.services.azure_service.AsyncSessionLocal", factory):
        await disconnect()
        try:
            await get_cost_data()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not connected" in str(e).lower()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_rg_resources_raises_when_feature_disabled():
    from app.services.azure_service import (
        get_rg_resources, toggle_feature, disconnect, connect
    )
    engine, factory = await _make_async_session()
    with patch("app.services.azure_service.AsyncSessionLocal", factory):
        with patch("app.services.azure_service.ResourceManagementClient") as MockRm:
            mock_instance = MagicMock()
            MockRm.return_value = mock_instance
            mock_instance.resource_groups.get.return_value = MagicMock()
            await connect(
                tenant_id="t", subscription_id="s", client_id="c",
                client_secret="secret", resource_group="rg"
            )
        await toggle_feature("resource_discovery", False)
        try:
            await get_rg_resources()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not enabled" in str(e).lower()
    await engine.dispose()


@pytest.mark.asyncio
async def test_connect_raises_on_invalid_credentials():
    from app.services.azure_service import connect
    engine, factory = await _make_async_session()
    with patch("app.services.azure_service.AsyncSessionLocal", factory):
        with patch("app.services.azure_service.ResourceManagementClient") as MockRm:
            MockRm.return_value.resource_groups.get.side_effect = Exception("AuthenticationFailed")
            try:
                await connect("t", "s", "c", "bad_secret", "rg")
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "connection failed" in str(e).lower()
    await engine.dispose()
