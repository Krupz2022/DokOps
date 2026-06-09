from typing import Optional, Any, Dict, List
from datetime import datetime, timezone
import uuid
from sqlmodel import Field, SQLModel, Column, JSON


class Workflow(SQLModel, table=True):
    __tablename__ = "workflows"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    trigger_type: str = Field(default="manual")  # manual|webhook|cron|all|alert
    webhook_token: str = Field(
        default_factory=lambda: str(uuid.uuid4()), unique=True, index=True
    )
    cron_schedule: Optional[str] = Field(default=None)
    trigger_config: Optional[str] = Field(default=None)  # JSON: {"alert_name": "CrashLoopBackOff"}
    input_schema: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    steps: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_by: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Agent fields (null/empty for scripted workflows)
    workflow_type: str = Field(default="scripted")  # scripted|agent
    agent_goal: Optional[str] = Field(default=None)
    agent_approved_tools: List[Dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    agent_cluster_ids: List[int] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    agent_minion_ids: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    agent_max_retries: int = Field(default=3)
    agent_timeout_seconds: int = Field(default=900)
    agent_approval_timeout_seconds: int = Field(default=600)
    # Notification config: {"slack": {"enabled": bool, "webhook_url": str},
    #                        "teams": {"enabled": bool, "webhook_url": str},
    #                        "jira":  {"enabled": bool, "base_url": str, "project_key": str,
    #                                  "issue_type": str, "email": str, "api_token": str}}
    agent_notifications: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class WorkflowRun(SQLModel, table=True):
    __tablename__ = "workflow_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    workflow_id: int = Field(foreign_key="workflows.id", index=True)
    triggered_by: str = Field(default="manual")  # manual|webhook|cron
    triggered_by_user_id: Optional[int] = Field(default=None)
    trigger_input: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="pending")  # pending|running|completed|failed|awaiting_approval
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)
    step_results: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    ai_summary: Optional[str] = Field(default=None)
