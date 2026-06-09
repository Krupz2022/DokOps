import asyncio
import base64
import json
import secrets
import time
import aiohttp
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from pydantic import BaseModel, SecretStr
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.api import deps
from app.core.god_mode import is_god_mode_active
from app.models.user import User
from app.models.workflow import Workflow, WorkflowRun
from app.services import workflow_service as wf_svc
from app.services import agent_executor_service as agent_svc

router = APIRouter()

# Short-lived SSE tickets: ticket → (username, run_id, expires_at)
_sse_tickets: Dict[str, tuple] = {}

_JIRA_TYPE_MAP: dict[str, str] = {
    "string": "string", "any": "string",
    "number": "number",
    "array": "array",
    "option": "option",
    "user": "user",
    "date": "date", "datetime": "date",
}


def _jira_auth_headers(instance_type: str, email: str, username: str, api_token: str) -> dict:
    """Build Authorization header dict for a Jira request.
    Callers pass api_token as a plain str (call .get_secret_value() first for SecretStr fields)."""
    if instance_type == "server_pat":
        return {"Accept": "application/json", "Authorization": f"Bearer {api_token}"}
    user = email if instance_type == "cloud" else username
    encoded = base64.b64encode(f"{user}:{api_token}".encode()).decode()
    return {"Accept": "application/json", "Authorization": f"Basic {encoded}"}


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    trigger_type: str = "manual"
    cron_schedule: Optional[str] = None
    trigger_config: Optional[str] = None
    input_schema: Dict[str, Any] = {}
    steps: List[Dict[str, Any]] = []
    # Agent fields
    workflow_type: str = "scripted"
    agent_goal: Optional[str] = None
    agent_approved_tools: List[Dict[str, Any]] = []
    agent_cluster_ids: List[str] = []
    agent_minion_ids: List[str] = []
    agent_max_retries: int = 3
    agent_timeout_seconds: int = 900
    agent_approval_timeout_seconds: int = 600
    agent_notifications: Dict[str, Any] = {}


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    cron_schedule: Optional[str] = None
    trigger_config: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    # Agent fields
    workflow_type: Optional[str] = None
    agent_goal: Optional[str] = None
    agent_approved_tools: Optional[List[Dict[str, Any]]] = None
    agent_cluster_ids: Optional[List[str]] = None
    agent_minion_ids: Optional[List[str]] = None
    agent_max_retries: Optional[int] = None
    agent_timeout_seconds: Optional[int] = None
    agent_approval_timeout_seconds: Optional[int] = None
    agent_notifications: Optional[Dict[str, Any]] = None


class DiscoverToolsRequest(BaseModel):
    goal: str


class JiraFieldsRequest(BaseModel):
    base_url: str
    email: str
    api_token: SecretStr
    project_key: str
    issue_type: str = "Bug"
    instance_type: str = "cloud"
    username: str = ""


class JiraIssueTypesRequest(BaseModel):
    base_url: str
    email: str
    api_token: SecretStr
    project_key: str
    instance_type: str = "cloud"
    username: str = ""


class JiraUserSearchRequest(BaseModel):
    base_url: str
    email: str
    api_token: SecretStr
    query: str
    instance_type: str = "cloud"
    username: str = ""


