import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.services.integrations.base import BaseIntegrationService


class LokiService(BaseIntegrationService):

    async def test_connection(self, base_url: str, headers: Dict[str, str]) -> Tuple[bool, str]:
        url = base_url.rstrip("/") + "/ready"
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

        async def loki_query_logs(
            log_query: str,
            start: Optional[str] = None,
            end: Optional[str] = None,
            limit: int = 100,
        ) -> Dict[str, Any]:
            """Query Loki for log entries using LogQL."""
            try:
                now = int(time.time())
                params = {
                    "query": log_query,
                    "start": start or str((now - 3600) * 1_000_000_000),
                    "end": end or str(now * 1_000_000_000),
                    "limit": str(limit),
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(
                        f"{url}/loki/api/v1/query_range",
                        headers=headers,
                        params=params,
                    )
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
                body = resp.json()
                parsed: List[Dict] = []
                for stream_result in body.get("data", {}).get("result", []):
                    labels = stream_result.get("stream", {})
                    for ts, line in stream_result.get("values", []):
                        parsed.append({"timestamp": ts, "log": line, "labels": labels})
                parsed.sort(key=lambda x: x["timestamp"])
                return {"success": True, "data": parsed, "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        async def loki_list_labels() -> Dict[str, Any]:
            """List all label names available in Loki. Call this first to discover valid label keys before querying."""
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(f"{url}/loki/api/v1/labels", headers=headers)
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
                labels = resp.json().get("data", [])
                return {"success": True, "data": labels, "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        async def loki_list_label_values(label: str) -> Dict[str, Any]:
            """List all values for a Loki label (e.g. label='namespace' returns all namespace names)."""
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(f"{url}/loki/api/v1/label/{label}/values", headers=headers)
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
                values = resp.json().get("data", [])
                return {"success": True, "data": values, "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        return {
            "loki_list_labels": {
                "function": loki_list_labels,
                "description": (
                    "List all label keys available in Loki (e.g. 'namespace', 'pod', 'app', 'container'). "
                    "Call this FIRST before querying logs to discover valid label names for the stream selector."
                ),
                "inputs": [],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "loki_list_label_values": {
                "function": loki_list_label_values,
                "description": (
                    "List all values for a specific Loki label. "
                    "Use after loki_list_labels to find exact values. "
                    "label: the label key e.g. 'namespace', 'pod', 'app'."
                ),
                "inputs": ["label"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "loki_query_logs": {
                "function": loki_query_logs,
                "description": (
                    "Query Loki for logs using LogQL. "
                    "Use when the user asks about application logs, error patterns, or log-level filtering. "
                    "log_query: LogQL stream selector e.g. '{app=\"myapp\", level=\"error\"}'. "
                    "start/end: nanosecond Unix timestamps (default: last 1 hour). limit: max log lines (default 100)."
                ),
                "inputs": ["log_query", "start", "end", "limit"],
                "operation_type": "read",
                "requires_confirmation": False,
            }
        }
