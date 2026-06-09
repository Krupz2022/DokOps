import aiohttp
from typing import Any, Dict
from .base import ConnectorBase


class ArgoCDConnector(ConnectorBase):
    """ArgoCD connector. config: url, token, app_name, action."""

    @property
    def actions(self) -> list[str]:
        return ["get_app_status", "get_sync_history", "trigger_sync"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        base_url = config.get("url", "").rstrip("/")
        token = config.get("token", "")
        app_name = config.get("app_name", "")
        action = config.get("action", "get_app_status")
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        try:
            async with aiohttp.ClientSession() as session:
                if action == "get_app_status":
                    url = f"{base_url}/api/v1/applications/{app_name}"
                    async with session.get(url, headers=headers, ssl=True) as resp:
                        data = await resp.json()
                        status = data.get("status", {})
                        return {
                            "success": True,
                            "data": {
                                "name": app_name,
                                "sync_status": status.get("sync", {}).get("status"),
                                "health_status": status.get("health", {}).get("status"),
                                "message": status.get("operationState", {}).get("message"),
                            },
                            "error": None,
                        }

                elif action == "get_sync_history":
                    url = f"{base_url}/api/v1/applications/{app_name}"
                    async with session.get(url, headers=headers, ssl=True) as resp:
                        data = await resp.json()
                        history = data.get("status", {}).get("history", [])
                        return {"success": resp.status < 400, "data": {"history": history[-10:]}, "error": None if resp.status < 400 else f"HTTP {resp.status}"}

                elif action == "trigger_sync":
                    url = f"{base_url}/api/v1/applications/{app_name}/sync"
                    async with session.post(url, headers=headers, ssl=True) as resp:
                        return {
                            "success": resp.status == 200,
                            "data": {"syncing": True},
                            "error": None if resp.status == 200 else f"HTTP {resp.status}",
                        }

                return {"success": False, "error": f"Unknown action: {action}", "data": None}
        except Exception as e:
            return {"success": False, "error": str(e), "data": None}
