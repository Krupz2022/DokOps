from mcp.server.fastmcp import FastMCP
from mcp.types import Resource, Tool, TextContent
from app.services.k8s_service import k8s_service
from app.core.god_mode import is_mcp_god_mode_active
import logging

# Initialize MCP Server
mcp = FastMCP("k8s-mcp-server")
logger = logging.getLogger(__name__)


# --- MCP Tool Definitions ---

@mcp.tool()
async def list_namespaces() -> str:
    """List all Kubernetes namespaces."""
    namespaces = await k8s_service.list_namespaces()
    return f"Namespaces: {', '.join(namespaces)}"

@mcp.tool()
async def list_pods(namespace: str) -> str:
    """List pods in a specific namespace."""
    pods = await k8s_service.list_pods(namespace)
    return str(pods)

@mcp.tool()
async def get_pod_logs(namespace: str, pod_name: str) -> str:
    """Get logs for a specific pod."""
    return await k8s_service.get_pod_logs(namespace, pod_name)

@mcp.tool()
async def delete_pod(namespace: str, pod_name: str) -> str:
    """Delete a pod. REQUIRES GOD MODE."""
    if not is_mcp_god_mode_active():
        return "PERMISSION DENIED: God Mode is disabled. Cannot delete pod."
    try:
        return await k8s_service.delete_pod(namespace, pod_name, god_mode=True)
    except PermissionError:
        return "PERMISSION DENIED: God Mode is disabled. Cannot delete pod."

@mcp.tool()
async def scale_deployment(namespace: str, deployment_name: str, replicas: int) -> str:
    """Scale a deployment. REQUIRES GOD MODE."""
    if not is_mcp_god_mode_active():
        return "PERMISSION DENIED: God Mode is disabled. Cannot scale deployment."
    try:
        return await k8s_service.scale_deployment(namespace, deployment_name, replicas, god_mode=True)
    except PermissionError:
        return "PERMISSION DENIED: God Mode is disabled. Cannot scale deployment."

@mcp.tool()
async def get_status() -> str:
    """Check the current status and mode of the MCP server."""
    mode = "GOD" if is_mcp_god_mode_active() else "NORMAL"
    return f"MCP Server is running. Current Mode: {mode}"
