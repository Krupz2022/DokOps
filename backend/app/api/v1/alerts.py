# backend/app/api/v1/alerts.py
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api import deps
from app.api.deps import get_current_active_superuser
from app.models.alert_incident import AlertIncident
from app.models.setting import SystemSetting
from app.models.user import User
from app.services.alert_handler_service import alert_handler_service
from app.services.alert_normalizers import (
    parse_alertmanager,
    parse_datadog,
    parse_elasticsearch,
    parse_generic,
    parse_grafana,
    parse_opsgenie,
    parse_pagerduty,
)
from app.services.webhook_security import validate_webhook_source

logger = logging.getLogger(__name__)
router = APIRouter()

_PARSERS = {
    "alertmanager": parse_alertmanager,
    "grafana": parse_grafana,
    "datadog": parse_datadog,
    "pagerduty": parse_pagerduty,
    "opsgenie": parse_opsgenie,
    "elasticsearch": parse_elasticsearch,
    "generic": parse_generic,
}


@router.post("/webhook/{source}", status_code=202)
async def receive_webhook(
    source: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(deps.get_db),
) -> Dict[str, Any]:
    """Receive an alert from an external monitoring system."""
    raw_body = await validate_webhook_source(source, request)
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    parser = _PARSERS[source]
    alerts = parser(payload)
    for alert in alerts:
        background_tasks.add_task(alert_handler_service.handle, alert, db)

    return {"status": "accepted", "alerts_queued": len(alerts)}


@router.get("/incidents", response_model=List[Dict[str, Any]])
def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    query = select(AlertIncident).order_by(AlertIncident.created_at.desc()).offset(offset).limit(limit)
    if status:
        query = query.where(AlertIncident.status == status)
    if severity:
        query = query.where(AlertIncident.severity == severity)
    incidents = db.exec(query).all()
    return [i.model_dump() for i in incidents]


@router.get("/incidents/{incident_id}", response_model=Dict[str, Any])
def get_incident(
    incident_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    incident = db.get(AlertIncident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident.model_dump()


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(
    incident_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_active_superuser),
) -> Dict[str, Any]:
    incident = db.get(AlertIncident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident.status = "closed"
    incident.resolved_at = datetime.now(timezone.utc)
    db.add(incident)
    db.commit()
    return {"status": "closed", "incident_id": incident_id}


@router.get("/policy")
def get_policy(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    row = db.get(SystemSetting, "alert_remediation_policy")
    if not row:
        return {}
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return {}


@router.put("/policy")
def update_policy(
    policy: Dict[str, Any],
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    row = db.get(SystemSetting, "alert_remediation_policy")
    if not row:
        row = SystemSetting(key="alert_remediation_policy", value=json.dumps(policy))
        db.add(row)
    else:
        row.value = json.dumps(policy)
        db.add(row)
    db.commit()
    return {"status": "saved"}


@router.get("/webhook-config")
def get_webhook_config(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    row = db.get(SystemSetting, "alert_webhook_secrets")
    if not row:
        return {}
    try:
        secrets = json.loads(row.value)
        return {k: "********" if v else "" for k, v in secrets.items()}
    except json.JSONDecodeError:
        return {}


@router.put("/webhook-config")
def update_webhook_config(
    config: Dict[str, str],
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    valid_sources = {"alertmanager", "grafana", "datadog", "pagerduty", "opsgenie", "elasticsearch", "generic"}
    filtered = {k: v for k, v in config.items() if k in valid_sources}
    row = db.get(SystemSetting, "alert_webhook_secrets")
    if not row:
        row = SystemSetting(key="alert_webhook_secrets", value=json.dumps(filtered))
        db.add(row)
    else:
        row.value = json.dumps(filtered)
        db.add(row)
    db.commit()
    return {"status": "saved"}


# ── Jira Configuration ────────────────────────────────────────────────────────

class JiraAlertConfig(BaseModel):
    instance_type: str = "cloud"
    base_url: str
    email: str = ""
    username: str = ""
    api_token: str = ""      # empty string = keep existing token
    project_key: str = ""


@router.get("/jira-config")
def get_jira_alert_config(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    row = db.get(SystemSetting, "alert_jira_config")
    if not row or not row.value:
        return {}
    try:
        config = json.loads(row.value)
    except json.JSONDecodeError:
        return {}
    if config.get("api_token"):
        config["api_token"] = "••••••"
    return config


@router.put("/jira-config")
def save_jira_alert_config(
    config: JiraAlertConfig,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    existing: dict = {}
    row = db.get(SystemSetting, "alert_jira_config")
    if row and row.value:
        try:
            existing = json.loads(row.value)
        except json.JSONDecodeError:
            pass

    data = {
        "instance_type": config.instance_type,
        "base_url": config.base_url.rstrip("/"),
        "email": config.email,
        "username": config.username,
        "project_key": config.project_key,
        "api_token": config.api_token if config.api_token else existing.get("api_token", ""),
    }

    if row:
        row.value = json.dumps(data)
        db.add(row)
    else:
        db.add(SystemSetting(key="alert_jira_config", value=json.dumps(data)))
    db.commit()
    return {"status": "saved"}


@router.post("/jira-test")
async def test_jira_alert_connection(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    import aiohttp as _aiohttp

    row = db.get(SystemSetting, "alert_jira_config")
    if not row or not row.value:
        raise HTTPException(status_code=400, detail="Jira is not configured")
    try:
        cfg = json.loads(row.value)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid Jira config")

    base_url = cfg.get("base_url", "").rstrip("/")
    instance_type = cfg.get("instance_type", "cloud")
    token = cfg.get("api_token", "")
    api_version = "3" if instance_type == "cloud" else "2"
    url = f"{base_url}/rest/api/{api_version}/myself"

    if instance_type == "server_pat":
        req_headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        auth = None
    else:
        user = cfg.get("email", "") if instance_type == "cloud" else cfg.get("username", "")
        req_headers = {"Accept": "application/json"}
        auth = _aiohttp.BasicAuth(user, token)

    try:
        timeout = _aiohttp.ClientTimeout(total=10)
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=req_headers, auth=auth) as resp:
                if resp.status in (200, 201):
                    return {"status": "connected"}
                text = await resp.text()
                raise HTTPException(status_code=503, detail=f"Jira returned {resp.status}: {text[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
