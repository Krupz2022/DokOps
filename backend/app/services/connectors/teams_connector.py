import aiohttp
from typing import Any, Dict
from .base import ConnectorBase


class TeamsConnector(ConnectorBase):
    """Microsoft Teams connector. config: webhook_url, message, title, action (post_message|post_adaptive_card)."""

    @property
    def actions(self) -> list[str]:
        return ["post_message", "post_adaptive_card"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        webhook_url = config.get("webhook_url", "")
        message = config.get("message", tool_inputs.get("message", ""))
        title = config.get("title", "DokOps Notification")
        action = config.get("action", "post_message")

        if not webhook_url:
            return {"success": False, "error": "webhook_url is required", "data": None}
        if not message:
            return {"success": False, "error": "message is required", "data": None}

        if action == "post_adaptive_card":
            payload = {
                "type": "message",
                "attachments": [{
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": title},
                            {"type": "TextBlock", "text": message, "wrap": True},
                        ],
                    },
                }],
            }
        else:
            payload = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "themeColor": "0076D7",
                "summary": title,
                "sections": [{"activityTitle": title, "activityText": message}],
            }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as resp:
                    return {
                        "success": resp.status in (200, 202),
                        "data": {"posted": True},
                        "error": None if resp.status in (200, 202) else f"HTTP {resp.status}",
                    }
        except Exception as e:
            return {"success": False, "error": str(e), "data": None}
