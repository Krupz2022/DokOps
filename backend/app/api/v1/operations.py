import json
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api import deps
from app.models.user import User
from app.core import db as _db_module
from app.models.audit import AuditLog

from app.tools import registry
from app.tools.registry import execute_tool_async
from app.services.ai_service import signal_approval
from app.core.god_mode import is_god_mode_active


def _derive_resource(tool_name: str, inputs: dict) -> str:
    mapping = {
        "scale_deployment":           lambda i: f"deployment/{i.get('deployment_name', '?')} ({i.get('namespace', '?')})",
        "delete_deployment":          lambda i: f"deployment/{i.get('deployment_name', '?')} ({i.get('namespace', '?')})",
        "rollback_deployment":        lambda i: f"deployment/{i.get('deployment_name', '?')} ({i.get('namespace', '?')})",
        "patch_deployment_resources": lambda i: f"deployment/{i.get('deployment_name', '?')} ({i.get('namespace', '?')})",
        "patch_deployment_env":       lambda i: f"deployment/{i.get('deployment_name', '?')} ({i.get('namespace', '?')})",
        "deploy_application":         lambda i: f"deployment/{i.get('name', '?')} ({i.get('namespace', '?')})",
        "restart_pod":                lambda i: f"pod/{i.get('pod_name', '?')} ({i.get('namespace', '?')})",
        "patch_secret":               lambda i: f"secret/{i.get('name', '?')} ({i.get('namespace', '?')})",
        "update_configmap":           lambda i: f"configmap/{i.get('configmap_name', '?')} ({i.get('namespace', '?')})",
        "create_namespace":           lambda i: f"namespace/{i.get('namespace', '?')}",
        "delete_namespace":           lambda i: f"namespace/{i.get('namespace', '?')}",
        "cordon_node":                lambda i: f"node/{i.get('node_name', '?')}",
        "uncordon_node":              lambda i: f"node/{i.get('node_name', '?')}",
        "drain_node":                 lambda i: f"node/{i.get('node_name', '?')}",
        "apply_manifest":             lambda i: "manifest/apply",
    }
    fn = mapping.get(tool_name)
    if fn:
        return fn(inputs)
    return f"{tool_name}: {json.dumps(inputs)}"


async def _write_mutation_audit(
    actor: str,
    tool_name: str,
    inputs: dict,
    result: str,
    details: dict,
) -> None:
    log = AuditLog(
        actor=actor,
        action=tool_name,
        resource=_derive_resource(tool_name, inputs),
        result=result,
        mode="GOD",
        source="K8S",
        details=json.dumps(details),
    )
    async with _db_module.AsyncSessionLocal() as audit_db:
        audit_db.add(log)
        await audit_db.commit()


router = APIRouter()

# In-memory store for pending operations
# Format: {uuid_str: PendingOperationDict}
pending_operations_store: Dict[str, Dict[str, Any]] = {}

class PendingOperationCreate(BaseModel):
    session_id: str
    tool_name: str
    tool_inputs: Dict[str, Any]
    confirmation_message: str
    risk_level: str

class PendingOperationResponse(BaseModel):
    id: str
    session_id: str
    tool_name: str
    tool_inputs: Dict[str, Any]
    confirmation_message: str
    risk_level: str
    created_at: float
    status: str
    executed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None

