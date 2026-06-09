# backend/app/services/integration_manager.py
import logging
from typing import Any, Dict

from sqlmodel import Session, select

logger = logging.getLogger(__name__)

from app.core.db import engine
from app.models.integration import IntegrationSettings
from app.services.integrations.base import build_auth_headers
from app.services.integrations.prometheus import PrometheusService
from app.services.integrations.loki import LokiService
from app.services.integrations.grafana import GrafanaService
from app.services.integrations.elasticsearch import ElasticsearchService
from app.services.integrations.datadog import DatadogService

_SERVICE_MAP = {
    "prometheus": PrometheusService,
    "loki": LokiService,
    "grafana": GrafanaService,
    "elasticsearch": ElasticsearchService,
    "datadog": DatadogService,
}


class IntegrationManager:

    def get_active_tool_registry(self) -> Dict[str, Any]:
        """Query DB for active integrations and return merged TOOL_REGISTRY-compatible dict."""
        merged: Dict[str, Any] = {}
        try:
            with Session(engine) as session:
                rows = session.exec(
                    select(IntegrationSettings).where(IntegrationSettings.is_active == True)  # noqa: E712
                ).all()
        except Exception as e:
            logger.error("integration_manager: DB query failed: %s", e)
            return merged

        logger.debug("integration_manager: found %d active integration(s)", len(rows))
        for row in rows:
            svc_cls = _SERVICE_MAP.get(row.backend)
            if not svc_cls:
                continue
            try:
                headers = build_auth_headers(row.auth_type, row.encrypted_credentials)
                svc = svc_cls()
                tools = svc.get_tool_registry(row.base_url, headers)
                logger.debug("integration_manager: loaded %d tool(s) from %s (url=%s)", len(tools), row.backend, row.base_url)
                merged.update(tools)
            except Exception as e:
                logger.error("integration_manager: FAILED to load tools for %s (id=%s): %s", row.backend, row.id, e)
                continue

        logger.debug("integration_manager: registry total=%d tools=%s", len(merged), list(merged.keys()))
        return merged

    def get_tools_description_for_prompt(self, registry: Dict[str, Any] | None = None) -> str:
        """Return a prompt section listing available observability tools."""
        if registry is None:
            registry = self.get_active_tool_registry()
        if not registry:
            return ""
        lines = ["OBSERVABILITY TOOLS (call these to query metrics, logs, and traces):"]
        for name, info in registry.items():
            inputs = ", ".join(info.get("inputs", []))
            lines.append(f"- {name}({inputs}): {info['description']} - EXECUTES IMMEDIATELY (READ)")
        return "\n".join(lines)


integration_manager = IntegrationManager()
