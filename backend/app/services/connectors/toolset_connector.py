from typing import Any, Dict
from .base import ConnectorBase


class ToolsetConnector(ConnectorBase):
    """Executes any registered toolset tool directly — no AI, no rewriting.

    config keys:
      tool_name  (required) — e.g. "mssql_execute", "mssql_query", "redis_info"
      params     (optional) — dict of tool parameter overrides; supports {{input.x}} / {{steps.x.y}}
                              interpolated by the workflow engine before reaching here

    All config values are already interpolated by interpolate_config() in the workflow service,
    so {{input.query}} etc. arrive here as their resolved strings.
    """

    @property
    def actions(self) -> list[str]:
        return ["execute"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        from app.tools.registry import execute_tool_async

        tool_name = config.get("tool_name", "").strip()
        if not tool_name:
            return {"success": False, "error": "tool_name is required in step config", "data": None}

        # Merge config params (hardcoded/interpolated from workflow definition) with
        # any runtime tool_inputs passed by the workflow engine. Config params win.
        params: Dict[str, Any] = {}
        params.update(tool_inputs or {})
        params.update(config.get("params", {}))

        # confirmed=True: the workflow definition itself is the approval.
        # Workflow admins who create/enable the workflow have pre-authorised its steps.
        result = await execute_tool_async(tool_name, params, confirmed=True)
        return result
