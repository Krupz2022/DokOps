from fastapi import APIRouter, Depends, HTTPException, Body, Header
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from app.api import deps
from app.models.user import User
from app.models.setting import SystemSetting
from app.core.settings_cache import invalidate as _invalidate_settings_cache
from app.services.ai_service import ai_service
from app.services.runbook_service import runbook_service
from app.services.k8s_service import k8s_service

router = APIRouter()

@router.post("/config")
def save_ai_config(
    config: Dict[str, str],
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Save AI configuration settings.
    """
    allowed_keys = [
        "ai_provider", "ai_api_key", "ai_base_url", "ai_model", "ai_api_version",
        "ai_fast_model", "ai_fast_base_url", "ai_fast_api_key",
        "rag_enabled", "rag_chroma_host", "rag_chroma_port",
        "rag_embedding_provider", "rag_embedding_api_key", "rag_embedding_model", "rag_embedding_base_url",
        "minion_auto_accept_key",
        "alert_slack_webhook", "alert_teams_webhook", "alert_suppression_minutes",
        "ctx_tool_budget", "ctx_compaction_threshold", "ctx_keep_recent",
    ]

    import hashlib

    for key, value in config.items():
        if key not in allowed_keys:
            continue
        # Store the auto-accept key as bcrypt hash — never plaintext
        if key == "minion_auto_accept_key":
            from app.services.minion_service import hash_token
            value = hash_token(value)
        setting = db.get(SystemSetting, key)
        if not setting:
            setting = SystemSetting(key=key, value=value)
            db.add(setting)
        else:
            setting.value = value
            db.add(setting)

    db.commit()
    _invalidate_settings_cache()
    return {"message": "Configuration saved"}

@router.get("/config")
def get_ai_config(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Get current AI configuration (excluding sensitive keys).
    """
    settings = db.exec(select(SystemSetting)).all()
    config = {}
    for s in settings:
        config[s.key] = s.value
        
    # Mask API Key
    if "ai_api_key" in config:
        config["ai_api_key"] = "********"
    if "ai_fast_api_key" in config:
        config["ai_fast_api_key"] = "********"

    return config

@router.post("/test")
def test_ai_connection(
    config: Dict[str, str] = Body(None),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Test connection to the configured AI provider.
    """
    try:
        ai_service.test_connection(config_override=config)
        return {"status": "success", "message": "Connection successful"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/analyze/logs")
async def analyze_logs(
    namespace: str = Body(...),
    pod_name: str = Body(...),
    query: str = Body(...),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Analyze pod logs using AI.
    """
    # 1. Fetch Logs
    logs = await k8s_service.get_pod_logs(namespace, pod_name, tail_lines=500)

    # 2. Analyze
    analysis = await ai_service.analyze_logs(logs, query)

    return {"analysis": analysis}

@router.get("/runbooks")
def list_runbooks(current_user: User = Depends(deps.get_current_user)) -> Any:
    """
    List available automated runbooks.
    """
    return runbook_service.list_runbooks()

class MatchRequest(BaseModel):
    query: str

@router.post("/runbooks/match")
def match_runbook(
    req: MatchRequest,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Match a user query to the best available runbook using AI classification.
    """
    return runbook_service.match_runbook_logic(req.query)

@router.post("/runbooks/{runbook_id}")
def create_runbook(
    runbook_id: str,
    content: str = Body(...),
    current_user: User = Depends(deps.get_current_active_superuser)
) -> Any:
    """
    Create or update an AI Runbook.
    """
    success = runbook_service.save_runbook(runbook_id, content)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid runbook format or save error.")
    return {"status": "success", "message": f"Runbook {runbook_id} saved."}


@router.post("/diagnose/stream")
async def diagnose_stream(
    namespace: str = Body(...),
    pod_name: str = Body(...),
    query: str = Body(...),
    runbook_id: Optional[str] = Body(None),
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Any:
    import json
    async def event_stream():
        full_query = f"Investigate pod {namespace}/{pod_name}. {query}"
        async for step in ai_service.run_global_agentic_loop(
            full_query,
            context=cluster_context,
            runbook_id=runbook_id,
        ):
            yield f"data: {json.dumps(step)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.post("/global/stream")
async def global_diagnose_stream(
    query: str = Body(..., embed=True),
    runbook_id: Optional[str] = Body(None),
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Any:
    import json
    async def event_stream():
        async for step in ai_service.run_global_agentic_loop(query, context=cluster_context, runbook_id=runbook_id):
            yield f"data: {json.dumps(step)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.post("/analyze/batch")
async def analyze_batch(
    pods: List[Dict[str, str]] = Body(...), # [{'namespace': 'a', 'pod_name': 'b'}]
    query: str = Body(...),
    runbook_id: Optional[str] = Body(None),
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Any:
    """
    Analyze logs for multiple pods via Re-Act streaming engine.
    """
    import json
    async def event_stream():
        async for step in ai_service.run_batch_agentic_loop(pods, query, context=cluster_context, runbook_id=runbook_id):
            yield f"data: {json.dumps(step)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
@router.post("/command")
async def ai_command(
    request: dict = Body(...),
    current_user: User = Depends(deps.get_current_user)
) -> Dict[str, Any]:
    """
    Process a natural language command using AI.
    Returns an Action Proposal or Search Results.
    """
    query = request.get("query")
    context = request.get("context", {})

    if not query:
        raise HTTPException(status_code=400, detail="Query required")

    # 1. Detect Intent with Context
    intent = ai_service.detect_intent(query, context)

    # 2. Ambiguity Resolution (Only for Actions)
    if intent.get("type") == "action_proposal" and not intent.get("namespace_explicit"):
        params = intent.get("parameters", {})
        name = params.get("name")

        if name:
            # Check if it exists in current namespace first?
            # User requirement: "find the pod with namespace if there are 2 pods it should find both"
            # So we ALWAYs check global if not explicit.

            matches = await k8s_service.find_deployments_by_name(name)

            if len(matches) == 0:
                pass # Let it fail normally or keep default
            elif len(matches) == 1:
                # Auto-switch to the found namespace
                found = matches[0]
                params["namespace"] = found["namespace"]
                intent["parameters"] = params
                intent["summary"] += f" (Found in {found['namespace']})"
            else:
                # Multiple matches -> Ambiguity
                # Return strict choices
                return {
                    "type": "disambiguation",
                    "message": f"Found '{name}' in multiple namespaces. Which one?",
                    "choices": matches,
                    "intent_template": intent # Pass the original intent so frontend can re-hydrate
                }

    return intent
