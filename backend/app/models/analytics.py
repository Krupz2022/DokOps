from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class AITokenUsage(SQLModel, table=True):
    __tablename__ = "ai_token_usage"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    source: str = Field(index=True)   # chat | agent | workflow | alert | rag | notification
    model: str = Field(default="")
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
