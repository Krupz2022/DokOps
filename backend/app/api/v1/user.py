from typing import Any, List
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.core import security
from app.core.config import settings
from app.models.user import User

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    hashed_password: str
    is_superuser: bool = False
    role: str = "user"
    is_active: bool = True


@router.get("/me", response_model=User)
async def read_user_me(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Get current user.
    """
    return current_user

@router.get("/", response_model=List[User])
async def read_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_superuser),
    db: AsyncSession = Depends(deps.get_async_db),
) -> Any:
    """
    Retrieve users.
    """
    users = (await db.exec(select(User).offset(skip).limit(limit))).all()
    return users

@router.post("/", response_model=User)
async def create_user(
    *,
    db: AsyncSession = Depends(deps.get_async_db),
    user_in: UserCreate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Create new user. Only superusers can create new users.
    """
    existing = (await db.exec(select(User).where(User.username == user_in.username))).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )

    new_user = User(
        username=user_in.username,
        hashed_password=security.get_password_hash(user_in.hashed_password),
        is_superuser=user_in.is_superuser,
        role=user_in.role,
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@router.put("/{user_id}", response_model=User)
async def update_user(
    *,
    db: AsyncSession = Depends(deps.get_async_db),
    user_id: int,
    user_in: User,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Update a user.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )

    # Update fields
    user.username = user_in.username
    user.is_active = user_in.is_active
    user.is_superuser = user_in.is_superuser
    user.role = user_in.role

    if user_in.hashed_password and user_in.hashed_password != user.hashed_password:
         # Basic check if it's a new password string (not already hashed)
         # In a real app we'd use a separate schema (UserUpdate)
         if len(user_in.hashed_password) < 60: # primitive check for bcrypt hash length
             user.hashed_password = security.get_password_hash(user_in.hashed_password)

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

class RoleUpdate(BaseModel):
    role: str  # "admin" | "user"


@router.patch("/{user_id}/role", response_model=User)
async def update_user_role(
    *,
    db: AsyncSession = Depends(deps.get_async_db),
    user_id: int,
    payload: RoleUpdate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Change a user's role. Superusers only."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    valid_roles = {"admin", "user"}
    if payload.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Role must be one of {valid_roles}")
    user.role = payload.role
    user.is_superuser = payload.role == "admin"
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=User)
async def delete_user(
    *,
    db: AsyncSession = Depends(deps.get_async_db),
    user_id: int,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Delete a user.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    await db.delete(user)
    await db.commit()
    return user
