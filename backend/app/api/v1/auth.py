from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api import deps
from app.core import security
from app.core.config import settings
from app.models.user import User

router = APIRouter()

@router.post("/login/access-token")
def login_access_token(
    response: Response,
    db: Session = Depends(deps.get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    OAuth2 compatible token login. Sets a httpOnly cookie and also returns token in body.
    """
    statement = select(User).where(User.username == form_data.username)
    user = db.exec(statement).first()

    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(user.username, expires_delta=access_token_expires)

    # Set httpOnly cookie — not accessible via JavaScript, safer than localStorage
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,   # Set to True in production (requires HTTPS)
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return {
        "access_token": access_token,   # also returned in body for backwards compat
        "token_type": "bearer",
        "username": user.username,
        "is_superuser": user.is_superuser,
        "role": user.role,
    }


@router.post("/logout")
def logout(response: Response) -> Any:
    """Clear the auth cookie."""
    response.delete_cookie(key="access_token", httponly=True, samesite="lax")
    return {"message": "Logged out"}


class RegisterRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
def register_user(
    payload: RegisterRequest,
    db: Session = Depends(deps.get_db),
) -> Any:
    if settings.SSO_ENABLED:
        raise HTTPException(status_code=403, detail="Registration is disabled when SSO is enabled")

    from app.models.setting import SystemSetting

    signup_enabled_row = db.exec(
        select(SystemSetting).where(SystemSetting.key == "signup_enabled")
    ).first()
    if not signup_enabled_row or signup_enabled_row.value != "true":
        raise HTTPException(status_code=403, detail="Public signups are disabled")

    existing = db.exec(select(User).where(User.username == payload.username)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    signup_default_role_row = db.exec(
        select(SystemSetting).where(SystemSetting.key == "signup_default_role")
    ).first()
    role = signup_default_role_row.value if signup_default_role_row else "user"

    user = User(
        username=payload.username,
        hashed_password=security.get_password_hash(payload.password),
        is_superuser=(role == "admin"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = security.create_access_token(user.username, expires_delta=expires)
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "is_superuser": user.is_superuser,
        "role": user.role,
    }
