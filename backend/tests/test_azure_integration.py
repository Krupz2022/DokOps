import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import SQLModel, create_engine, Session


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Redirect all DB operations to a fresh in-memory SQLite for each test."""
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Import models so SQLModel.metadata knows about them
    import app.models.integration  # noqa
    import app.models.audit        # noqa
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr("app.services.azure_service.engine", test_engine)
    monkeypatch.setattr("app.core.db.engine", test_engine)
    yield


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


def test_toggle_feature_rejects_invalid_key():
    from app.services.azure_service import toggle_feature
    with pytest.raises(ValueError, match="Unknown feature key"):
        toggle_feature("not_a_real_feature", True)


def test_toggle_feature_accepts_valid_keys():
    from app.services.azure_service import toggle_feature, disconnect
    disconnect()
    result = toggle_feature("cost_optimization", True)
    assert result.feature_key == "cost_optimization"
    assert result.enabled is True


def test_get_status_when_not_connected():
    from app.services.azure_service import get_status, disconnect
    disconnect()
    status = get_status()
    assert status["connected"] is False
    assert status["tenant_id"] is None
    assert status["features"] == {}


def test_toggle_feature_persists():
    from app.services.azure_service import toggle_feature, disconnect
    disconnect()
    toggle_feature("cost_optimization", True)
    toggle_feature("cost_optimization", False)
    result = toggle_feature("cost_optimization", True)
    assert result.enabled is True


def test_get_cost_data_raises_when_not_connected():
    from app.services.azure_service import get_cost_data, disconnect
    disconnect()
    try:
        get_cost_data()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not connected" in str(e).lower()


def test_get_rg_resources_raises_when_feature_disabled():
    from app.services.azure_service import (
        get_rg_resources, toggle_feature, disconnect, connect
    )
    from unittest.mock import patch, MagicMock
    with patch("app.services.azure_service.ResourceManagementClient") as MockRm:
        mock_instance = MagicMock()
        MockRm.return_value = mock_instance
        mock_instance.resource_groups.get.return_value = MagicMock()
        connect(
            tenant_id="t", subscription_id="s", client_id="c",
            client_secret="secret", resource_group="rg"
        )
    toggle_feature("resource_discovery", False)
    try:
        get_rg_resources()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not enabled" in str(e).lower()


def test_connect_raises_on_invalid_credentials():
    from app.services.azure_service import connect
    from unittest.mock import patch
    with patch("app.services.azure_service.ResourceManagementClient") as MockRm:
        MockRm.return_value.resource_groups.get.side_effect = Exception("AuthenticationFailed")
        try:
            connect("t", "s", "c", "bad_secret", "rg")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "connection failed" in str(e).lower()
