# backend/app/services/alert_handler_service.py
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.alert_incident import AlertIncident
from app.models.audit import AuditLog
from app.models.setting import SystemSetting  # ensures table is registered in metadata
from app.services.alert_normalizers import NormalizedAlert
from app.core.dynamic_gate import DynamicGate
from app.core.settings_cache import get_setting

logger = logging.getLogger(__name__)

SUPPRESSION_WINDOW_MINUTES_DEFAULT = 5
MAX_CONCURRENT_RCA_DEFAULT = 5
MAX_CONCURRENT_RCA_KEY = "alert_max_concurrent_rca"


def _get_max_concurrent_rca() -> int:
    """Current RCA concurrency limit from SystemSetting; defaults/floors at sane values."""
    raw = get_setting(MAX_CONCURRENT_RCA_KEY)
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return MAX_CONCURRENT_RCA_DEFAULT
    return value if value > 0 else MAX_CONCURRENT_RCA_DEFAULT


# Module-level gate: bounds concurrent RCA pipelines across the whole process.
_rca_gate = DynamicGate(_get_max_concurrent_rca)


def build_jira_body(incident: AlertIncident) -> str:
    lines = [
        f"*Alert:* {incident.alert_name}",
        f"*Severity:* {incident.severity.upper()}",
        f"*Source:* {incident.source}",
        f"*Namespace/Pod:* {incident.namespace or 'N/A'} / {incident.pod_name or 'N/A'}",
        f"*Received:* {incident.created_at.isoformat()}",
        "",
        "---",
        "*Root Cause Analysis:*",
    ]
    if incident.rca_report:
        try:
            steps = json.loads(incident.rca_report)
            for step in steps:
                if step.get("type") == "result":
                    lines.append(step.get("message", "")[:600])
        except (json.JSONDecodeError, TypeError):
            lines.append(str(incident.rca_report)[:600])
    else:
        lines.append("RCA pending.")

    lines += ["", "---", "*Evidence Summary:*"]
    if incident.evidence:
        try:
            ev = json.loads(incident.evidence)
            if ev.get("logs"):
                lines.append(f"Logs (last 20 lines):\n{ev['logs'][-1000:]}")
            if ev.get("events"):
                lines.append(f"Events:\n{ev['events'][:500]}")
        except (json.JSONDecodeError, TypeError):
            pass

    return "\n".join(lines)


