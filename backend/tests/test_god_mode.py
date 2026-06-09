import pytest
from app.core.god_mode import (
    enable_god_mode,
    disable_god_mode,
    is_god_mode_active,
    enable_mcp_god_mode,
    disable_mcp_god_mode,
    is_mcp_god_mode_active,
    _god_mode_sessions,
)


@pytest.fixture(autouse=True)
def clean_sessions():
    _god_mode_sessions.clear()
    disable_mcp_god_mode()
    yield
    _god_mode_sessions.clear()
    disable_mcp_god_mode()


def test_god_mode_defaults_to_false():
    assert is_god_mode_active(user_id=1) is False


def test_enable_god_mode_for_user():
    enable_god_mode(user_id=1)
    assert is_god_mode_active(user_id=1) is True


def test_god_mode_is_per_user():
    enable_god_mode(user_id=1)
    assert is_god_mode_active(user_id=2) is False


def test_disable_god_mode_for_user():
    enable_god_mode(user_id=1)
    disable_god_mode(user_id=1)
    assert is_god_mode_active(user_id=1) is False


def test_mcp_god_mode_defaults_to_false():
    assert is_mcp_god_mode_active() is False


def test_enable_mcp_god_mode():
    enable_mcp_god_mode()
    assert is_mcp_god_mode_active() is True


def test_disable_mcp_god_mode():
    enable_mcp_god_mode()
    disable_mcp_god_mode()
    assert is_mcp_god_mode_active() is False


def test_require_god_mode_raises_if_not_superuser():
    from unittest.mock import MagicMock
    from fastapi import HTTPException
    from app.api.deps import require_god_mode
    import asyncio

    user = MagicMock()
    user.is_superuser = False
    user.id = 99

    with pytest.raises(HTTPException) as exc:
        asyncio.get_event_loop().run_until_complete(require_god_mode(current_user=user))
    assert exc.value.status_code == 403
    assert "superuser" in exc.value.detail.lower()


def test_require_god_mode_raises_if_god_mode_inactive():
    from unittest.mock import MagicMock
    from fastapi import HTTPException
    from app.api.deps import require_god_mode
    import asyncio

    user = MagicMock()
    user.is_superuser = True
    user.id = 42

    with pytest.raises(HTTPException) as exc:
        asyncio.get_event_loop().run_until_complete(require_god_mode(current_user=user))
    assert exc.value.status_code == 403
    assert "not active" in exc.value.detail.lower()


def test_require_god_mode_passes_when_active():
    from unittest.mock import MagicMock
    from app.api.deps import require_god_mode
    from app.core.god_mode import enable_god_mode
    import asyncio

    user = MagicMock()
    user.is_superuser = True
    user.id = 7
    enable_god_mode(7)

    result = asyncio.get_event_loop().run_until_complete(require_god_mode(current_user=user))
    assert result == user


def test_mcp_god_mode_is_context_isolated():
    """Enabling MCP god mode in one context must not affect an independent context."""
    import contextvars

    results = {}

    def task_enable():
        enable_mcp_god_mode()
        results["enabled_ctx"] = is_mcp_god_mode_active()

    def task_read():
        results["isolated_ctx"] = is_mcp_god_mode_active()

    ctx1 = contextvars.copy_context()
    ctx2 = contextvars.copy_context()

    ctx1.run(task_enable)
    ctx2.run(task_read)

    assert results["enabled_ctx"] is True, "God mode must be active inside the context that enabled it"
    assert results["isolated_ctx"] is False, "God mode must NOT leak to an independent context"
