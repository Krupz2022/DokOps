import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api import deps
from app.models.user import User
from app.models.setting import SystemSetting
from app.core import security as _security
from app.core.config import settings as _settings

router = APIRouter()


@router.get("/status")
def get_system_status(
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_optional_current_user),
) -> Any:
    from app.core.god_mode import is_god_mode_active

    any_user = db.exec(select(User).limit(1)).first()
    setup_complete = any_user is not None

    signup_enabled_row = db.exec(
        select(SystemSetting).where(SystemSetting.key == "signup_enabled")
    ).first()
    signup_default_role_row = db.exec(
        select(SystemSetting).where(SystemSetting.key == "signup_default_role")
    ).first()

    return {
        "god_mode_active": is_god_mode_active(current_user.id) if current_user else False,
        "is_superuser": current_user.is_superuser if current_user else False,
        "setup_complete": setup_complete,
        "signup_enabled": signup_enabled_row.value == "true" if signup_enabled_row else False,
        "signup_default_role": signup_default_role_row.value if signup_default_role_row else "user",
        "sso_enabled": _settings.SSO_ENABLED,
    }


class SetupRequest(BaseModel):
    username: str
    password: str


@router.post("/setup")
def first_run_setup(
    payload: SetupRequest,
    db: Session = Depends(deps.get_db),
) -> Any:
    any_user = db.exec(select(User).limit(1)).first()
    if any_user is not None:
        raise HTTPException(status_code=403, detail="Setup already complete")

    user = User(
        username=payload.username,
        hashed_password=_security.get_password_hash(payload.password),
        is_superuser=True,
        role="admin",
        is_active=True,
    )
    db.add(user)

    for key, value in [("signup_enabled", "true"), ("signup_default_role", "user")]:
        db.add(SystemSetting(key=key, value=value))

    db.commit()
    db.refresh(user)

    expires = timedelta(minutes=_settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = _security.create_access_token(user.username, expires_delta=expires)
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "is_superuser": user.is_superuser,
        "role": user.role,
    }


class SignupSettingsRequest(BaseModel):
    signup_enabled: bool
    signup_default_role: str  # "user" or "admin"


@router.put("/settings")
def update_signup_settings(
    payload: SignupSettingsRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    if payload.signup_default_role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="signup_default_role must be 'user' or 'admin'")

    updates = [
        ("signup_enabled", "true" if payload.signup_enabled else "false"),
        ("signup_default_role", payload.signup_default_role),
    ]
    for key, value in updates:
        row = db.exec(select(SystemSetting).where(SystemSetting.key == key)).first()
        if row:
            row.value = value
            db.add(row)
        else:
            db.add(SystemSetting(key=key, value=value))
    db.commit()
    return {"status": "updated"}


@router.post("/mode")
def set_system_mode(
    mode: str = Body(..., embed=True),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Toggle God Mode for the current superuser's session."""
    if mode not in ["GOD", "NORMAL"]:
        raise HTTPException(status_code=400, detail="Invalid mode")

    from app.core.god_mode import (
        enable_god_mode, disable_god_mode,
        enable_mcp_god_mode, disable_mcp_god_mode,
    )
    if mode == "GOD":
        enable_god_mode(current_user.id)
        enable_mcp_god_mode()
    else:
        disable_god_mode(current_user.id)
        disable_mcp_god_mode()

    return {"status": "updated", "mode": mode}


# ── OpenAI-Compatible API Config ───────────────────────────────────────────────

def _get_compat_setting(key: str, db: Session) -> Optional[str]:
    row = db.exec(select(SystemSetting).where(SystemSetting.key == key)).first()
    return row.value if row else None


def _upsert_setting(key: str, value: str, db: Session) -> None:
    row = db.exec(select(SystemSetting).where(SystemSetting.key == key)).first()
    if row:
        row.value = value
        db.add(row)
    else:
        db.add(SystemSetting(key=key, value=value))


@router.get("/openai-compat")
def get_openai_compat_config(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db),
):
    enabled_val = _get_compat_setting("openai_compat_enabled", db)
    has_key = _get_compat_setting("openai_compat_api_key_hash", db) is not None
    created_at = _get_compat_setting("openai_compat_key_created_at", db)
    return {
        "enabled": enabled_val == "true",
        "has_key": has_key,
        "created_at": created_at,
    }


class OpenAICompatPatch(BaseModel):
    enabled: Optional[bool] = None


@router.patch("/openai-compat")
def update_openai_compat_config(
    payload: OpenAICompatPatch,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db),
):
    if payload.enabled is not None:
        _upsert_setting("openai_compat_enabled", "true" if payload.enabled else "false", db)
        db.commit()
    return {"status": "updated"}


@router.post("/openai-compat/regenerate-key")
def regenerate_openai_compat_key(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db),
):
    plaintext = "sk-dokops-" + secrets.token_hex(32)
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    created_at = datetime.now(timezone.utc).isoformat()
    _upsert_setting("openai_compat_api_key_hash", key_hash, db)
    _upsert_setting("openai_compat_key_created_at", created_at, db)
    db.commit()
    return {"key": plaintext}
