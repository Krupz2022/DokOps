from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from app.api import deps
from app.models.user import User
from app.services.toolset_service import toolset_service
from app.services.env_service import env_var_service

router = APIRouter()

@router.get("/builtin")
def list_builtin_tools(current_user: User = Depends(deps.get_current_user)) -> Any:
    """
    List all built-in global tools from the registry.
    """
    from app.tools.registry import TOOL_REGISTRY
    tools = []
    for name, info in TOOL_REGISTRY.items():
        tools.append({
            "name": name,
            "description": info.get("description", ""),
            "inputs": info.get("inputs", []),
            "operation_type": info.get("operation_type", "read"),
            "requires_confirmation": info.get("requires_confirmation", False),
            "risk_level": info.get("risk_level", "low")
        })
    return tools

@router.get("/toolsets")
def list_toolsets(current_user: User = Depends(deps.get_current_user)) -> Any:
    """
    List available AI toolsets.
    """
    return toolset_service.list_toolsets()

@router.post("/toolsets/{toolset_id}")
def save_toolset(
    toolset_id: str,
    content: str = Body(...),
    current_user: User = Depends(deps.get_current_active_superuser)
) -> Any:
    """
    Create or update an AI Toolset.
    """
    success = toolset_service.save_toolset(toolset_id, content)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid toolset format or save error.")
    return {"status": "success", "message": f"Toolset {toolset_id} saved."}

@router.get("/toolsets/{toolset_id}")
def get_toolset(
    toolset_id: str,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get a specific toolset definition.
    """
    toolset = toolset_service.get_toolset(toolset_id)
    if not toolset:
        raise HTTPException(status_code=404, detail="Toolset not found")
    return toolset

@router.get("/toolsets/{toolset_id}/raw")
def get_toolset_raw(
    toolset_id: str,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get the raw YAML text for a toolset (for the editor).
    """
    from fastapi.responses import PlainTextResponse
    raw = toolset_service.get_toolset_raw(toolset_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Toolset not found")
    return PlainTextResponse(content=raw)


# ─── Environment Variables ───────────────────────────────────────────────────

class EnvVarPayload(BaseModel):
    key: str
    value: str

@router.get("/env-vars")
def list_env_vars(current_user: User = Depends(deps.get_current_user)) -> Any:
    """List all toolset environment variables (values masked)."""
    return env_var_service.list_vars()

@router.post("/env-vars")
def set_env_var(
    payload: EnvVarPayload,
    current_user: User = Depends(deps.get_current_active_superuser)
) -> Any:
    """Set or update a toolset environment variable."""
    from app.services.env_service import PROTECTED_ENV_KEYS
    if payload.key.strip().upper() in PROTECTED_ENV_KEYS:
        raise HTTPException(status_code=400, detail=f"'{payload.key.upper()}' is a protected system variable and cannot be overridden.")
    success = env_var_service.set_var(payload.key, payload.value)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid variable name.")
    return {"status": "success", "message": f"Variable {payload.key.upper()} saved."}

@router.delete("/env-vars/{key}")
def delete_env_var(
    key: str,
    current_user: User = Depends(deps.get_current_active_superuser)
) -> Any:
    """Delete a toolset environment variable."""
    success = env_var_service.delete_var(key)
    if not success:
        raise HTTPException(status_code=404, detail="Variable not found.")
    return {"status": "success", "message": f"Variable {key} deleted."}

@router.post("/env-vars/bulk")
def bulk_import_env_vars(
    payload: dict = Body(...),
    current_user: User = Depends(deps.get_current_active_superuser)
) -> Any:
    """Bulk import environment variables from a JSON object { "KEY": "value", ... }."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object with key-value pairs.")

    imported = 0
    errors = []
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            errors.append(f"Skipped {key}: both key and value must be strings")
            continue
        success = env_var_service.set_var(key, value)
        if success:
            imported += 1
        else:
            errors.append(f"Failed to save {key}")

    return {
        "status": "success",
        "imported": imported,
        "errors": errors,
        "message": f"Imported {imported} variable(s)."
    }


@router.get("/builtin-toolsets")
def list_builtin_toolsets(current_user: User = Depends(deps.get_current_user)) -> Any:
    """List all built-in (read-only) toolsets shipped with DokOps."""
    return toolset_service.list_builtin_toolsets()

