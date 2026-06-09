import aiohttp
from typing import Any, Dict
from .base import ConnectorBase


class JenkinsConnector(ConnectorBase):
    """Jenkins connector. config: url (Jenkins base URL), username, api_token, job_path, action."""

    @property
    def actions(self) -> list[str]:
        return ["get_build_status", "get_build_log", "trigger_build"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        base_url = config.get("url", "").rstrip("/")
        username = config.get("username", "")
        api_token = config.get("api_token", "")
        job_path = config.get("job_path", "")
        action = config.get("action", "get_build_status")
        build_number = config.get("build_number", "lastBuild")

        auth = aiohttp.BasicAuth(username, api_token) if username and api_token else None

        try:
            async with aiohttp.ClientSession() as session:
                if action == "get_build_status":
                    url = f"{base_url}/{job_path}/{build_number}/api/json"
                    async with session.get(url, auth=auth) as resp:
                        data = await resp.json()
                        return {
                            "success": resp.status < 400,
                            "data": {
                                "number": data.get("number"),
                                "result": data.get("result"),
                                "duration": data.get("duration"),
                                "url": data.get("url"),
                                "building": data.get("building"),
                            },
                            "error": None if resp.status < 400 else f"HTTP {resp.status}",
                        }

                elif action == "get_build_log":
                    url = f"{base_url}/{job_path}/{build_number}/consoleText"
                    async with session.get(url, auth=auth) as resp:
                        text = await resp.text()
                        return {"success": resp.status < 400, "data": {"log": text[-4000:]}, "error": None if resp.status < 400 else f"HTTP {resp.status}"}

                elif action == "trigger_build":
                    url = f"{base_url}/{job_path}/build"
                    async with session.post(url, auth=auth) as resp:
                        return {
                            "success": resp.status in (200, 201),
                            "data": {"triggered": True},
                            "error": None if resp.status in (200, 201) else f"HTTP {resp.status}",
                        }

                return {"success": False, "error": f"Unknown action: {action}", "data": None}
        except Exception as e:
            return {"success": False, "error": str(e), "data": None}
