from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field, utc_optional_field


class Activation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    license_key: str = Field(unique=True, index=True)
    instance_id: str
    activated_at: datetime = utc_field()
    last_heartbeat_at: Optional[datetime] = utc_optional_field()
    is_active: bool = Field(default=False)
