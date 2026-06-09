import aiohttp
from typing import Any, Dict
from .base import ConnectorBase


class SlackConnector(ConnectorBase):
    """Slack connector. config: webhook_url, message."""

    @property
    def actions(self) -> list[str]:
        return ["post_message"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        message = config.get("message", tool_inputs.get("message", ""))
        webhook_url = config.get("webhook_url", "")

        if not message:
            return {"success": False, "error": "message is required", "data": None}
        if not webhook_url:
            return {"success": False, "error": "webhook_url is required", "data": None}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json={"text": message}) as resp:
                    return {
                        "success": resp.status == 200,
                        "data": {"posted": True},
                        "error": None if resp.status == 200 else f"HTTP {resp.status}",
                    }
        except Exception as e:
            return {"success": False, "error": str(e), "data": None}
