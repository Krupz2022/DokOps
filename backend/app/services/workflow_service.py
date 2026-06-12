import re
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.workflow import Workflow, WorkflowRun
from app.services.ai_service import ai_service


# Per-run event queues: run_id → asyncio.Queue
_run_queues: Dict[int, asyncio.Queue] = {}


def interpolate_variables(template: str, context: Dict[str, Any]) -> str:
    """Replace {{input.x}} and {{steps.x.y}} with values from context."""
    def replacer(match: re.Match) -> str:
        path = match.group(1).strip()
        parts = path.split(".")
        value: Any = context
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                raise ValueError(f"Variable '{{{{{path}}}}}' not found in execution context")
        return str(value)

    return re.sub(r"\{\{([^}]+)\}\}", replacer, template)


def interpolate_config(config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively interpolate all string values in a config dict."""
    result: Dict[str, Any] = {}
    for key, value in config.items():
        if isinstance(value, str):
            result[key] = interpolate_variables(value, context)
        elif isinstance(value, dict):
            result[key] = interpolate_config(value, context)
        else:
            result[key] = value
    return result


def _build_step_tool_schema(step: Dict[str, Any]) -> Dict[str, Any]:
    output_var = step.get("output_var") or step["id"]
    return {
        "type": "function",
        "function": {
            "name": output_var,
            "description": step.get("name", output_var),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def _update_step_result(run: WorkflowRun, step_id: str, db: Session, **kwargs: Any) -> None:
    results = list(run.step_results)
    for i, sr in enumerate(results):
        if sr.get("step_id") == step_id:
            results[i] = {**sr, **kwargs}
            break
    run.step_results = results
    db.add(run)
    db.commit()


async def create_run(
    workflow_id: int,
    trigger_input: Dict[str, Any],
    triggered_by: str,
    db: AsyncSession,
    user_id: Optional[int] = None,
) -> WorkflowRun:
    """Create a WorkflowRun record and register its event queue."""
    run = WorkflowRun(
        workflow_id=workflow_id,
        triggered_by=triggered_by,
        triggered_by_user_id=user_id,
        trigger_input=trigger_input,
        status="pending",
        step_results=[],
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    _run_queues[run.id] = asyncio.Queue()
    return run


async def run_workflow_background(
    run_id: int,
    workflow_id: int,
    trigger_input: Dict[str, Any],
    db: Optional[Session] = None,
) -> None:
    """Execute a workflow run. Pushes SSE events to the run's queue.

    ``db`` may be injected by tests; production callers omit it and a fresh
    session is opened so the background task is never bound to a request session.
    """
    from contextlib import contextmanager
    from app.services.connectors import get_connector
    from app.core.db import engine

    @contextmanager
    def _session():
        if db is not None:
            yield db
        else:
            # TODO(Phase 4c): replace with AsyncSessionLocal once run_workflow_background
            # is fully converted to async session ops throughout its body.
            with Session(engine) as s:  # noqa: Phase-3d-escape
                yield s

    with _session() as _db:
        run = _db.get(WorkflowRun, run_id)
        workflow = _db.get(Workflow, workflow_id)
        if not run or not workflow:
            return

        queue = _run_queues.get(run_id)

        async def emit(event: Dict[str, Any]) -> None:
            if queue:
                await queue.put(event)

        run.status = "running"
        run.step_results = [
            {
                "step_id": s["id"],
                "step_name": s.get("name", s["id"]),
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "output": None,
                "error": None,
            }
            for s in workflow.steps
        ]
        _db.add(run)
        _db.commit()

        context: Dict[str, Any] = {"input": trigger_input, "steps": {}}
        workflow_tool_executors: Dict[str, Any] = {}
        workflow_tools_schema: List[Dict[str, Any]] = []

        for step in workflow.steps:
            output_var = step.get("output_var") or step["id"]
            step_id = step["id"]

            if step.get("connector_type") == "ai_analyze":
                continue

            workflow_tools_schema.append(_build_step_tool_schema(step))

            async def make_executor(s: Dict[str, Any] = step, ov: str = output_var, sid: str = step_id):
                async def executor(tool_inputs: Dict[str, Any]) -> str:
                    _update_step_result(run, sid, _db, status="running", started_at=datetime.now(timezone.utc).isoformat())
                    await emit({"type": "step_update", "step_id": sid, "status": "running"})
                    try:
                        resolved_config = interpolate_config(s.get("config", {}), context)
                        connector = get_connector(s["connector_type"])
                        result = await connector.execute(resolved_config, tool_inputs)
                        context["steps"][ov] = result.get("data") or result
                        _update_step_result(
                            run, sid, _db,
                            status="passed",
                            output=result,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                        )
                        await emit({"type": "step_update", "step_id": sid, "status": "passed"})
                        return json.dumps(result)
                    except Exception as e:
                        error_msg = str(e)
                        _update_step_result(run, sid, _db, status="failed", error=error_msg, completed_at=datetime.now(timezone.utc).isoformat())
                        await emit({"type": "step_update", "step_id": sid, "status": "failed", "error": error_msg})
                        if s.get("on_failure", "stop") == "stop":
                            raise
                        return json.dumps({"error": error_msg})
                return executor

            workflow_tool_executors[output_var] = await make_executor()

        system_prompt_addendum = (
            f"\n\nYou are executing workflow: {workflow.name}\n"
            f"Description: {workflow.description}\n"
            f"Trigger input: {json.dumps(trigger_input)}\n"
            f"Execute all workflow steps in order using the provided tools, then summarise your findings."
        )

        summary = ""
        try:
            async for event in ai_service.run_global_agentic_loop(
                query=system_prompt_addendum,
                workflow_tools_schema=workflow_tools_schema,
                workflow_tool_executors=workflow_tool_executors,
            ):
                await emit(event)
                if event.get("type") == "result":
                    summary = event.get("message", "")

            run.status = "completed"
            run.ai_summary = summary
            run.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            run.status = "failed"
            run.ai_summary = f"Execution failed: {e}"
            run.completed_at = datetime.now(timezone.utc)
            await emit({"type": "result", "message": run.ai_summary})

        try:
            _db.add(run)
            _db.commit()
        except Exception as db_err:
            import logging as _log
            _log.getLogger(__name__).error("run_workflow_background: DB commit failed: %s", db_err)
        finally:
            await emit({"type": "completed", "run_id": run_id, "status": run.status})


async def trigger_alert_workflow(
    workflow_id: int,
    alert_data: Dict[str, Any],
    incident_id: int,
    jira_url: Optional[str],
) -> int:
    """Create and kick off a WorkflowRun triggered by an alert. Returns run_id.

    Opens its own AsyncSession for create_run so the caller (alert_handler_service,
    which manages a sync Session) does not need to provide one.
    """
    from app.core.db import AsyncSessionLocal
    trigger_input = {
        "alert": alert_data,
        "incident_id": incident_id,
        "jira_url": jira_url,
    }
    async with AsyncSessionLocal() as db:
        run = await create_run(workflow_id, trigger_input, triggered_by="alert", db=db)
    asyncio.create_task(run_workflow_background(run.id, workflow_id, trigger_input))
    return run.id
