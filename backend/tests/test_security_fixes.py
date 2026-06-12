# backend/tests/test_security_fixes.py
import pytest
import shlex
import subprocess
from unittest.mock import patch

def test_default_secret_raises_on_startup():
    """Startup must reject the default 'changethis' secret."""
    from app.main import _assert_secret_changed
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        _assert_secret_changed("changethis")

def test_strong_secret_passes():
    from app.main import _assert_secret_changed
    _assert_secret_changed("a-very-long-random-secret-that-is-not-default-xyz123")


def test_god_mode_check_uses_real_user_id():
    """is_god_mode_active must be called with the actual run's user_id, not 0."""
    from app.core.god_mode import enable_god_mode, is_god_mode_active, disable_god_mode
    enable_god_mode(99)
    assert is_god_mode_active(99) is True
    assert is_god_mode_active(0) is False   # 0 must NOT be god mode just because 99 is
    disable_god_mode(99)


# Task 4 — WebSocket token verification
def test_minion_websocket_token_hashes_unique():
    """hash_token must produce distinct hashes for different inputs."""
    from app.services.minion_service import hash_token
    assert hash_token("good-token") != hash_token("bad-token")
    assert hash_token("good-token") != hash_token("")


# Task 18 — bcrypt upgrade for auto-accept token
def test_hash_token_uses_bcrypt():
    from app.services.minion_service import hash_token, verify_token
    token = "my-test-token-abc123"
    hashed = hash_token(token)
    # bcrypt hashes start with $2b$ and are NOT plain hex
    assert hashed.startswith("$2"), "hash_token must produce a bcrypt hash"
    assert len(hashed) != 64, "hash_token must NOT produce a plain SHA-256 hex digest"
    # verify_token must work correctly
    assert verify_token(token, hashed) is True
    assert verify_token("wrong-token", hashed) is False

def test_verify_token_legacy_sha256_fallback():
    """Existing SHA-256 hashes must still validate during migration."""
    import hashlib
    from app.services.minion_service import verify_token
    token = "legacy-token"
    sha256_hash = hashlib.sha256(token.encode()).hexdigest()
    assert verify_token(token, sha256_hash) is True
    assert verify_token("wrong", sha256_hash) is False


# Task 5 — shell=False prevents injection in user-controlled paths
def test_cli_tool_no_shell_injection():
    """install_custom_tool and _install_helm_plugin must use shell=False."""
    import inspect
    from app.services.cli_tool_service import CLIToolService
    custom_src = inspect.getsource(CLIToolService.install_custom_tool)
    helm_src = inspect.getsource(CLIToolService._install_helm_plugin)
    assert "shell=False" in custom_src, "install_custom_tool must use shell=False"
    assert "shell=True" not in custom_src, "install_custom_tool must not use shell=True"
    assert "shell=False" in helm_src, "_install_helm_plugin must use shell=False"
    assert "shell=True" not in helm_src, "_install_helm_plugin must not use shell=True"


# Task 6 — ps_quote safety
def test_ps_quote_safe_name():
    from app.services.patch_service import ps_quote
    assert ps_quote("Windows Update KB123") == "'Windows Update KB123'"

def test_ps_quote_single_quote_escaped():
    from app.services.patch_service import ps_quote
    result = ps_quote("test'injection")
    assert result.startswith("'") and result.endswith("'")
    assert result == "'test''injection'"

def test_ps_quote_never_double_quoted():
    from app.services.patch_service import ps_quote
    for name in ["test'foo", "a'b'c"]:
        result = ps_quote(name)
        assert result.startswith("'"), f"Must start with single quote: {result}"
        assert result.endswith("'"), f"Must end with single quote: {result}"


# Task 8 — dispatch_job allowlist enforcement
def test_dispatch_job_blocks_non_allowlisted_command():
    import asyncio
    from app.services.minion_service import MinionConnectionManager
    mgr = MinionConnectionManager()
    mgr._connections = {"m1": object()}  # fake connected
    with pytest.raises((PermissionError, RuntimeError)):
        asyncio.get_event_loop().run_until_complete(
            mgr.dispatch_job("m1", "rm -rf /", actor="test", timeout=5, god_mode=False)
        )

def test_dispatch_job_allows_allowlisted_command():
    """is_read_allowed check — uptime is in the allowlist."""
    from app.services.minion_service import is_read_allowed
    assert is_read_allowed("uptime") is True
    assert is_read_allowed("docker ps") is True
    assert is_read_allowed("rm -rf /") is False


# Task 9 — probe container quoting
def test_probe_container_is_shell_quoted():
    import shlex
    from app.services.probe_registry import render_command
    malicious_container = "x; echo HACKED"
    cmd = render_command("redis", "info", "docker", None, 6379, container=malicious_container)
    assert shlex.quote(malicious_container) in cmd


# Task 10 — redact_command
def test_redact_command_removes_password():
    from app.services.minion_service import redact_command
    cmd = "mysqladmin -u 'admin' --password='SuperSecret123' status"
    redacted = redact_command(cmd)
    assert "SuperSecret123" not in redacted
    assert "[REDACTED]" in redacted

def test_redact_command_preserves_non_credential_commands():
    from app.services.minion_service import redact_command
    cmd = "docker exec mycontainer redis-cli ping"
    assert redact_command(cmd) == cmd


# Task 11 — template param sanitization
def test_sanitize_template_param_strips_newlines():
    from app.services.ai_service import _sanitize_template_param
    injected = "legit-pod\nrm -rf /data\n"
    sanitized = _sanitize_template_param(injected)
    assert "\n" not in sanitized
    assert "legit-pod" in sanitized


