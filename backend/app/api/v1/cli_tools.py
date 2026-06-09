from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session
from datetime import datetime

from app.api.deps import get_current_active_superuser, get_db, require_god_mode
from app.models.user import User
from app.models.audit import AuditLog
from app.services.cli_tool_service import cli_tool_service

router = APIRouter()


async def _write_audit(db: Session, actor: str, action: str, resource: str, result: str, mode: str, details: Optional[str] = None):
    log = AuditLog(
        timestamp=datetime.utcnow(),
        actor=actor,
        action=action,
        resource=resource,
        result=result,
        mode=mode,
        source="SYSTEM",
        details=details,
    )
    db.add(log)
    db.commit()


@router.get("/")
async def detect_tools(current_user: User = Depends(get_current_active_superuser)):
    """Detect all pre-defined tools and return their install status."""
    return await cli_tool_service.detect_all()


@router.post("/{tool_name}/install")
async def install_tool(
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_god_mode),
):
    """Install a pre-defined tool. Requires God Mode."""
    result = await cli_tool_service.install_predefined(tool_name)
    await _write_audit(
        db,
        actor=current_user.username,
        action=f"install_cli_tool:{tool_name}",
        resource=f"cli_tool/{tool_name}",
        result="SUCCESS" if result["success"] else "FAILURE",
        mode="GOD",
        details=f"platform={cli_tool_service._detect_platform()} | exit_code={0 if result['success'] else 1} | out={result['output'][:300] if result['output'] else ''}",
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["output"])
    return result


class CustomToolPayload(BaseModel):
    name: str
    platform: str   # "windows" | "linux" | "both"
    command: str


@router.get("/custom")
async def list_custom_tools(current_user: User = Depends(get_current_active_superuser)):
    """List all saved custom tool definitions."""
    return cli_tool_service.list_custom_tools()


@router.post("/custom")
async def save_custom_tool(
    payload: CustomToolPayload,
    current_user: User = Depends(get_current_active_superuser),
):
    """Save a custom tool installer definition."""
    if payload.platform not in ("windows", "linux", "both"):
        raise HTTPException(status_code=422, detail="platform must be 'windows', 'linux', or 'both'")
    cli_tool_service.save_custom_tool(payload.model_dump())
    return {"saved": True}


@router.delete("/custom/{tool_name}")
async def delete_custom_tool(
    tool_name: str,
    current_user: User = Depends(get_current_active_superuser),
):
    """Delete a custom tool definition."""
    cli_tool_service.delete_custom_tool(tool_name)
    return {"deleted": True}


@router.post("/custom/{tool_name}/install")
async def install_custom_tool(
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_god_mode),
):
    """Run a custom tool's install command. Requires God Mode."""
    tools = cli_tool_service.list_custom_tools()
    tool = next((t for t in tools if t["name"] == tool_name), None)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Custom tool '{tool_name}' not found")

    result = await cli_tool_service.install_custom_tool(tool)

    await _write_audit(
        db,
        actor=current_user.username,
        action=f"install_custom_tool:{tool_name}",
        resource=f"cli_tool/custom/{tool_name}",
        result="SUCCESS" if result["success"] else "FAILURE",
        mode="GOD",
        details=f"cmd={tool['command'][:200]} | platform={cli_tool_service._detect_platform()} | exit_code={0 if result['success'] else 1} | out={result['output'][:200]}",
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["output"])
    return result
