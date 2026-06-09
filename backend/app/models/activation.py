from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel


class Activation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    license_key: str = Field(unique=True, index=True)
    instance_id: str
    activated_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=False)