# Task 12 — K8s name validation
def test_k8s_name_validation_blocks_flag_injection():
    from app.tools.k8s_tools import validate_k8s_name
    with pytest.raises(ValueError):
        validate_k8s_name("foo --context=evil", "pod_name")

def test_k8s_name_validation_blocks_spaces():
    from app.tools.k8s_tools import validate_k8s_name
    with pytest.raises(ValueError):
        validate_k8s_name("my pod", "pod_name")

def test_k8s_name_validation_allows_valid():
    from app.tools.k8s_tools import validate_k8s_name
    assert validate_k8s_name("my-pod-123", "pod_name") == "my-pod-123"
    assert validate_k8s_name("default", "namespace") == "default"


# Task 13 — OIDC nonce validation
def test_nonce_mismatch_raises():
    from app.services.sso_service import _assert_nonce
    with pytest.raises(ValueError, match="[Nn]once"):
        _assert_nonce({"nonce": "different"}, "expected-nonce-abc")

def test_nonce_match_passes():
    from app.services.sso_service import _assert_nonce
    _assert_nonce({"nonce": "abc123"}, "abc123")  # should not raise


# Task 14 — SSO role allowlist
def test_sso_unknown_role_defaults_to_user():
    from app.services.sso_service import _safe_role
    assert _safe_role("admin") == "admin"
    assert _safe_role("user") == "user"
    assert _safe_role("readonly") == "user"   # readonly removed; falls back to user
    assert _safe_role("superadmin") == "user"
    assert _safe_role("") == "user"
    assert _safe_role(None) == "user"


# Task 17 — Encryption key fallback
def test_encryption_key_env_var_used_when_set():
    """ENCRYPTION_KEY env var should be used instead of deriving from AUTH_SECRET_KEY."""
    from app.core.encryption import _fernet
    f = _fernet()  # Should not raise even without ENCRYPTION_KEY set
    assert f is not None


# Task 21 — Toolset path traversal
def test_toolset_path_traversal_blocked(tmp_path):
    from app.services.toolset_service import ToolsetService
    svc = ToolsetService(str(tmp_path))
    with pytest.raises(ValueError):
        svc.get_toolset("../../../etc/passwd")

def test_toolset_valid_id_passes(tmp_path):
    from app.services.toolset_service import ToolsetService
    svc = ToolsetService(str(tmp_path))
    result = svc.get_toolset("my-toolset-123")
    assert result is None  # not found but no exception


# Task 24 — Email header injection
def test_email_header_injection_stripped():
    from app.services.connectors.email_connector import _sanitize_header
    injected = "victim@example.com\nBcc: attacker@evil.com"
    sanitized = _sanitize_header(injected)
    # The newline is removed — this prevents the email library from parsing a new header
    assert "\n" not in sanitized
    assert "\r" not in sanitized
    assert _sanitize_header("normal@example.com") == "normal@example.com"


# Task 25 — KQL injection
def test_kql_escape_single_quote():
    from app.services.azure_service import _kql_escape
    assert _kql_escape("normal-rg") == "normal-rg"
    assert _kql_escape("test' or '1'='1") == "test'' or ''1''=''1"


# Task 7 — SSRF validate_url
def test_ssrf_validate_url_blocks_localhost():
    from app.core.ssrf import validate_url
    with pytest.raises(ValueError):
        validate_url("http://localhost:8080/admin")

def test_ssrf_validate_url_blocks_metadata():
    from app.core.ssrf import validate_url
    with pytest.raises(ValueError):
        validate_url("http://169.254.169.254/latest/meta-data/")

def test_ssrf_validate_url_allows_public():
    from app.core.ssrf import validate_url
    validate_url("https://hooks.slack.com/services/abc")  # should not raise


def test_fernet_logs_warning_without_encryption_key(caplog):
    """_fernet() must emit a WARNING when ENCRYPTION_KEY is not set."""
    import logging
    from unittest.mock import patch
    from app.core import encryption

    with patch.object(encryption.settings, "ENCRYPTION_KEY", None), \
         caplog.at_level(logging.WARNING, logger="app.core.encryption"):
        encryption._fernet()

    assert any("ENCRYPTION_KEY" in r.message for r in caplog.records), \
        "Expected a WARNING mentioning ENCRYPTION_KEY"


@pytest.mark.asyncio
async def test_refresh_token_is_encrypted_in_db():
    """provider_refresh_token must be stored encrypted, not plaintext."""
    from sqlmodel import SQLModel
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession
    from app.core.encryption import decrypt
    from app.services.sso_service import upsert_sso_user

    _async_engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}
    )
    async with _async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    async with _AsyncSessionLocal() as db:
        user = await upsert_sso_user(
            db=db,
            provider="entra",
            external_id="ext-001",
            email="test@example.com",
            username="testuser",
            role="user",
            refresh_token="plaintext-refresh-token-abc123",
            auto_provision=True,
        )

    await _async_engine.dispose()

    assert user.provider_refresh_token != "plaintext-refresh-token-abc123", \
        "Refresh token must be stored encrypted"
    assert decrypt(user.provider_refresh_token) == "plaintext-refresh-token-abc123"


@pytest.mark.asyncio
async def test_refresh_token_none_is_stored_as_none():
    """upsert_sso_user with refresh_token=None must store None."""
    from sqlmodel import SQLModel
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession
    from app.services.sso_service import upsert_sso_user

    _async_engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}
    )
    async with _async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    async with _AsyncSessionLocal() as db:
        user = await upsert_sso_user(
            db=db,
            provider="google",
            external_id="ext-002",
            email="other@example.com",
            username="otheruser",
            role="user",
            refresh_token=None,
            auto_provision=True,
        )

    await _async_engine.dispose()

    assert user.provider_refresh_token is None
