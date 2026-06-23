from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field, utc_optional_field


class Minion(SQLModel, table=True):
    id: str = Field(primary_key=True)
    hostname: str
    status: str = Field(default="pending")   # pending | active | offline
    grains: str = Field(default="{}")        # JSON blob
    token_hash: Optional[str] = None
    last_seen: Optional[datetime] = utc_optional_field()
    approved_by: Optional[str] = None
    last_patch_scan: Optional[datetime] = utc_optional_field()
    bootstrapped: bool = Field(default=False)
    created_at: datetime = utc_field()


class MinionJob(SQLModel, table=True):
    id: str = Field(primary_key=True)
    minion_id: str = Field(foreign_key="minion.id", index=True)
    command: str
    actor: str
    status: str = Field(default="pending")   # pending | running | done | failed
    stdout: str = Field(default="")
    stderr: str = Field(default="")
    exit_code: Optional[int] = None
    created_at: datetime = utc_field()
    completed_at: Optional[datetime] = utc_optional_field()
