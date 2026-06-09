from typing import Optional
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: Optional[str] = Field(default=None)  # None for SSO users
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    role: str = Field(default="user")  # "admin" | "user"
    # SSO fields — None for local users
    email: Optional[str] = Field(default=None, index=True)
    provider: Optional[str] = Field(default=None)   # "entra"|"google"|"authentik"|"cognito"
    external_id: Optional[str] = Field(default=None)
    provider_refresh_token: Optional[str] = Field(default=None)
    god_mode_active: bool = Field(default=False)
