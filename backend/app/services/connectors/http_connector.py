import aiohttp
from typing import Any, Dict
from .base import ConnectorBase
from app.core.ssrf import validate_url as _validate_url


class HttpConnector(ConnectorBase):
    """Generic REST connector. config keys: url, method, headers (dict), body (dict|str)."""

    @property
    def actions(self) -> list[str]:
        return ["request"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        url = config.get("url", "")
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        body = config.get("body")

        if not url:
            return {"success": False, "error": "url is required", "data": None}

        try:
            _validate_url(url)
        except ValueError as e:
            return {"success": False, "error": f"Blocked URL (SSRF protection): {e}", "data": None}

        try:
            async with aiohttp.ClientSession() as session:
                kwargs: Dict[str, Any] = {"headers": headers}
                if body and method in ("POST", "PUT", "PATCH"):
                    if isinstance(body, dict):
                        kwargs["json"] = body
                    else:
                        kwargs["data"] = str(body)

                async with session.request(method, url, **kwargs) as resp:
                    try:
                        data = await resp.json()
                    except Exception:
                        data = await resp.text()
                    return {
                        "success": resp.status < 400,
                        "status_code": resp.status,
                        "data": data,
                        "error": None if resp.status < 400 else f"HTTP {resp.status}",
                    }
        except Exception as e:
            return {"success": False, "error": str(e), "data": None}
