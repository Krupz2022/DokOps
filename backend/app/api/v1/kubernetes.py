from typing import Any, List, Dict, Optional, Set
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Header
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.api import deps
from app.api.deps import require_god_mode
from app.services.k8s_service import k8s_service
from app.models.user import User

router = APIRouter()


async def _get_registered_context_names(db: AsyncSession) -> Set[str]:
    """Return the set of context names for all registered cluster connections."""
    from app.models.cluster import ClusterConnection
    clusters = (await db.exec(select(ClusterConnection))).all()
    return {c.name for c in clusters if c.name}


async def _validate_cluster_context(context: Optional[str], db: AsyncSession) -> Optional[str]:
    """Raise 403 if context is set but not in the list of registered cluster contexts."""
    if context is None:
        return None
    allowed = await _get_registered_context_names(db)
    if allowed and context not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Cluster {context!r} is not registered. "
                   "Add the cluster via the Clusters page first.",
        )
    return context

# --- Namespaces ---
@router.get("/namespaces")
async def list_namespaces(
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> List[str]:
    """List all Kubernetes namespaces."""
    cluster_context = await _validate_cluster_context(cluster_context, db)
    try:
        return await k8s_service.list_namespaces(context=cluster_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cluster/health")
async def get_cluster_health(
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    """Get cluster health report."""
    cluster_context = await _validate_cluster_context(cluster_context, db)
    try:
        report = await k8s_service.get_cluster_health(context=cluster_context)
        return {"report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/namespaces/{name}")
async def delete_namespace(
    name: str,
    _: User = Depends(require_god_mode),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    """Delete a namespace. Requires God Mode."""
    try:
        result = await k8s_service.delete_namespace(name, god_mode=True, context=cluster_context)
        return {"message": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Pods ---
@router.get("/namespaces/{namespace}/pods")
async def list_pods(
    namespace: str,
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> List[Dict[str, Any]]:
    """List all pods in a namespace."""
    try:
        return await k8s_service.list_pods(namespace, context=cluster_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/namespaces/{namespace}/pods/{pod_name}/logs")
async def get_pod_logs(
    namespace: str,
    pod_name: str,
    tail_lines: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    """Get logs from a specific pod."""
    try:
        logs = await k8s_service.get_pod_logs(namespace, pod_name, tail_lines, context=cluster_context)
        return {"logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/namespaces/{namespace}/pods/{pod_name}")
async def delete_pod(
    namespace: str,
    pod_name: str,
    _: User = Depends(require_god_mode),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    """Delete a pod. Requires God Mode."""
    try:
        result = await k8s_service.delete_pod(namespace, pod_name, god_mode=True, context=cluster_context)
        return {"message": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Deployments ---
@router.get("/namespaces/{namespace}/deployments")
async def list_deployments(
    namespace: str,
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> List[Dict[str, Any]]:
    """List all deployments in a namespace."""
    try:
        return await k8s_service.list_deployments(namespace, context=cluster_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/namespaces/{namespace}/deployments/{deployment_name}/scale")
async def scale_deployment(
    namespace: str,
    deployment_name: str,
    body: Dict[str, int] = Body(...),
    _: User = Depends(require_god_mode),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    try:
        replicas = body.get("replicas")
        if replicas is None:
            raise HTTPException(status_code=400, detail="Replicas field required")
        result = await k8s_service.scale_deployment(namespace, deployment_name, replicas, god_mode=True, context=cluster_context)
        return {"message": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/namespaces/{namespace}/deployments/{deployment_name}/restart")
async def restart_deployment(
    namespace: str,
    deployment_name: str,
    _: User = Depends(require_god_mode),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    try:
        result = await k8s_service.restart_deployment(namespace, deployment_name, god_mode=True, context=cluster_context)
        return {"message": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/namespaces/{namespace}/deployments")
async def create_deployment(
    namespace: str,
    deployment: Dict[str, Any] = Body(...),
    _: User = Depends(require_god_mode),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    try:
        name = deployment.get("name")
        image = deployment.get("image")
        replicas = deployment.get("replicas", 1)
        if not name or not image:
            raise HTTPException(status_code=400, detail="Name and Image are required")
        result = await k8s_service.create_deployment_simple(namespace, name, image, replicas, god_mode=True, context=cluster_context)
        return {"message": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/namespaces/{namespace}/deployments/{deployment_name}")
async def delete_deployment(
    namespace: str,
    deployment_name: str,
    _: User = Depends(require_god_mode),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    """Delete a deployment. Requires God Mode."""
    try:
        result = await k8s_service.delete_deployment(namespace, deployment_name, god_mode=True, context=cluster_context)
        return {"message": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Services ---
@router.get("/namespaces/{namespace}/services")
async def list_services(
    namespace: str,
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> List[Dict[str, Any]]:
    """List all services in a namespace."""
    try:
        return await k8s_service.list_services(namespace, context=cluster_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ConfigMaps ---
@router.get("/namespaces/{namespace}/configmaps")
async def list_configmaps(
    namespace: str,
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> List[Dict[str, Any]]:
    """List all configmaps in a namespace."""
    try:
        return await k8s_service.list_configmaps(namespace, context=cluster_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/namespaces/{namespace}/configmaps/{name}")
async def get_configmap(
    namespace: str,
    name: str,
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, Any]:
    """Get a specific configmap."""
    try:
        return await k8s_service.get_configmap(namespace, name, context=cluster_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/namespaces/{namespace}/configmaps/{name}")
async def patch_configmap(
    namespace: str,
    name: str,
    body: Dict[str, Any] = Body(...),
    _: User = Depends(require_god_mode),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> Dict[str, str]:
    """Patch a specific configmap. Requires God Mode."""
    try:
        data = body.get("data")
        if data is None or not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Data field dictionary is required")

        result = await k8s_service.patch_configmap(namespace, name, data, god_mode=True, context=cluster_context)
        return {"message": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Secrets ---
@router.get("/namespaces/{namespace}/secrets")
async def list_secrets(
    namespace: str,
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> List[Dict[str, Any]]:
    """List all secrets in a namespace."""
    try:
        return await k8s_service.list_secrets(namespace, context=cluster_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pods/search")
async def search_pods(
    query: str,
    current_user: User = Depends(deps.get_current_user),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context")
) -> List[Dict[str, Any]]:
    """Global search for pods."""
    try:
        return await k8s_service.search_pods(query, context=cluster_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
