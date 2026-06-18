from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field

class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = utc_field()
    actor: str = Field(index=True)
    action: str
    resource: str
    result: str  # "SUCCESS", "FAILURE", "REJECTED", "EXPIRED"
    mode: str    # "GOD", "NORMAL"
    source: str = Field(default="SYSTEM", index=True)  # "K8S" | "AZURE" | "SYSTEM"
    details: Optional[str] = None
