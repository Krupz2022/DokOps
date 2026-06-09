from typing import Any, Dict
from .base import ConnectorBase


class K8sConnector(ConnectorBase):
    """K8s connector — wraps existing k8s_service. config: action, namespace, pod_name."""

    @property
    def actions(self) -> list[str]:
        return ["get_pod_logs", "get_events", "get_pod_status"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.k8s_service import k8s_service

        action = config.get("action", "get_pod_logs")
        namespace = config.get("namespace", "default")
        pod_name = config.get("pod_name", "")

        try:
            if action == "get_pod_logs":
                if not pod_name:
                    return {"success": False, "error": "pod_name is required", "data": None}
                logs = await k8s_service.get_pod_logs(namespace, pod_name)
                return {"success": True, "data": {"logs": logs}, "error": None}

            elif action == "get_events":
                if not pod_name:
                    return {"success": False, "error": "pod_name is required for get_events", "data": None}
                events = await k8s_service.get_pod_events(namespace, pod_name)
                return {"success": True, "data": {"events": events}, "error": None}

            elif action == "get_pod_status":
                pods = await k8s_service.list_pods(namespace)
                if pod_name:
                    pods = [p for p in (pods or []) if p.get("name", "") == pod_name or pod_name in p.get("name", "")]
                return {"success": True, "data": {"pods": pods}, "error": None}

            return {"success": False, "error": f"Unknown action: {action}", "data": None}
        except Exception as e:
            return {"success": False, "error": str(e), "data": None}