@router.post("/pending", response_model=PendingOperationResponse)
async def create_pending_operation(
    op: PendingOperationCreate,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """Create a new pending operation request"""
    op_id = str(uuid.uuid4())
    new_op = {
        "id": op_id,
        "session_id": op.session_id,
        "tool_name": op.tool_name,
        "tool_inputs": op.tool_inputs,
        "confirmation_message": op.confirmation_message,
        "risk_level": op.risk_level,
        "created_at": time.time(),
        "status": "pending",
        "executed_at": None,
        "result": None
    }
    pending_operations_store[op_id] = new_op
    return new_op

@router.get("/pending", response_model=List[PendingOperationResponse])
async def list_pending_operations(
    session_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Get all pending operations for a session"""
    now = time.time()
    result = []
    for op_id, op in list(pending_operations_store.items()):
        if op["status"] == "pending" and (now - op["created_at"]) > 300:
            op["status"] = "expired"
            if not op.get("audit_written"):
                op["audit_written"] = True
                await _write_mutation_audit(
                    actor="system",
                    tool_name=op["tool_name"],
                    inputs=op["tool_inputs"],
                    result="EXPIRED",
                    details={"inputs": op["tool_inputs"], "reason": "pending operation timed out after 5 minutes"},
                )

        if op["session_id"] == session_id:
            result.append(op)

    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result

@router.get("/pending/{op_id}", response_model=PendingOperationResponse)
async def get_pending_operation(
    op_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Get a specific pending operation"""
    if op_id not in pending_operations_store:
        raise HTTPException(status_code=404, detail="Operation not found")

    op = pending_operations_store[op_id]

    if op["status"] == "pending" and (time.time() - op["created_at"]) > 300:
        op["status"] = "expired"
        if not op.get("audit_written"):
            op["audit_written"] = True
            await _write_mutation_audit(
                actor="system",
                tool_name=op["tool_name"],
                inputs=op["tool_inputs"],
                result="EXPIRED",
                details={"inputs": op["tool_inputs"], "reason": "pending operation timed out after 5 minutes"},
            )

    return op

@router.post("/pending/{op_id}/approve", response_model=PendingOperationResponse)
async def approve_pending_operation(
    op_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Approve and execute a pending operation"""
    if op_id not in pending_operations_store:
        raise HTTPException(status_code=404, detail="Operation not found")

    op = pending_operations_store[op_id]

    if op["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Operation cannot be approved. Current status: {op['status']}")

    # God Mode check — only God Mode is required (superuser is not needed)
    if not is_god_mode_active(current_user.id):
        op["status"] = "rejected"
        op["executed_at"] = time.time()
        op["result"] = {
            "success": False,
            "error": "God Mode is not active for your session. Enable it from the header toggle before approving operations.",
            "source": "system",
        }
        signal_approval(op_id)  # Unblock the waiting agent loop so it can tell the user
        raise HTTPException(
            status_code=403,
            detail="God Mode is not active for your session. Enable it from the header toggle, then retry.",
        )

    tool_name = op["tool_name"]
    tool_inputs = op["tool_inputs"]

    try:
        if tool_name.startswith("mcp__"):
            from app.services.mcp_client_service import mcp_client_service
            result = mcp_client_service.execute_tool(tool_name, tool_inputs, confirmed=True)
        else:
            result = await execute_tool_async(tool_name, tool_inputs, confirmed=True)

        result_str = "SUCCESS" if (isinstance(result, dict) and result.get("success")) else "FAILURE"
        op["status"] = "approved"
        op["executed_at"] = time.time()
        op["result"] = result
        await _write_mutation_audit(
            actor=current_user.username,
            tool_name=tool_name,
            inputs=tool_inputs,
            result=result_str,
            details={"inputs": tool_inputs, "outcome": result},
        )
        signal_approval(op_id)  # Resume the waiting agent loop
        return op
    except Exception as e:
        op["status"] = "failed"
        op["executed_at"] = time.time()
        op["result"] = {"success": False, "error": str(e), "source": "system"}
        await _write_mutation_audit(
            actor=current_user.username,
            tool_name=tool_name,
            inputs=tool_inputs,
            result="FAILURE",
            details={"inputs": tool_inputs, "error": str(e)},
        )
        signal_approval(op_id)  # Resume loop even on failure so agent can react
        return op

@router.post("/pending/{op_id}/reject", response_model=PendingOperationResponse)
async def reject_pending_operation(
    op_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Reject a pending operation"""
    if op_id not in pending_operations_store:
        raise HTTPException(status_code=404, detail="Operation not found")

    op = pending_operations_store[op_id]

    if op["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Operation cannot be rejected. Current status: {op['status']}")

    op["status"] = "rejected"
    op["executed_at"] = time.time()
    await _write_mutation_audit(
        actor=current_user.username,
        tool_name=op["tool_name"],
        inputs=op["tool_inputs"],
        result="REJECTED",
        details={"inputs": op["tool_inputs"]},
    )
    signal_approval(op_id)  # Resume loop so agent knows the operation was rejected
    return op