class AlertHandlerService:

    async def _get_suppression_minutes(self) -> int:
        async with AsyncSessionLocal() as db:
            row = await db.get(SystemSetting, "alert_suppression_minutes")
            try:
                return int(row.value) if row else SUPPRESSION_WINDOW_MINUTES_DEFAULT
            except (ValueError, TypeError):
                return SUPPRESSION_WINDOW_MINUTES_DEFAULT

    async def _is_duplicate(self, alert: NormalizedAlert) -> bool:
        suppression_minutes = await self._get_suppression_minutes()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=suppression_minutes)
        async with AsyncSessionLocal() as db:
            existing = (await db.exec(
                select(AlertIncident).where(
                    AlertIncident.fingerprint == alert.fingerprint,
                    AlertIncident.status != "closed",
                    AlertIncident.created_at >= cutoff,
                )
            )).first()
        return existing is not None

    async def _check_remediation_rate_limit(
        self, alert_name: str, action: str, max_per_hour: int
    ) -> bool:
        """Returns True if we are UNDER the rate limit (safe to remediate)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        async with AsyncSessionLocal() as db:
            count = len((await db.exec(
                select(AlertIncident).where(
                    AlertIncident.alert_name == alert_name,
                    AlertIncident.remediation_action == action,
                    AlertIncident.status == "remediated",
                    AlertIncident.created_at >= cutoff,
                )
            )).all())
        return count < max_per_hour

    async def _update_status(self, incident_id: int, status: str) -> None:
        async with AsyncSessionLocal() as db:
            incident = await db.get(AlertIncident, incident_id)
            if incident:
                incident.status = status
                db.add(incident)
                await db.commit()

    async def _collect_evidence(
        self, incident: AlertIncident
    ) -> Dict[str, Any]:
        from app.services.k8s_service import k8s_service
        evidence: Dict[str, Any] = {}
        if not incident.namespace or not incident.pod_name:
            return evidence
        try:
            evidence["logs"] = await k8s_service.get_pod_logs(
                incident.namespace, incident.pod_name, tail_lines=500
            )
        except Exception as e:
            evidence["logs_error"] = str(e)
        try:
            evidence["events"] = await k8s_service.get_pod_events(
                incident.namespace, incident.pod_name
            )
        except Exception as e:
            evidence["events_error"] = str(e)
        return evidence

    async def _run_rca(
        self, incident: AlertIncident, evidence: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        from app.services.ai_service import ai_service
        from app.core.token_context import set_token_context
        set_token_context(user_id=None, source="alert")
        query = f"{incident.alert_name}: {incident.status}"
        evidence_ctx = json.dumps(evidence)[:4000] if evidence else None
        steps = []
        try:
            if incident.namespace and incident.pod_name:
                gen = ai_service.run_agentic_loop(
                    incident.namespace, incident.pod_name, query, evidence_context=evidence_ctx
                )
            else:
                gen = ai_service.run_global_agentic_loop(query, evidence_context=evidence_ctx)
            async for step in gen:
                steps.append(step)
        except Exception as e:
            steps.append({"type": "error", "message": str(e)})
        return steps

    async def _create_jira_ticket(self, incident: AlertIncident) -> Optional[str]:
        """Returns jira ticket key if created, else None."""
        async with AsyncSessionLocal() as db:
            row = await db.get(SystemSetting, "alert_jira_config")
            if not row or not row.value:
                return None
            try:
                jira_config = json.loads(row.value)
            except json.JSONDecodeError:
                return None

        from app.services.connectors.jira_connector import JiraConnector

        summary = f"[{incident.severity.upper()}] {incident.alert_name} — {incident.namespace}/{incident.pod_name}"
        description = build_jira_body(incident)
        jira_config["action"] = "create_issue"
        jira_config["summary"] = summary
        jira_config["description"] = description

        connector = JiraConnector()
        ticket_key = None
        ticket_url = None
        try:
            result = await connector.execute(jira_config, {})
            if result.get("success") and result.get("data"):
                ticket_key = result["data"].get("issue_key")
                ticket_url = result["data"].get("url")
        except Exception as e:
            logger.warning(f"Jira ticket creation failed for incident {incident.id}: {e}")

        if ticket_key or ticket_url:
            async with AsyncSessionLocal() as db:
                fresh = await db.get(AlertIncident, incident.id)
                if fresh:
                    fresh.jira_ticket_key = ticket_key
                    fresh.jira_ticket_url = ticket_url
                    db.add(fresh)
                    await db.commit()
                    # propagate back to in-memory incident for downstream steps
                    incident.jira_ticket_key = ticket_key
                    incident.jira_ticket_url = ticket_url

        return ticket_key

    async def _notify(self, incident: AlertIncident) -> None:
        rca_summary = ""
        if incident.rca_report:
            try:
                steps = json.loads(incident.rca_report)
                for s in steps:
                    if s.get("type") == "result":
                        rca_summary = s.get("message", "")[:600]
                        break
            except (json.JSONDecodeError, TypeError):
                pass

        message = (
            f"🚨 *[{incident.severity.upper()}] {incident.alert_name}*\n"
            f"Namespace: `{incident.namespace or 'N/A'}` | Pod: `{incident.pod_name or 'N/A'}`\n"
            f"Source: {incident.source}\n"
        )
        if rca_summary:
            message += f"\n*AI RCA:*\n{rca_summary}\n"
        if incident.jira_ticket_url:
            message += f"\n*Jira:* {incident.jira_ticket_url}"

        # Read notification config in one short session
        slack_url = None
        teams_url = None
        async with AsyncSessionLocal() as db:
            row = await db.get(SystemSetting, "alert_slack_webhook")
            if row and row.value:
                slack_url = row.value
            row = await db.get(SystemSetting, "alert_teams_webhook")
            if row and row.value:
                teams_url = row.value

        # Slack
        if slack_url:
            from app.services.connectors.slack_connector import SlackConnector
            try:
                await SlackConnector().execute({"webhook_url": slack_url, "message": message}, {})
            except Exception as e:
                logger.warning(f"Slack notify failed: {e}")

        # Teams
        if teams_url:
            from app.services.connectors.teams_connector import TeamsConnector
            try:
                await TeamsConnector().execute({"webhook_url": teams_url, "message": message}, {})
            except Exception as e:
                logger.warning(f"Teams notify failed: {e}")

        async with AsyncSessionLocal() as db:
            fresh = await db.get(AlertIncident, incident.id)
            if fresh:
                fresh.notification_sent_at = datetime.now(timezone.utc)
                db.add(fresh)
                await db.commit()

    async def _trigger_workflows(self, incident: AlertIncident, alert: NormalizedAlert) -> None:
        from app.models.workflow import Workflow
        from app.services.workflow_service import trigger_alert_workflow

        async with AsyncSessionLocal() as db:
            rows = (await db.exec(select(Workflow).where(Workflow.trigger_type == "alert"))).all()

        for workflow in rows:
            if not workflow.trigger_config:
                continue
            try:
                config = json.loads(workflow.trigger_config)
            except json.JSONDecodeError:
                continue
            if config.get("alert_name") != alert.alert_name:
                continue
            try:
                run_id = await trigger_alert_workflow(
                    workflow_id=workflow.id,
                    alert_data=alert.model_dump(mode="json"),
                    incident_id=incident.id,
                    jira_url=incident.jira_ticket_url,
                )
                if incident.workflow_run_id is None:
                    incident.workflow_run_id = run_id
                    async with AsyncSessionLocal() as db:
                        fresh = await db.get(AlertIncident, incident.id)
                        if fresh:
                            fresh.workflow_run_id = run_id
                            db.add(fresh)
                            await db.commit()
            except Exception as e:
                logger.warning(f"Workflow trigger failed for workflow {workflow.id}: {e}")

    async def _maybe_remediate(self, incident: AlertIncident) -> None:
        from app.services.k8s_service import k8s_service

        # Read remediation policy
        policy = None
        async with AsyncSessionLocal() as db:
            row = await db.get(SystemSetting, "alert_remediation_policy")
            if row and row.value:
                try:
                    policy = json.loads(row.value)
                except json.JSONDecodeError:
                    pass

        if not policy:
            return

        rule = policy.get(incident.alert_name)
        if not rule:
            return

        action = rule.get("action")
        max_per_hour = rule.get("max_per_hour", 1)

        if not await self._check_remediation_rate_limit(incident.alert_name, action, max_per_hour):
            logger.warning(
                f"Remediation rate limit reached for {incident.alert_name} ({action}). Skipping."
            )
            return

        outcome = "skipped"
        if action == "restart_pod" and incident.namespace and incident.pod_name:
            outcome = await k8s_service.restart_pod(incident.namespace, incident.pod_name)

        async with AsyncSessionLocal() as db:
            fresh = await db.get(AlertIncident, incident.id)
            if fresh:
                fresh.remediation_action = action
                fresh.remediation_outcome = outcome
                fresh.status = "remediated"
                db.add(fresh)
                await db.commit()
                # propagate back
                incident.remediation_action = action
                incident.remediation_outcome = outcome
                incident.status = "remediated"

            db.add(AuditLog(
                actor="SYSTEM",
                action=f"auto_remediate:{action}",
                resource=f"{incident.namespace}/{incident.pod_name}",
                result="SUCCESS",
                mode="NORMAL",
                source="ALERT",
                details=f"incident_id={incident.id} alert={incident.alert_name} outcome={outcome}",
            ))
            await db.commit()

        await self._notify_remediation(incident)

    async def _notify_remediation(self, incident: AlertIncident) -> None:
        message = (
            f"✅ *Auto-remediated:* {incident.alert_name}\n"
            f"Action: `{incident.remediation_action}` on `{incident.namespace}/{incident.pod_name}`\n"
            f"Outcome: {incident.remediation_outcome}"
        )

        if incident.jira_ticket_url and incident.jira_ticket_key:
            jira_config_value = None
            async with AsyncSessionLocal() as db:
                row = await db.get(SystemSetting, "alert_jira_config")
                if row and row.value:
                    jira_config_value = row.value
            if jira_config_value:
                from app.services.connectors.jira_connector import JiraConnector
                try:
                    jira_config = json.loads(jira_config_value)
                    jira_config["action"] = "add_comment"
                    jira_config["issue_key"] = incident.jira_ticket_key
                    jira_config["comment"] = message
                    await JiraConnector().execute(jira_config, {})
                except Exception as e:
                    logger.warning(f"Jira remediation comment failed: {e}")

        slack_url = None
        async with AsyncSessionLocal() as db:
            row = await db.get(SystemSetting, "alert_slack_webhook")
            if row and row.value:
                slack_url = row.value
        if slack_url:
            from app.services.connectors.slack_connector import SlackConnector
            try:
                await SlackConnector().execute({"webhook_url": slack_url, "message": message}, {})
            except Exception as e:
                logger.warning(f"Slack remediation notify failed: {e}")

    async def _resolve_cluster(self, alert: NormalizedAlert) -> Optional[str]:
        """
        Determine which registered cluster this alert belongs to.

        Tier 1 — namespace scan: ask each cluster's k8s API whether it owns the
                  alert's namespace. Fast, free, no LLM needed.
        Tier 2 — AI fallback: send the full alert payload + cluster list to
                  simple_completion (uses fast model when available, main model
                  otherwise). Handles alerts with no namespace or ambiguous signals.
        """
        from app.models.cluster import ClusterConnection
        from app.services.k8s_service import k8s_service

        async with AsyncSessionLocal() as db:
            clusters = (await db.exec(select(ClusterConnection))).all()
        cluster_names = [c.name for c in clusters]

        if not cluster_names:
            return None
        if len(cluster_names) == 1:
            return cluster_names[0]

        # Tier 1: namespace scan
        if alert.namespace:
            for cluster_name in cluster_names:
                try:
                    core_api = k8s_service._get_api("CoreV1Api", context=cluster_name)
                    if core_api:
                        ns_list = await core_api.list_namespace(_request_timeout=3)
                        if any(ns.metadata.name == alert.namespace for ns in ns_list.items):
                            logger.info("Alert cluster resolved via namespace scan: %s", cluster_name)
                            return cluster_name
                except Exception:
                    continue

        # Tier 2: AI resolution (fast model if configured, main model otherwise)
        try:
            from app.services.ai_service import ai_service
            from app.core.token_context import set_token_context
            set_token_context(user_id=None, source="alert")

            payload_summary = json.dumps({
                "alert_name": alert.alert_name,
                "source": alert.source,
                "namespace": alert.namespace,
                "pod_name": alert.pod_name,
                "description": alert.description[:500],
                "labels": alert.labels,
            }, indent=2)

            prompt = (
                "You are a DevOps assistant. An alert arrived with this payload:\n\n"
                f"{payload_summary}\n\n"
                f"Registered Kubernetes clusters: {', '.join(cluster_names)}\n\n"
                "Which cluster does this alert most likely belong to? "
                "Reply with ONLY the exact cluster name from the list above, "
                "or 'unknown' if you cannot determine it."
            )

            result = await asyncio.to_thread(ai_service.simple_completion, prompt)
            result = result.strip().strip('"').strip("'").split("\n")[0].strip()
            if result in cluster_names:
                logger.info("Alert cluster resolved via AI: %s", result)
                return result
        except Exception as e:
            logger.warning("AI cluster resolution failed: %s", e)

        logger.warning(
            "Could not resolve cluster for alert '%s' — will use default context", alert.alert_name
        )
        return None

    async def handle(self, alert: NormalizedAlert) -> None:
        """Full pipeline for a freshly-received alert. Called as a FastAPI BackgroundTask."""
        logger.info(f"Alert received: {alert.source}/{alert.alert_name} fp={alert.fingerprint}")

        # Step 1: Deduplicate
        if await self._is_duplicate(alert):
            logger.info(f"Alert suppressed (duplicate within window): {alert.fingerprint}")
            return

        # Step 2: Resolve which cluster this alert belongs to
        from app.services.k8s_service import active_cluster_ctx
        cluster_name = await self._resolve_cluster(alert)
        ctx_token = active_cluster_ctx.set(cluster_name) if cluster_name else None
        logger.info("Alert cluster resolved: %s", cluster_name or "(default)")

        try:
            # Step 3: Persist incident as 'pending' BEFORE acquiring the gate, so a storm-queued
            # alert is durable and recoverable even if we crash while it waits for a slot.
            incident = AlertIncident(
                fingerprint=alert.fingerprint,
                source=alert.source,
                alert_name=alert.alert_name,
                severity=alert.severity,
                namespace=alert.namespace,
                pod_name=alert.pod_name,
                cluster_name=cluster_name,
                status="pending",
            )
            async with AsyncSessionLocal() as db:
                db.add(incident)
                await db.commit()
                await db.refresh(incident)

            await self._run_pipeline(incident, alert)
        finally:
            if ctx_token is not None:
                active_cluster_ctx.reset(ctx_token)

    async def _run_pipeline(
        self, incident: AlertIncident, alert: NormalizedAlert
    ) -> None:
        """Steps 4-8 against an already-persisted incident, bounded by the RCA gate.

        Shared by the fresh-alert path (handle) and the recovery path (handle_recovery).
        """
        async with _rca_gate:
            # Step 4: Collect evidence FIRST (long async I/O — no session held open)
            await self._update_status(incident.id, "collecting")
            evidence = {}
            try:
                evidence = await self._collect_evidence(incident)
            except Exception as e:
                logger.warning(f"Evidence collection error (continuing): {e}")

            async with AsyncSessionLocal() as db:
                fresh = await db.get(AlertIncident, incident.id)
                if fresh:
                    fresh.evidence = json.dumps(evidence)
                    db.add(fresh)
                    await db.commit()
                    incident.evidence = fresh.evidence

            # Step 5: AI RCA (long async — no session held open)
            await self._update_status(incident.id, "rca_running")
            rca_steps = []
            try:
                rca_steps = await self._run_rca(incident, evidence)
            except Exception as e:
                logger.warning(f"RCA error (continuing): {e}")
                rca_steps = [{"type": "error", "message": str(e)}]

            async with AsyncSessionLocal() as db:
                fresh = await db.get(AlertIncident, incident.id)
                if fresh:
                    fresh.rca_report = json.dumps(rca_steps)
                    db.add(fresh)
                    await db.commit()
                    incident.rca_report = fresh.rca_report

            # Step 6a: Create Jira ticket (skipped if one already exists — recovery-safe)
            try:
                await self._create_jira_ticket(incident)
            except Exception as e:
                logger.warning(f"Jira step error (continuing): {e}")

            # Step 6b: Notify channels (skipped if already notified — recovery-safe)
            try:
                await self._notify(incident)
            except Exception as e:
                logger.warning(f"Notify step error (continuing): {e}")
            if incident.status != "remediated":
                await self._update_status(incident.id, "notified")

            # Step 7: Trigger matching workflows
            try:
                await self._trigger_workflows(incident, alert)
            except Exception as e:
                logger.warning(f"Workflow trigger error (continuing): {e}")

            # Step 8: Check allowlist and maybe remediate
            try:
                await self._maybe_remediate(incident)
            except Exception as e:
                logger.warning(f"Remediation step error (continuing): {e}")


alert_handler_service = AlertHandlerService()
