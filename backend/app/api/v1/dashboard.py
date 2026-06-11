import asyncio
from typing import Any, Dict
from fastapi import APIRouter, Depends
from app.api import deps
from app.services.k8s_service import k8s_service
from app.models.user import User

router = APIRouter()

from fastapi import APIRouter, Depends, Header
from typing import Optional, Any, Dict

@router.get("/stats")
async def get_dashboard_stats(
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Any:
    """
    Get cluster dashboard statistics.
    """
    try:
        namespaces, nodes = await asyncio.gather(
            k8s_service.list_namespaces(context=cluster_context),
            k8s_service.get_nodes(context=cluster_context),
        )
        return {
            "namespaces_count": len(namespaces),
            "nodes_count": len(nodes),
            "nodes": nodes,
            "status": "Healthy" if nodes else "Unknown"
        }
    except Exception as e:
        return {"error": str(e), "status": "Error"}

@router.get("/metrics")
async def get_dashboard_metrics(
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, Any]:
    """
    Get cluster node metrics (CPU/RAM).
    """
    try:
        return await k8s_service.get_node_metrics(context=cluster_context)
    except Exception as e:
        return {"available": False, "error": "Cluster unreachable"}
