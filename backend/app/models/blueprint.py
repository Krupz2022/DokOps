from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field, utc_optional_field


def _uuid() -> str:
    return str(uuid.uuid4())


class Blueprint(SQLModel, table=True):
    __tablename__ = "blueprint"
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(unique=True, index=True)
    yaml_body: str = Field(default="resources: []")
    updated_at: datetime = utc_field()


class BlueprintSource(SQLModel, table=True):
    __tablename__ = "blueprintsource"
    id: str = Field(default_factory=_uuid, primary_key=True)
    blueprint_id: str = Field(foreign_key="blueprint.id", index=True)
    name: str
    content: str = Field(default="")


class BlueprintAssignment(SQLModel, table=True):
    __tablename__ = "blueprintassignment"
    id: str = Field(default_factory=_uuid, primary_key=True)
    blueprint_id: str = Field(foreign_key="blueprint.id", index=True)
    scope_type: str  # org | group | minion
    scope_id: str = Field(index=True)


class BlueprintRun(SQLModel, table=True):
    __tablename__ = "blueprintrun"
    id: str = Field(default_factory=_uuid, primary_key=True)
    minion_id: str = Field(foreign_key="minion.id", index=True)
    actor: str
    test: bool = True
    status: str = Field(default="running")  # running | done | failed
    created_at: datetime = utc_field()
    completed_at: Optional[datetime] = utc_optional_field()


class ResourceResult(SQLModel, table=True):
    __tablename__ = "resourceresult"
    id: str = Field(default_factory=_uuid, primary_key=True)
    run_id: str = Field(foreign_key="blueprintrun.id", index=True)
    resource_id: str
    result: Optional[bool] = None  # True | None(would-change) | False
    changes: str = Field(default="{}")  # JSON
    comment: str = Field(default="")
    output: str = Field(default="")  # captured command output (logs)
