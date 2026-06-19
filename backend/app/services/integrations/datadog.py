import json
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from app.services.integrations.base import BaseIntegrationService


class DatadogService(BaseIntegrationService):

    async def test_connection(self, base_url: str, headers: Dict[str, str]) -> Tuple[bool, str]:
        url = base_url.rstrip("/") + "/api/v1/validate"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return True, "Connected"
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    def get_tool_registry(self, base_url: str, headers: Dict[str, str]) -> Dict[str, Any]:
        url = base_url.rstrip("/")

        async def datadog_query_metrics(
            query: str,
            from_ts: Optional[int] = None,
            to_ts: Optional[int] = None,
        ) -> Dict[str, Any]:
            """Query Datadog metrics API v1. Returns time series data."""
            try:
                now = int(time.time())
                params = {
                    "query": query,
                    "from": from_ts or (now - 3600),
                    "to": to_ts or now,
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(f"{url}/api/v1/query", headers=headers, params=params)
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
                return {"success": True, "data": resp.json(), "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        async def datadog_query_logs(
            query: str,
            from_ts: Optional[str] = None,
            to_ts: Optional[str] = None,
            limit: int = 50,
        ) -> Dict[str, Any]:
            """Search Datadog logs API v2."""
            try:
                from datetime import datetime, timezone, timedelta
                now = datetime.now(timezone.utc)
                # Datadog Logs API v2 requires ISO 8601 format
                default_from = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                default_to   = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
                body = {
                    "filter": {
                        "query": query,
                        "from": from_ts or default_from,
                        "to": to_ts or default_to,
                    },
                    "page": {"limit": limit},
                    "sort": "timestamp",
                }
                req_headers = {"Content-Type": "application/json", **headers}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{url}/api/v2/logs/events/search",
                        headers=req_headers,
                        content=json.dumps(body),
                    )
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
                events = resp.json().get("data", [])
                logs = [
                    {
                        "timestamp": e.get("attributes", {}).get("timestamp"),
                        "message": e.get("attributes", {}).get("message"),
                        "service": e.get("attributes", {}).get("service"),
                    }
                    for e in events
                ]
                return {"success": True, "data": logs, "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        return {
            "datadog_query_metrics": {
                "function": datadog_query_metrics,
                "description": (
                    "Query Datadog metrics. "
                    "query: Datadog metric query e.g. 'avg:kubernetes.cpu.usage.total{*} by {pod_name}'. "
                    "from_ts/to_ts: Unix timestamps (default: last 1 hour)."
                ),
                "inputs": ["query", "from_ts", "to_ts"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "datadog_query_logs": {
                "function": datadog_query_logs,
                "description": (
                    "Search Datadog logs. "
                    "query: Datadog log search syntax e.g. 'service:payments status:error'. "
                    "from_ts/to_ts: ISO 8601 timestamps as strings e.g. '2026-06-18T10:00:00+00:00' "
                    "(default: last 1 hour). limit: max results."
                ),
                "inputs": ["query", "from_ts", "to_ts", "limit"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
        }
