from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor: str = Field(index=True)
    action: str
    resource: str
    result: str  # "SUCCESS", "FAILURE", "REJECTED", "EXPIRED"
    mode: str    # "GOD", "NORMAL"
    source: str = Field(default="SYSTEM", index=True)  # "K8S" | "AZURE" | "SYSTEM"
    details: Optional[str] = None
