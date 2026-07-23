from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field, utc_optional_field


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    conversation_id: str = Field(index=True)
    kind: str = Field(default="rollout_watch")
    namespace: str = ""
    target: str = ""                         # display only, e.g. "deployment/sample-api"
    status: str = Field(default="watching")  # watching | succeeded | failed | timed_out
    message: str = ""
    read: bool = Field(default=False)
    cluster_context: Optional[str] = Field(default=None)
    created_at: datetime = utc_field()
    resolved_at: Optional[datetime] = utc_optional_field()
