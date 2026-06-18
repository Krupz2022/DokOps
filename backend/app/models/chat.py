# backend/app/models/chat.py
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel
import uuid

from app.core.datetimes import utc_field


def _new_uuid() -> str:
    return str(uuid.uuid4())


class ChatConversation(SQLModel, table=True):
    id: str = Field(default_factory=_new_uuid, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str = Field(default="New Chat")
    created_at: datetime = utc_field()
    updated_at: datetime = utc_field()
    is_compacted: bool = Field(default=False)
    summary: Optional[str] = Field(default=None)


class ChatMessage(SQLModel, table=True):
    id: str = Field(default_factory=_new_uuid, primary_key=True)
    conversation_id: str = Field(foreign_key="chatconversation.id", index=True)
    role: str  # "user" | "assistant"
    content: str
    message_type: str = Field(default="text")  # "text" | "step" | "action_card" | "runbook_card" | "pending_op" | "compaction_banner"
    token_count: int = Field(default=0)
    created_at: datetime = utc_field()
    is_compacted: bool = Field(default=False)
