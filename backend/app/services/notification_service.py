"""notification_service.py — shared notification dispatcher and patch summary builder."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

# Connector imports at module level so patch() can target them by name.
# Circular-import risk is low; connectors only import from .base.
from app.services.ai_service import ai_service
from app.services.connectors.slack_connector import SlackConnector
from app.services.connectors.teams_connector import TeamsConnector
from app.services.connectors.jira_connector import JiraConnector

_log = logging.getLogger(__name__)


async def send_notifications(
    config: Dict[str, Any],
    message: str,
    jira_title: Optional[str] = None,
) -> None:
    """Dispatch *message* to all enabled channels in *config*. Never raises."""
    if not config:
        return
    if not any(v.get("enabled") for v in config.values() if isinstance(v, dict)):
        return

    # ── Slack ─────────────────────────────────────────────────────────────────
    slack_cfg = config.get("slack", {})
    if slack_cfg.get("enabled") and slack_cfg.get("webhook_url"):
        try:
            await SlackConnector().execute(
                {"webhook_url": slack_cfg["webhook_url"], "message": message}, {}
            )
        except Exception as exc:
            _log.warning("Slack notification failed: %s", exc)

    # ── Teams ─────────────────────────────────────────────────────────────────
    teams_cfg = config.get("teams", {})
    if teams_cfg.get("enabled") and teams_cfg.get("webhook_url"):
        try:
            await TeamsConnector().execute(
                {"webhook_url": teams_cfg["webhook_url"], "message": message}, {}
            )
        except Exception as exc:
            _log.warning("Teams notification failed: %s", exc)

    # ── Jira ──────────────────────────────────────────────────────────────────
    jira_cfg = config.get("jira", {})
    if jira_cfg.get("enabled") and jira_cfg.get("base_url") and jira_cfg.get("project_key"):
        try:
            lines = message.splitlines()
            title = jira_title or (lines[0][:120] if lines else "Notification")
            payload = {
                "action": "create_issue",
                "base_url": jira_cfg["base_url"],
                "project_key": jira_cfg["project_key"],
                "issue_type": jira_cfg.get("issue_type", "Task"),
                "email": jira_cfg.get("email", ""),
                "api_token": jira_cfg.get("api_token", ""),
                "instance_type": jira_cfg.get("instance_type", "cloud"),
                "summary": title,
                "description": message[:4000],
            }
            await JiraConnector().execute(payload, {})
        except Exception as exc:
            _log.warning("Jira notification failed: %s", exc)


def build_patch_summary(
    promo: "PatchPromotion",
    results: List["PatchPromotionResult"],
    minion_hostnames: Dict[str, str],
    pipeline_name: str,
    stage_name: str,
    auto_reboot: bool,
) -> str:
    """Build a structured markdown summary of a completed patch promotion."""
    import json as _json

    ts = promo.completed_at.strftime("%Y-%m-%d %H:%M UTC") if promo.completed_at else "—"
    reboot_ids: set = set(_json.loads(promo.reboot_minions or "[]"))

    lines = [
        f"**Patch Run Complete — {pipeline_name} / {stage_name}**",
        f"Run: {ts}   Scope: {promo.patch_scope}   Status: {promo.status.upper()}",
        "",
        f"{'Minion':<30} {'Patches':>7}  {'Status':<12}  Reboot",
        "-" * 64,
    ]

    total_patches = 0
    succeeded = 0
    failed = 0

    for r in results:
        hostname = minion_hostnames.get(r.minion_id, r.minion_id[:12])
        status_icon = "✓ done" if r.status == "done" else "✗ failed"
        if r.status == "done":
            succeeded += 1
        else:
            failed += 1
        total_patches += r.packages_count

        if r.minion_id in reboot_ids:
            reboot_col = "done" if auto_reboot else "required"
        else:
            reboot_col = "—"

        lines.append(f"{hostname:<30} {r.packages_count:>7}  {status_icon:<12}  {reboot_col}")

    lines += [
        "-" * 64,
        f"Total: {total_patches} patches across {len(results)} systems. "
        f"{succeeded} succeeded, {failed} failed.",
    ]
    return "\n".join(lines)


async def ai_beautify_message(raw: str) -> str:
    """Return an AI-polished version of *raw*. Falls back to *raw* on any error."""
    try:
        from app.core.token_context import set_token_context
        set_token_context(user_id=None, source="notification")
        prompt = (
            "You are an ops notification assistant. Rewrite the following patch run summary "
            "as a concise, friendly, human-readable ops report. Keep all the data. "
            "Use clear formatting. No fluff.\n\n"
            f"Raw summary:\n{raw}"
        )
        return await asyncio.to_thread(ai_service.simple_completion, prompt)
    except Exception as exc:
        _log.warning("AI beautify failed, falling back to raw: %s", exc)
        return raw
