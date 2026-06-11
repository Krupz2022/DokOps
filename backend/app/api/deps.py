import logging
from typing import AsyncGenerator, Generator, Optional
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.security import ALGORITHM
from app.models.user import User
from app.core.db import engine, AsyncSessionLocal

logger = logging.getLogger(__name__)

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token",
    auto_error=False,  # Don't auto-raise; we also accept cookies
)

def get_db() -> Generator:
    with Session(engine) as session:
        yield session


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def get_current_user(
    db: Session = Depends(get_db),
    token_from_header: Optional[str] = Depends(reusable_oauth2),
    access_token: Optional[str] = Cookie(default=None),
) -> User:
    # Accept token from httpOnly cookie first, then Authorization header
    token = access_token or token_from_header
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = jwt.decode(
            token, settings.AUTH_SECRET_KEY, algorithms=[ALGORITHM]
        )
        token_data = payload.get("sub")
    except (JWTError, ValidationError):
        logger.debug("Token validation failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    user = db.query(User).filter(User.username == token_data).first()
    if not user:
        logger.debug("User not found in DB")
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        logger.debug("User is inactive")
        raise HTTPException(status_code=400, detail="Inactive user")
    return user

def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=400, detail="The user doesn't have enough privileges"
        )
    return current_user


from app.core.god_mode import is_god_mode_active


async def require_god_mode(
    current_user: User = Depends(get_current_user),
) -> User:
    if not is_god_mode_active(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="God Mode is not active for your session. Enable it from the header.",
        )
    return current_user


async def get_optional_current_user(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(OAuth2PasswordBearer(
        tokenUrl=f"{settings.API_V1_STR}/login/access-token",
        auto_error=False,
    )),
) -> Optional[User]:
    if token is None:
        return None
    try:
        payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[ALGORITHM])
        token_data = payload.get("sub")
    except (JWTError, ValidationError):
        return None
    return db.query(User).filter(User.username == token_data).first()
