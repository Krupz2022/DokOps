from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger
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
    """A file a blueprint can lay down on a minion.

    Two origins, because the bytes live in different places:
      - "disk"   — seeded from the blueprints folder; the file stays on disk and
                   this row is a reference. Artifacts can be gigabytes, so their
                   contents must never be loaded to answer a question about them.
      - "inline" — created in the UI (editor or upload); bytes live in `content`.
    """
    __tablename__ = "blueprintsource"
    id: str = Field(default_factory=_uuid, primary_key=True)
    blueprint_id: str = Field(foreign_key="blueprint.id", index=True)
    name: str
    origin: str = Field(default="inline")  # "disk" | "inline"

    # origin="disk": reference to the file under BLUEPRINTS_ROOT.
    # size/mtime_ns MUST be 64-bit: nanosecond mtimes are ~1.8e18 and artifacts can
    # exceed 2GB, both of which overflow Postgres int32. SQLite hides this (its
    # INTEGER is dynamically sized), so only Postgres fails — hence the explicit type.
    rel_path: str = Field(default="")
    size: int = Field(default=0, sa_type=BigInteger)
    mtime_ns: int = Field(default=0, sa_type=BigInteger)
    sha256: Optional[str] = Field(default=None)  # lazily filled; cleared when size/mtime change

    # origin="inline": the bytes themselves.
    content: str = Field(default="")
    encoding: str = Field(default="utf-8")  # "utf-8" | "base64"


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
