from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class OAuthState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    state: str = Field(index=True, unique=True)
    nonce: str
    provider: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
