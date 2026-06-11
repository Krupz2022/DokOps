import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from app.models.workflow import Workflow, WorkflowRun
from app.core.god_mode import is_god_mode_active

# Per-run approval primitives: run_id → (asyncio.Event, decision str)
_approval_events: Dict[int, asyncio.Event] = {}
_approval_decisions: Dict[int, str] = {}  # "approve" | "skip"


def resolve_approval(run_id: int, decision: str) -> None:
    """Called by the API to approve or skip a paused run. decision: 'approve' | 'skip'."""
    _approval_decisions[run_id] = decision
    event = _approval_events.get(run_id)
    if event:
        event.set()


def _build_agent_tool_catalog() -> List[Dict[str, Any]]:
    """Build the agent tool catalog dynamically from the live tool registries."""
    from app.tools.registry import TOOL_REGISTRY
    from app.services.integration_manager import IntegrationManager

    merged: Dict[str, Any] = {}
    merged.update(TOOL_REGISTRY)
    merged.update(IntegrationManager().get_active_tool_registry())

    return [
        {
            "name": name,
            "description": info.get("description", ""),
            "is_destructive": bool(info.get("requires_confirmation", False)),
        }
        for name, info in merged.items()
        if info.get("description")
    ]


def _get_catalog_map() -> Dict[str, Any]:
    return {t["name"]: t for t in _build_agent_tool_catalog()}


_catalog_cache: Optional[List[Dict[str, Any]]] = None


def __getattr__(name: str) -> Any:
    global _catalog_cache
    if name == "AGENT_TOOL_CATALOG":
        if _catalog_cache is None:
            _catalog_cache = _build_agent_tool_catalog()
        return _catalog_cache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def _ask_ai_for_tools(goal: str) -> List[Dict[str, Any]]:
    """Ask the AI which tools from the live catalog are needed for this goal."""
    from app.services.ai_service import ai_service
    from app.core.token_context import set_token_context
    set_token_context(user_id=None, source="agent")

    catalog = _build_agent_tool_catalog()
    catalog_map = {t["name"]: t for t in catalog}

    catalog_summary = "\n".join(
        f"- {t['name']}: {t['description']} {'[DESTRUCTIVE]' if t['is_destructive'] else ''}"
        for t in catalog
    )
    prompt = (
        f"You are helping configure a DokOps autonomous agent.\n"
        f"User goal: {goal}\n\n"
        f"Available tools:\n{catalog_summary}\n\n"
        f"Return a JSON array of tool names (strings only) that this goal will need. "
        f"Include only tools from the list above. No explanation, only JSON."
    )
    raw = await asyncio.to_thread(ai_service.simple_completion, prompt)
    try:
        names = json.loads(raw)
        if not isinstance(names, list):
            raise ValueError("expected list")
    except Exception:
        import re
        names = re.findall(r'"([a-z][a-z0-9_]{2,40})"', raw)

    result = []
    for name in names:
        if name in catalog_map:
            entry = catalog_map[name]
            result.append({
                "name": name,
                "description": entry["description"],
                "is_destructive": entry["is_destructive"],
                "pre_approved": False,
            })
    return result


async def discover_tools_for_goal(goal: str) -> List[Dict[str, Any]]:
    """Public API — callers should use this, not _ask_ai_for_tools directly."""
    return await _ask_ai_for_tools(goal)


