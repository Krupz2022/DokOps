# backend/app/models/alert_incident.py
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field, utc_optional_field


class AlertIncident(SQLModel, table=True):
    __tablename__ = "alert_incidents"

    id: Optional[int] = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True)
    source: str          # "alertmanager" | "grafana" | "datadog" | "pagerduty" | "opsgenie" | "elasticsearch" | "generic"
    alert_name: str = Field(index=True)
    severity: str        # "critical" | "warning" | "info"
    namespace: Optional[str] = None
    pod_name: Optional[str] = None
    cluster_name: Optional[str] = None   # which k8s cluster this incident was resolved to
    status: str = Field(default="pending")  # pending | collecting | rca_running | notified | remediated | closed
    evidence: Optional[str] = None          # JSON blob: {logs, events, metrics}
    rca_report: Optional[str] = None        # JSON blob: agentic loop output
    jira_ticket_key: Optional[str] = None
    jira_ticket_url: Optional[str] = None
    notification_sent_at: Optional[datetime] = utc_optional_field()
    remediation_action: Optional[str] = None
    remediation_outcome: Optional[str] = None
    workflow_run_id: Optional[int] = None
    created_at: datetime = utc_field()
    resolved_at: Optional[datetime] = utc_optional_field()
