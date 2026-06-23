from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field


def _uuid() -> str:
    return str(uuid.uuid4())


class ActivationKey(SQLModel, table=True):
    __tablename__ = "activationkey"
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(unique=True, index=True)
    value_hash: str
    org_id: Optional[str] = Field(default=None, foreign_key="organisation.id")
    group_id: Optional[str] = Field(default=None, foreign_key="miniongroup.id")
    run_on_attach: bool = Field(default=False)
    enabled: bool = Field(default=True)
    created_at: datetime = utc_field()
    created_by: str = ""


class KeyBlueprint(SQLModel, table=True):
    __tablename__ = "keyblueprint"
    id: str = Field(default_factory=_uuid, primary_key=True)
    key_id: str = Field(foreign_key="activationkey.id", index=True)
    blueprint_id: str = Field(foreign_key="blueprint.id")
    position: int = Field(default=0)
