from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field


class AITokenUsage(SQLModel, table=True):
    __tablename__ = "ai_token_usage"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    source: str = Field(index=True)   # chat | agent | workflow | alert | rag | notification
    model: str = Field(default="")
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cached_tokens: int = Field(default=0)
    created_at: datetime = utc_field(index=True)
