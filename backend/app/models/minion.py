from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class Minion(SQLModel, table=True):
    id: str = Field(primary_key=True)
    hostname: str
    status: str = Field(default="pending")   # pending | active | offline
    grains: str = Field(default="{}")        # JSON blob
    token_hash: Optional[str] = None
    last_seen: Optional[datetime] = None
    approved_by: Optional[str] = None
    last_patch_scan: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MinionJob(SQLModel, table=True):
    id: str = Field(primary_key=True)
    minion_id: str = Field(foreign_key="minion.id", index=True)
    command: str
    actor: str
    status: str = Field(default="pending")   # pending | running | done | failed
    stdout: str = Field(default="")
    stderr: str = Field(default="")
    exit_code: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
