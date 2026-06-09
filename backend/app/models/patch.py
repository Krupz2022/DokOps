from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid.uuid4())


class Organisation(SQLModel, table=True):
    __tablename__ = "organisation"
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    slug: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MinionGroup(SQLModel, table=True):
    __tablename__ = "miniongroup"
    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organisation.id", index=True)
    name: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MinionGroupMember(SQLModel, table=True):
    __tablename__ = "miniongroupmember"
    group_id: str = Field(foreign_key="miniongroup.id", primary_key=True)
    minion_id: str = Field(foreign_key="minion.id", primary_key=True)


class MinionPatch(SQLModel, table=True):
    __tablename__ = "minionpatch"
    id: str = Field(default_factory=_uuid, primary_key=True)
    minion_id: str = Field(foreign_key="minion.id", index=True)
    package_name: str
    installed_version: str
    available_version: str
    advisory_id: Optional[str] = None
    advisory_type: str = "enhancement"   # security / bugfix / enhancement
    severity: str = "none"               # critical / high / medium / low / none
    cve_ids: str = Field(default="[]")   # JSON text e.g. '["CVE-2023-1234"]'
    scanned_at: datetime = Field(default_factory=datetime.utcnow)


class PatchPipeline(SQLModel, table=True):
    __tablename__ = "patchpipeline"
    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organisation.id", index=True)
    name: str
    auto_promote: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PipelineStage(SQLModel, table=True):
    __tablename__ = "pipelinestage"
    id: str = Field(default_factory=_uuid, primary_key=True)
    pipeline_id: str = Field(foreign_key="patchpipeline.id", index=True)
    group_id: str = Field(foreign_key="miniongroup.id")
    order: int
    name: str   # display label e.g. "dev", "qa", "uat", "prod"


class PatchPromotion(SQLModel, table=True):
    __tablename__ = "patchpromotion"
    id: str = Field(default_factory=_uuid, primary_key=True)
    pipeline_id: str = Field(foreign_key="patchpipeline.id", index=True)
    from_stage_id: Optional[str] = Field(default=None, foreign_key="pipelinestage.id")
    to_stage_id: str = Field(foreign_key="pipelinestage.id")
    patch_scope: str                          # security / all / custom
    custom_packages: Optional[str] = None     # JSON text ["nginx", "openssl"]
    triggered_by: str
    triggered_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "pending"                   # pending / running / done / partial / failed
    completed_at: Optional[datetime] = None
    failed_minions: Optional[str] = None      # JSON text ["minion-id-1", "minion-id-2"]
    reboot_minions: Optional[str] = None      # JSON text ["minion-id-1"] — need reboot after patching
    excluded_minions: Optional[str] = None    # JSON text [{"id":..,"reason":..,"excluded_by":..,"at":..}]
    partial_override: bool = False


class PatchSchedule(SQLModel, table=True):
    __tablename__ = "patchschedule"
    id: str = Field(default_factory=_uuid, primary_key=True)
    pipeline_id: str = Field(foreign_key="patchpipeline.id", index=True)
    stage_id: str = Field(foreign_key="pipelinestage.id")
    cron_expr: str
    timezone: str = "UTC"                     # IANA timezone e.g. "Europe/London"
    patch_scope: str                          # security / all / custom
    custom_packages: Optional[str] = None
    promote_from_previous: bool = False       # if true, read prior stage's frozen package list
    auto_reboot: bool = False                 # if true, reboot minion after patching when reboot is required
    week_of_month: Optional[int] = None       # 1-4; None = every week
    enabled: bool = True
    notifications: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    ai_beautify: bool = False
    created_by: str
    next_run_at: Optional[datetime] = None


class PatchAlertEvent(SQLModel, table=True):
    __tablename__ = "patchalertevent"
    id: str = Field(default_factory=_uuid, primary_key=True)
    pipeline_id: str = Field(foreign_key="patchpipeline.id", index=True)
    stage_id: str = Field(foreign_key="pipelinestage.id")
    # prior_stage_not_complete / prior_stage_failed / prior_stage_partial / no_prior_run
    reason: str
    fired_at: datetime = Field(default_factory=datetime.utcnow)
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None


class PatchPromotionResult(SQLModel, table=True):
    __tablename__ = "patchpromotionresult"
    id: str = Field(default_factory=_uuid, primary_key=True)
    promotion_id: str = Field(foreign_key="patchpromotion.id", index=True)
    minion_id: str = Field(foreign_key="minion.id", index=True)
    status: str                                    # done / failed
    exit_code: int = 0
    stdout: Optional[str] = None                   # truncated to 4096 chars
    applied_advisories: str = Field(default="[]")  # JSON list of {advisory_id, package_name, severity, from_version, to_version}
    packages_count: int = 0                        # len(applied_advisories) for quick reads
    created_at: datetime = Field(default_factory=datetime.utcnow)
