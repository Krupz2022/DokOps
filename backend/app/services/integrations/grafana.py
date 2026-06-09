from typing import Any, Dict, Optional, Tuple

import httpx

from app.services.integrations.base import BaseIntegrationService


class GrafanaService(BaseIntegrationService):

    async def test_connection(self, base_url: str, headers: Dict[str, str]) -> Tuple[bool, str]:
        url = base_url.rstrip("/") + "/api/health"
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

        async def grafana_list_dashboards(search: Optional[str] = None) -> Dict[str, Any]:
            """List Grafana dashboards, optionally filtered by name."""
            try:
                params = {"type": "dash-db", "limit": "50"}
                if search:
                    params["query"] = search
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(f"{url}/api/search", headers=headers, params=params)
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
                dashboards = [
                    {"uid": d.get("uid"), "title": d.get("title"), "url": d.get("url")}
                    for d in resp.json()
                ]
                return {"success": True, "data": dashboards, "error": None}
            except Exception as e:
                return {"success": False, "data": None, "error": str(e)}

        return {
            "grafana_list_dashboards": {
                "function": grafana_list_dashboards,
                "description": (
                    "List Grafana dashboards. "
                    "Use when the user asks 'do we have a dashboard for X?' or 'find the K8s dashboard'. "
                    "search: optional keyword to filter by dashboard title."
                ),
                "inputs": ["search"],
                "operation_type": "read",
                "requires_confirmation": False,
            }
        }
