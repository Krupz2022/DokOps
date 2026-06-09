import time
from typing import Any, Dict, Optional, Tuple

import httpx

from app.services.integrations.base import BaseIntegrationService


class PrometheusService(BaseIntegrationService):

    async def test_connection(self, base_url: str, headers: Dict[str, str]) -> Tuple[bool, str]:
        url = base_url.rstrip("/") + "/api/v1/query"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers, params={"query": "up"})
            if resp.status_code == 200:
                return True, "Connected"
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    def get_tool_registry(self, base_url: str, headers: Dict[str, str]) -> Dict[str, Any]:
        url = base_url.rstrip("/")

        async def prometheus_instant_query(query: str, description: str = "") -> Dict[str, Any]:
            """Execute a PromQL instant query (single point in time)."""
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{url}/api/v1/query",
                        headers=headers,
                        data={"query": query},
                    )
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
                body = resp.json()
                if body.get("status") != "success":
                    return {"success": False, "data": None, "error": body.get("error", "Unknown error")}
                return {"success": True, "data": body["data"], "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        async def prometheus_range_query(
            query: str,
            description: str = "",
            start: Optional[str] = None,
            end: Optional[str] = None,
            step: str = "60s",
        ) -> Dict[str, Any]:
            """Execute a PromQL range query. start/end are Unix timestamps or RFC3339. Default: last 1 hour."""
            try:
                now = int(time.time())
                payload = {
                    "query": query,
                    "start": start or str(now - 3600),
                    "end": end or str(now),
                    "step": step,
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{url}/api/v1/query_range",
                        headers=headers,
                        data=payload,
                    )
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
                body = resp.json()
                if body.get("status") != "success":
                    return {"success": False, "data": None, "error": body.get("error", "Unknown error")}
                return {"success": True, "data": body["data"], "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        async def prometheus_list_alert_rules() -> Dict[str, Any]:
            """List all Prometheus alerting rules and their current state (firing/pending/inactive)."""
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(f"{url}/api/v1/rules", headers=headers, params={"type": "alert"})
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}"}
                body = resp.json()
                return {"success": True, "data": body.get("data"), "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        return {
            "prometheus_instant_query": {
                "function": prometheus_instant_query,
                "description": (
                    "Execute an instant PromQL query against Prometheus. "
                    "Use for current metric values (e.g. 'up', CPU usage, memory, error rates). "
                    "query: valid PromQL expression. description: short label for the step."
                ),
                "inputs": ["query", "description"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "prometheus_range_query": {
                "function": prometheus_range_query,
                "description": (
                    "Execute a PromQL range query against Prometheus to get metric values over time. "
                    "Use when the user asks about trends, spikes, or historical metric data. "
                    "query: PromQL expression. start/end: Unix timestamp or RFC3339 (default: last 1h). step: e.g. '60s', '5m'."
                ),
                "inputs": ["query", "description", "start", "end", "step"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "prometheus_list_alert_rules": {
                "function": prometheus_list_alert_rules,
                "description": (
                    "List all Prometheus alerting rules and their firing state. "
                    "Use when asked 'are there any alerts firing?' or 'what rules are configured?'"
                ),
                "inputs": [],
                "operation_type": "read",
                "requires_confirmation": False,
            },
        }
