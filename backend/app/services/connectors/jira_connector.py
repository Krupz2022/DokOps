import json
import aiohttp
from typing import Any, Dict
from .base import ConnectorBase


# ── Auth + body helpers ───────────────────────────────────────────────────────

def _build_auth(config: dict) -> tuple:
    """Returns (aiohttp.BasicAuth | None, extra_headers_dict).
    cloud/server_basic → BasicAuth; server_pat → Authorization: Bearer header."""
    instance_type = config.get("instance_type", "cloud")
    token = config.get("api_token", "")
    if instance_type == "server_pat":
        return None, {"Authorization": f"Bearer {token}"}
    if instance_type == "server_basic":
        return aiohttp.BasicAuth(config.get("username", ""), token), {}
    return aiohttp.BasicAuth(config.get("email", ""), token), {}  # cloud + fallback


def _build_text_body(text: str, instance_type: str) -> Any:
    """Cloud v3 requires ADF JSON; Server v2 takes a plain string."""
    if instance_type != "cloud":
        return text
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


class JiraConnector(ConnectorBase):
    """Jira connector. config: base_url (or url), email, api_token, project_key, action,
    issue_key (for add_comment), custom_fields (dict or JSON string)."""

    @property
    def actions(self) -> list[str]:
        return ["create_issue", "add_comment"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        base_url = (config.get("base_url") or config.get("url", "")).rstrip("/")
        project_key = config.get("project_key", "")
        action = config.get("action", "create_issue")
        instance_type = config.get("instance_type", "cloud")
        api_version = "3" if instance_type == "cloud" else "2"

        auth, extra_headers = _build_auth(config)
        headers = {"Accept": "application/json", "Content-Type": "application/json", **extra_headers}

        try:
            async with aiohttp.ClientSession() as session:
                if action == "create_issue":
                    summary = config.get("summary", tool_inputs.get("summary", "DokOps Alert"))
                    description = config.get("description", tool_inputs.get("description", ""))
                    issue_type = config.get("issue_type", "Bug")

                    payload: Dict[str, Any] = {
                        "fields": {
                            "project": {"key": project_key},
                            "summary": summary,
                            "description": _build_text_body(description, instance_type),
                            "issuetype": {"name": issue_type},
                        }
                    }

                    custom_fields = config.get("custom_fields", {})
                    if isinstance(custom_fields, str):
                        try:
                            custom_fields = json.loads(custom_fields)
                        except (json.JSONDecodeError, ValueError):
                            custom_fields = {}
                    if custom_fields and isinstance(custom_fields, dict):
                        payload["fields"].update(custom_fields)

                    url = f"{base_url}/rest/api/{api_version}/issue"
                    async with session.post(url, json=payload, auth=auth, headers=headers) as resp:
                        data = await resp.json()
                        return {
                            "success": resp.status == 201,
                            "data": {
                                "issue_key": data.get("key"),
                                "url": f"{base_url}/browse/{data.get('key')}",
                            },
                            "error": None if resp.status == 201 else str(data),
                        }

                elif action == "add_comment":
                    issue_key = config.get("issue_key", "")
                    comment = config.get("comment", tool_inputs.get("comment", ""))
                    payload = {"body": _build_text_body(comment, instance_type)}
                    url = f"{base_url}/rest/api/{api_version}/issue/{issue_key}/comment"
                    async with session.post(url, json=payload, auth=auth, headers=headers) as resp:
                        return {
                            "success": resp.status == 201,
                            "data": {"commented": True},
                            "error": None if resp.status == 201 else f"HTTP {resp.status}",
                        }

                return {"success": False, "error": f"Unknown action: {action}", "data": None}

        except Exception as e:
            return {"success": False, "error": str(e), "data": None}