@router.post("/agents/discover-tools")
async def discover_tools(
    body: DiscoverToolsRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    tools = await agent_svc.discover_tools_for_goal(body.goal)
    return {"tools": tools}


@router.post("/connectors/jira/fields")
async def get_jira_fields(
    body: JiraFieldsRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    base_url = body.base_url.rstrip("/")
    token = body.api_token.get_secret_value()
    headers = _jira_auth_headers(body.instance_type, body.email, body.username, token)

    async with aiohttp.ClientSession() as session:
        if body.instance_type == "cloud":
            # Cloud v3: two requests — resolve issue type ID, then fetch its fields
            url = f"{base_url}/rest/api/3/issue/createmeta/{body.project_key}/issuetypes"
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    raise HTTPException(status_code=400, detail="Jira rejected credentials: check email and API token")
                if resp.status != 200:
                    text = await resp.text()
                    raise HTTPException(status_code=502, detail=f"Jira API error: {text}")
                data = await resp.json()

            issue_types = data.get("issueTypes", [])
            issue_type_id = next(
                (it["id"] for it in issue_types if it.get("name", "").lower() == body.issue_type.lower()),
                issue_types[0]["id"] if issue_types else None,
            )
            if not issue_type_id:
                raise HTTPException(
                    status_code=502,
                    detail=f"Issue type '{body.issue_type}' not found in project {body.project_key}",
                )

            url = f"{base_url}/rest/api/3/issue/createmeta/{body.project_key}/issuetypes/{issue_type_id}"
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise HTTPException(status_code=502, detail=f"Jira fields error: {text}")
                fields_data = await resp.json()

            raw_fields = fields_data.get("fields", [])

        else:
            # createmeta removed in Jira 9.x — use /project/{key}/statuses for issue types
            # then /issue/createmeta/{project}/issuetypes/{id}/fields for fields (9.x)
            # or fall back to the newer per-issuetype fields endpoint
            issue_type_url = f"{base_url}/rest/api/2/project/{body.project_key}"
            async with session.get(issue_type_url, headers=headers) as resp:
                if resp.status == 401:
                    raise HTTPException(status_code=400, detail="Jira rejected credentials: check username and password/token")
                if resp.status == 404:
                    raise HTTPException(status_code=502, detail=f"Project '{body.project_key}' not found")
                if resp.status != 200:
                    text = await resp.text()
                    raise HTTPException(status_code=502, detail=f"Jira API error: {text}")
                proj_data = await resp.json(content_type=None)

            issue_types = proj_data.get("issueTypes", [])
            matching = next(
                (it for it in issue_types if it.get("name", "").lower() == body.issue_type.lower()),
                issue_types[0] if issue_types else None,
            )
            if not matching:
                raise HTTPException(status_code=502, detail=f"Issue type '{body.issue_type}' not found in project")

            issue_type_id = matching["id"]
            fields_url = f"{base_url}/rest/api/2/issue/createmeta/{body.project_key}/issuetypes/{issue_type_id}"
            async with session.get(fields_url, headers=headers, params={"maxResults": 500}) as resp:
                if resp.status != 200:
                    # Older server: fall back to createmeta with expand
                    fallback_url = f"{base_url}/rest/api/2/issue/createmeta"
                    params = {"projectKeys": body.project_key, "issuetypeIds": issue_type_id, "expand": "projects.issuetypes.fields"}
                    async with session.get(fallback_url, headers=headers, params=params) as fb:
                        if fb.status != 200:
                            raw_fields = []
                        else:
                            fb_data = await fb.json(content_type=None)
                            projects = fb_data.get("projects", [])
                            it_list = projects[0].get("issuetypes", []) if projects else []
                            fields_dict = it_list[0].get("fields", {}) if it_list else {}
                            raw_fields = [{"fieldId": fid, "name": fi.get("name", ""), "required": fi.get("required", False), "schema": fi.get("schema", {}), "allowedValues": fi.get("allowedValues", [])} for fid, fi in fields_dict.items()]
                else:
                    fields_data = await resp.json(content_type=None)
                    raw_fields = fields_data.get("fields", [])

    result = []
    for field in raw_fields:
        schema = field.get("schema", {})
        jira_type = schema.get("type", "string")
        normalized = _JIRA_TYPE_MAP.get(jira_type, "string")
        allowed = [
            av.get("name") or av.get("value", "")
            for av in field.get("allowedValues", [])
            if av.get("name") or av.get("value")
        ]
        result.append({
            "id": field.get("fieldId", field.get("key", "")),
            "name": field.get("name", ""),
            "type": normalized,
            "required": field.get("required", False),
            "allowed_values": allowed if allowed else None,
        })

    result.sort(key=lambda f: (not f["required"], f["name"].lower()))
    return result


@router.post("/connectors/jira/issue-types")
async def get_jira_issue_types(
    body: JiraIssueTypesRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    import logging as _log
    log = _log.getLogger("jira.issue_types")

    base_url = body.base_url.rstrip("/")
    token = body.api_token.get_secret_value()
    headers = _jira_auth_headers(body.instance_type, body.email, body.username, token)
    auth_user = body.email if body.instance_type == "cloud" else body.username

    log.debug("[jira/issue-types] instance=%s base_url=%s project=%s auth_user=%s",
                body.instance_type, base_url, body.project_key, auth_user)

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            if body.instance_type == "cloud":
                url = f"{base_url}/rest/api/3/issue/createmeta/{body.project_key}/issuetypes"
                log.debug("[jira/issue-types] GET %s", url)
                async with session.get(url, headers=headers) as resp:
                    text = await resp.text()
                    log.debug("[jira/issue-types] status=%d body=%s", resp.status, text[:500])
                    if resp.status == 401:
                        raise HTTPException(status_code=400, detail="Jira rejected credentials: check email and API token")
                    if resp.status != 200:
                        raise HTTPException(status_code=502, detail=f"Jira {resp.status}: {text[:300]}")
                    data = await resp.json(content_type=None)
                return [it["name"] for it in data.get("issueTypes", []) if it.get("name")]
            else:
                # createmeta was removed in Jira 9.x — use /project/{key} which returns issueTypes directly
                url = f"{base_url}/rest/api/2/project/{body.project_key}"
                log.debug("[jira/issue-types] GET %s", url)
                async with session.get(url, headers=headers) as resp:
                    text = await resp.text()
                    log.debug("[jira/issue-types] status=%d body=%s", resp.status, text[:500])
                    if resp.status == 401:
                        raise HTTPException(status_code=400, detail="Jira rejected credentials: check username and password/token")
                    if resp.status == 404:
                        raise HTTPException(status_code=502, detail=f"Project '{body.project_key}' not found in Jira")
                    if resp.status != 200:
                        raise HTTPException(status_code=502, detail=f"Jira {resp.status}: {text[:300]}")
                    data = await resp.json(content_type=None)
                issue_types = data.get("issueTypes", [])
                log.debug("[jira/issue-types] found=%d types", len(issue_types))
                return [it["name"] for it in issue_types if it.get("name")]
    except HTTPException:
        raise
    except aiohttp.ClientConnectorError as e:
        log.debug("[jira/issue-types] connection failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Cannot reach Jira at {base_url} — check the URL and network connectivity")
    except TimeoutError:
        raise HTTPException(status_code=502, detail=f"Connection to {base_url} timed out (10s)")
    except Exception as e:
        log.debug("[jira/issue-types] unexpected error: %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/connectors/jira/users/search")
async def search_jira_users(
    body: JiraUserSearchRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    base_url = body.base_url.rstrip("/")
    token = body.api_token.get_secret_value()
    headers = _jira_auth_headers(body.instance_type, body.email, body.username, token)

    async with aiohttp.ClientSession() as session:
        if body.instance_type == "cloud":
            url = f"{base_url}/rest/api/3/user/search"
            params = {"query": body.query}
        else:
            url = f"{base_url}/rest/api/2/user/search"
            params = {"username": body.query}

        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 401:
                raise HTTPException(status_code=400, detail="Jira rejected credentials: check email and API token")
            if resp.status != 200:
                text = await resp.text()
                raise HTTPException(status_code=502, detail=f"Jira user search error: {text}")
            users = await resp.json()

    if body.instance_type == "cloud":
        return [
            {
                "account_id": u.get("accountId", ""),
                "display_name": u.get("displayName", ""),
                "email": u.get("emailAddress", ""),
            }
            for u in users
            if u.get("accountType") == "atlassian"
        ]
    else:
        return [
            {
                "account_id": u.get("name", ""),
                "display_name": u.get("displayName", ""),
                "email": u.get("emailAddress", ""),
            }
            for u in users
        ]


@router.get("")
def list_workflows(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    return db.exec(select(Workflow)).all()


def _check_pre_approved_destructive(tools: List[Dict[str, Any]], user_id: int) -> None:
    has_pre_approved_destructive = any(
        t.get("is_destructive") and t.get("pre_approved") for t in tools
    )
    if has_pre_approved_destructive and not is_god_mode_active(user_id):
        raise HTTPException(
            status_code=403,
            detail="Pre-approving destructive tools requires God Mode to be active.",
        )


@router.post("")
def create_workflow(
    body: WorkflowCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    _check_pre_approved_destructive(body.agent_approved_tools, current_user.id)
    wf = Workflow(**body.model_dump(), created_by=current_user.username)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _require_workflow_owner(wf: Workflow, current_user: User) -> None:
    """Raise 403 if current user is not the workflow owner or a superuser."""
    if wf.created_by != current_user.username and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorised to access this workflow")


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    run = db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    wf = db.get(Workflow, run.workflow_id)
    if wf:
        _require_workflow_owner(wf, current_user)
    return run


@router.post("/runs/{run_id}/stream-ticket")
def issue_stream_ticket(
    run_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Exchange a full JWT (via Bearer/cookie) for a short-lived opaque SSE ticket."""
    now = time.time()
    # Purge expired tickets
    for k in [k for k, v in _sse_tickets.items() if v[2] < now]:
        del _sse_tickets[k]
    ticket = secrets.token_urlsafe(32)
    _sse_tickets[ticket] = (current_user.username, run_id, now + 30)
    return {"ticket": ticket}


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: int,
    db: Session = Depends(deps.get_db),
    ticket: Optional[str] = None,
    bearer_user: Optional[User] = Depends(deps.get_optional_current_user),
) -> Any:
    # Accept either a short-lived ticket (EventSource) or standard Bearer auth (fetch)
    current_user = None
    if ticket:
        entry = _sse_tickets.pop(ticket, None)
        if entry and entry[1] == run_id and entry[2] >= time.time():
            current_user = db.query(User).filter(User.username == entry[0]).first()
    if not current_user:
        current_user = bearer_user
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    run = db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    wf = db.get(Workflow, run.workflow_id)
    if wf:
        _require_workflow_owner(wf, current_user)

    async def event_stream():
        queue = wf_svc._run_queues.get(run_id)
        if not queue:
            # Queue is gone — run already finished or server was restarted.
            # Synthesise a completed event from DB so the frontend doesn't hang.
            final_run = db.get(WorkflowRun, run_id)
            final_status = final_run.status if final_run else "failed"
            if final_status in ("completed", "failed", "timed_out"):
                yield f"data: {json.dumps({'type': 'completed', 'run_id': run_id, 'status': final_status})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Run stream unavailable — reload to see latest status'})}\n\n"
            return
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") == "completed":
                wf_svc._run_queues.pop(run_id, None)
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    _require_workflow_owner(wf, current_user)
    return wf


@router.put("/{workflow_id}")
def update_workflow(
    workflow_id: int,
    body: WorkflowUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    _require_workflow_owner(wf, current_user)
    if body.agent_approved_tools is not None:
        _check_pre_approved_destructive(body.agent_approved_tools, current_user.id)
    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(wf, key, value)
    wf.updated_at = datetime.now(timezone.utc)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@router.delete("/{workflow_id}")
def delete_workflow(
    workflow_id: int,
    db: Session = Depends(deps.get_db),
    _: User = Depends(deps.require_god_mode),
) -> Any:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db.delete(wf)
    db.commit()
    return {"message": "Deleted"}


@router.get("/{workflow_id}/runs")
def list_runs(
    workflow_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    _require_workflow_owner(wf, current_user)
    return db.exec(
        select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id)
    ).all()


class RunWorkflowRequest(BaseModel):
    input: Dict[str, Any] = {}


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: int,
    body: RunWorkflowRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    _require_workflow_owner(wf, current_user)
    run = wf_svc.create_run(workflow_id, body.input, "manual", db, user_id=current_user.id)
    if wf.workflow_type == "agent":
        asyncio.create_task(agent_svc.run_agent_background(run.id, workflow_id))
    else:
        asyncio.create_task(wf_svc.run_workflow_background(run.id, workflow_id, body.input))
    return {"run_id": run.id, "status": "started"}


@router.post("/webhook/{token}")
async def webhook_trigger(
    token: str,
    payload: Dict[str, Any],
    db: Session = Depends(deps.get_db),
) -> Any:
    wf = db.exec(select(Workflow).where(Workflow.webhook_token == token)).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    run = wf_svc.create_run(wf.id, payload, "webhook", db)
    if wf.workflow_type == "agent":
        asyncio.create_task(agent_svc.run_agent_background(run.id, wf.id))
    else:
        asyncio.create_task(wf_svc.run_workflow_background(run.id, wf.id, payload))
    return {"run_id": run.id, "status": "started"}


@router.post("/{workflow_id}/runs/{run_id}/approve")
async def approve_run_action(
    workflow_id: int,
    run_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    run = db.get(WorkflowRun, run_id)
    if not run or run.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Run not found")
    wf = db.get(Workflow, workflow_id)
    if wf:
        _require_workflow_owner(wf, current_user)
    if run.status != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Run is not awaiting approval")
    agent_svc.resolve_approval(run_id, "approve")
    return {"message": "approved"}


@router.post("/{workflow_id}/runs/{run_id}/skip")
async def skip_run_action(
    workflow_id: int,
    run_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    run = db.get(WorkflowRun, run_id)
    if not run or run.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Run not found")
    wf = db.get(Workflow, workflow_id)
    if wf:
        _require_workflow_owner(wf, current_user)
    if run.status != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Run is not awaiting approval")
    agent_svc.resolve_approval(run_id, "skip")
    return {"message": "skipped"}