def _build_notification_message(
    run: "WorkflowRun",
    wf: "Workflow",
    summary: str,
    cluster_names: List[str],
    fmt: str = "slack",
) -> str:
    """Build a rich, personalised notification message for Slack or Teams."""
    status = run.status
    status_emoji = {"completed": "✅", "failed": "❌"}.get(status, "⚠️")
    status_label = status.capitalize()

    trigger_emoji = {"cron": "⏰", "manual": "▶️", "webhook": "🔗", "alert": "🚨"}.get(run.triggered_by, "▶️")
    trigger_label = run.triggered_by.capitalize()

    def _utc(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    duration = ""
    if run.started_at and run.completed_at:
        secs = int((_utc(run.completed_at) - _utc(run.started_at)).total_seconds())
        duration = f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"

    cluster_str = ", ".join(cluster_names) if cluster_names else "default"
    creator = wf.created_by or "team"
    ts = run.completed_at.strftime("%Y-%m-%d %H:%M UTC") if run.completed_at else ""

    if fmt == "slack":
        lines = [
            f"Hi *{creator}* 👋",
            "",
            f"{status_emoji} *Agent Run Report — {wf.name}*",
            "",
            f"*Status:* {status_label}",
            f"*Trigger:* {trigger_emoji} {trigger_label}",
            f"*Cluster(s):* {cluster_str}",
        ]
        if duration:
            lines.append(f"*Duration:* {duration}")
        if ts:
            lines.append(f"*Completed:* {ts}")
        lines += ["", "*📋 Summary:*", summary[:2000]]
    else:
        lines = [
            f"Hi **{creator}** 👋",
            "",
            f"{status_emoji} **Agent Run Report — {wf.name}**",
            "",
            f"**Status:** {status_label}  ",
            f"**Trigger:** {trigger_emoji} {trigger_label}  ",
            f"**Cluster(s):** {cluster_str}  ",
        ]
        if duration:
            lines.append(f"**Duration:** {duration}  ")
        if ts:
            lines.append(f"**Completed:** {ts}  ")
        lines += ["", "**📋 Summary:**", summary[:2000]]

    return "\n".join(lines)


async def _post_final_report(
    summary: str,
    approved_tools: List[Dict[str, Any]],
    db: Session,
    notifications: Optional[Dict[str, Any]] = None,
    agent_name: str = "Agent",
    run: Optional["WorkflowRun"] = None,
    wf: Optional["Workflow"] = None,
) -> None:
    """Send run summary via all configured notification channels."""
    import logging as _log
    _logger = _log.getLogger(__name__)

    notif = notifications or {}
    if not any(v.get("enabled") for v in notif.values() if isinstance(v, dict)):
        return

    # Resolve cluster names for the rich agent message
    cluster_names: List[str] = []
    if wf and wf.agent_cluster_ids:
        from app.models.cluster import ClusterConnection
        for uid in wf.agent_cluster_ids:
            conn = db.get(ClusterConnection, uid)
            if conn:
                cluster_names.append(conn.name)

    # Build channel-specific messages (rich for Slack/Teams, plain for Jira description)
    slack_msg = (
        _build_notification_message(run, wf, summary, cluster_names, fmt="slack")
        if run and wf
        else f"*[{agent_name}] Run complete*\n{summary[:2000]}"
    )
    teams_msg = (
        _build_notification_message(run, wf, summary, cluster_names, fmt="teams")
        if run and wf
        else f"**[{agent_name}] Run complete**\n\n{summary[:2000]}"
    )

    from app.services.notification_service import send_notifications

    slack_only = {k: v for k, v in notif.items() if k == "slack"}
    teams_only = {k: v for k, v in notif.items() if k == "teams"}
    jira_only  = {k: v for k, v in notif.items() if k == "jira"}

    status_label   = run.status.capitalize() if run else "Completed"
    trigger_label  = run.triggered_by.capitalize() if run else "Manual"
    cluster_str    = ", ".join(cluster_names) if cluster_names else "default"
    creator        = wf.created_by if wf else agent_name
    jira_description = (
        f"Hi {creator},\n\nAgent *{agent_name}* finished a run.\n\n"
        f"*Status:* {status_label}\n*Trigger:* {trigger_label}\n"
        f"*Cluster(s):* {cluster_str}\n\n*Summary:*\n{summary[:4000]}"
    )
    jira_title = f"[{agent_name}] {status_label} run — {trigger_label}"

    try:
        await send_notifications(slack_only, slack_msg)
    except Exception as e:
        _logger.warning("Agent Slack notification failed: %s", e)
    try:
        await send_notifications(teams_only, teams_msg)
    except Exception as e:
        _logger.warning("Agent Teams notification failed: %s", e)
    try:
        await send_notifications(jira_only, jira_description, jira_title=jira_title)
    except Exception as e:
        _logger.warning("Agent Jira notification failed: %s", e)


def _build_agent_system_prompt(wf: Workflow) -> str:
    tool_names = [t["name"] for t in wf.agent_approved_tools]
    return (
        f"You are an autonomous DokOps agent. Your goal: {wf.agent_goal}\n\n"
        f"You have access to these tools: {', '.join(tool_names)}\n"
        f"Work step by step. When the goal is achieved, output a clear final summary.\n"
        f"Max iterations: {wf.agent_max_retries}."
    )


def _append_step(run: WorkflowRun, entry: Dict[str, Any], db: Session) -> None:
    db.refresh(run)
    results = list(run.step_results)
    results.append({**entry, "timestamp": datetime.now(timezone.utc).isoformat()})
    run.step_results = results
    db.add(run)
    db.commit()


async def _pause_for_approval(
    run: WorkflowRun,
    tool_name: str,
    wf: Workflow,
    db: Session,
) -> str:
    """Pause the run until approve/skip is called or timeout. Returns 'approve' or 'skip'."""
    event = asyncio.Event()
    _approval_events[run.id] = event
    _approval_decisions[run.id] = "skip"  # default on timeout

    run.status = "awaiting_approval"
    db.add(run)
    db.commit()

    try:
        await asyncio.wait_for(event.wait(), timeout=wf.agent_approval_timeout_seconds)
    except asyncio.TimeoutError:
        pass

    decision = _approval_decisions.pop(run.id, "skip")
    _approval_events.pop(run.id, None)

    run.status = "running"
    db.add(run)
    db.commit()

    return decision


async def _run_loop_for_cluster(
    run: WorkflowRun,
    wf: Workflow,
    cluster_name: Optional[str],
    db: Session,
) -> str:
    """Run the full ReAct loop for one cluster. Returns AI summary string."""
    from app.services.ai_service import ai_service
    from app.services import workflow_service as wf_svc
    from app.services.k8s_service import active_cluster_ctx
    from app.core.token_context import set_token_context
    set_token_context(user_id=getattr(wf, "user_id", None), source="agent")

    queue = wf_svc._run_queues.get(run.id)

    async def emit(event: Dict[str, Any]) -> None:
        if queue:
            await queue.put(event)

    # Pin all K8s tool calls in this run to the target cluster.
    ctx_token = active_cluster_ctx.set(cluster_name) if cluster_name else None

    system_query = _build_agent_system_prompt(wf)
    if cluster_name is not None:
        system_query += f"\n\nTarget cluster: {cluster_name}"

    summary = f"Agent loop did not produce a result for cluster {cluster_name}."
    approved_names = {t["name"] for t in wf.agent_approved_tools}
    catalog_map = _get_catalog_map()

    try:
        async for event in ai_service.run_global_agentic_loop(query=system_query):
            tool_name = event.get("tool_name")

            # Block tools not in the approved list
            if tool_name and tool_name not in approved_names:
                _append_step(run, {
                    "type": "tool_blocked",
                    "tool": tool_name,
                    "message": f"Tool '{tool_name}' is not in the approved list — skipped.",
                }, db)
                await emit({"type": "step", "message": f"⛔ Tool '{tool_name}' blocked (not approved)"})
                continue

            # Handle destructive tools that need approval
            if tool_name:
                catalog_entry = catalog_map.get(tool_name, {})
                is_destructive = catalog_entry.get("is_destructive", False)
                approved_tool = next((t for t in wf.agent_approved_tools if t["name"] == tool_name), None)
                pre_approved = approved_tool.get("pre_approved", False) if approved_tool else False

                _user_id = getattr(run, "triggered_by_user_id", None) or 0
                if is_destructive and not pre_approved and not is_god_mode_active(_user_id):
                    decision = await _pause_for_approval(run, tool_name, wf, db)
                    await emit({
                        "type": "awaiting_approval",
                        "tool": tool_name,
                        "run_id": run.id,
                        "message": f"⏸ Awaiting approval to run '{tool_name}'",
                    })
                    if decision == "skip":
                        _append_step(run, {
                            "type": "approval_skipped",
                            "tool": tool_name,
                            "message": f"User skipped '{tool_name}'.",
                        }, db)
                        await emit({"type": "step", "message": f"⏭ '{tool_name}' skipped by user"})
                        continue

            _append_step(run, event, db)
            await emit(event)

            if event.get("type") == "result":
                summary = event.get("message", summary)
    finally:
        if ctx_token is not None:
            active_cluster_ctx.reset(ctx_token)

    return summary


async def run_agent_background(
    run_id: int,
    workflow_id: int,
    db: Optional[Session] = None,
) -> None:
    """Main entry point: execute the agent goal across all selected clusters.

    When ``db`` is provided it is used directly (unit-test path); otherwise a
    new session is opened via the module-level engine.
    """
    from contextlib import contextmanager
    from app.services import workflow_service as wf_svc
    from app.core.db import engine

    @contextmanager
    def _session():
        if db is not None:
            yield db
        else:
            with Session(engine) as s:
                yield s

    with _session() as db:
        run = db.get(WorkflowRun, run_id)
        wf = db.get(Workflow, workflow_id)
        if not run or not wf:
            return

        queue = wf_svc._run_queues.get(run_id)

        async def emit(event: Dict[str, Any]) -> None:
            if queue:
                await queue.put(event)

        run.status = "running"
        db.add(run)
        db.commit()

        summaries: List[str] = []
        cluster_uuid_list: List[Optional[str]] = wf.agent_cluster_ids if wf.agent_cluster_ids else [None]

        async def _run_all() -> None:
            from app.models.cluster import ClusterConnection
            for cluster_uuid in cluster_uuid_list:
                cluster_name: Optional[str] = None
                if cluster_uuid is not None:
                    conn = db.get(ClusterConnection, cluster_uuid)
                    cluster_name = conn.name if conn else None
                    await emit({"type": "step", "message": f"🔄 Starting loop for cluster {cluster_name or cluster_uuid}"})
                summary = await _run_loop_for_cluster(run, wf, cluster_name, db)
                summaries.append(summary)

        try:
            # asyncio.wait_for used for Python 3.10 compatibility (asyncio.timeout requires 3.11+)
            await asyncio.wait_for(_run_all(), timeout=wf.agent_timeout_seconds)

            full_summary = "\n\n".join(summaries)
            run.status = "completed"
            run.ai_summary = full_summary
            run.completed_at = datetime.now(timezone.utc)
            approved_tools = list(wf.agent_approved_tools or [])
            notif = wf.agent_notifications or {}
            await _post_final_report(full_summary, approved_tools, db, notifications=notif, agent_name=wf.name, run=run, wf=wf)

        except asyncio.TimeoutError:
            partial = "\n\n".join(summaries) if summaries else "Agent timed out before producing results."
            run.status = "failed"
            run.ai_summary = f"[TIMED OUT after {wf.agent_timeout_seconds}s]\n\n{partial}"
            run.completed_at = datetime.now(timezone.utc)
            approved_tools = list(wf.agent_approved_tools or [])
            notif = wf.agent_notifications or {}
            await _post_final_report(run.ai_summary, approved_tools, db, notifications=notif, agent_name=wf.name, run=run, wf=wf)

        except Exception as e:
            run.status = "failed"
            run.ai_summary = f"Agent error: {e}"
            run.completed_at = datetime.now(timezone.utc)
            approved_tools = list(wf.agent_approved_tools or [])
            notif = wf.agent_notifications or {}
            await _post_final_report(run.ai_summary, approved_tools, db, notifications=notif, agent_name=wf.name, run=run, wf=wf)

        try:
            db.add(run)
            db.commit()
        except Exception as db_err:
            import logging as _log
            _log.getLogger(__name__).error("run_agent_background: DB commit failed: %s", db_err)
        finally:
            await emit({"type": "completed", "run_id": run_id, "status": run.status})
