import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
import asyncio

from app.api import deps
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models.user import User
from app.services.k8s_service import k8s_service

router = APIRouter()


# --- Models ---

class TopoNode(BaseModel):
    id: str
    kind: str   # "Node" | "Namespace" | "Service" | "Pod"
    name: str
    namespace: Optional[str] = None
    health: str  # "healthy" | "warning" | "critical" | "unknown"
    cpu: Optional[float] = None
    memory: Optional[float] = None


class TopoEdge(BaseModel):
    source: str
    target: str
    kind: str  # "hosts" | "routes" | "owns"


class TopologySnapshot(BaseModel):
    nodes: List[TopoNode]
    edges: List[TopoEdge]
    version: int
    mock: bool = False


class NodeDetail(BaseModel):
    id: str
    kind: str
    name: str
    namespace: Optional[str]
    health: str
    events: str
    restart_count: int
    age: str


# --- Helpers ---

def _pod_health(status: str) -> str:
    if status in ("Running", "Succeeded"):
        return "healthy"
    if status in ("Pending", "Unknown"):
        return "warning"
    return "critical"


def _labels_match(selector: Dict[str, str], labels: Dict[str, str]) -> bool:
    return all(labels.get(k) == v for k, v in selector.items())


def _mock_snapshot() -> TopologySnapshot:
    nodes = [
        TopoNode(id="node/node-1", kind="Node", name="node-1", health="healthy"),
        TopoNode(id="node/node-2", kind="Node", name="node-2", health="warning"),
        TopoNode(id="ns/default", kind="Namespace", name="default", health="healthy"),
        TopoNode(id="ns/kube-system", kind="Namespace", name="kube-system", health="healthy"),
        TopoNode(id="svc/default/web-svc", kind="Service", name="web-svc", namespace="default", health="healthy"),
        TopoNode(id="pod/default/web-abc12", kind="Pod", name="web-abc12", namespace="default", health="healthy"),
        TopoNode(id="pod/default/web-def34", kind="Pod", name="web-def34", namespace="default", health="critical"),
        TopoNode(id="pod/default/api-xyz89", kind="Pod", name="api-xyz89", namespace="default", health="warning"),
        TopoNode(id="pod/kube-system/coredns-aaa", kind="Pod", name="coredns-aaa", namespace="kube-system", health="healthy"),
    ]
    edges = [
        TopoEdge(source="node/node-1", target="pod/default/web-abc12", kind="hosts"),
        TopoEdge(source="node/node-1", target="pod/default/api-xyz89", kind="hosts"),
        TopoEdge(source="node/node-2", target="pod/default/web-def34", kind="hosts"),
        TopoEdge(source="node/node-2", target="pod/kube-system/coredns-aaa", kind="hosts"),
        TopoEdge(source="ns/default", target="svc/default/web-svc", kind="owns"),
        TopoEdge(source="svc/default/web-svc", target="pod/default/web-abc12", kind="routes"),
        TopoEdge(source="svc/default/web-svc", target="pod/default/web-def34", kind="routes"),
    ]
    return TopologySnapshot(nodes=nodes, edges=edges, version=int(time.time()), mock=True)


async def build_topology_snapshot(context: Optional[str] = None) -> TopologySnapshot:
    """Build a full topology snapshot from live K8s data."""
    if k8s_service.mock_mode:
        return _mock_snapshot()

    nodes: List[TopoNode] = []
    edges: List[TopoEdge] = []

    # Physical nodes (K8s Nodes)
    k8s_nodes = await k8s_service.get_nodes(context=context)
    for n in k8s_nodes:
        health = "healthy" if n["status"] == "Ready" else "critical"
        nodes.append(TopoNode(id=f"node/{n['name']}", kind="Node", name=n["name"], health=health))

    # Namespaces
    namespaces = await k8s_service.list_namespaces(context=context)
    for ns in namespaces:
        nodes.append(TopoNode(id=f"ns/{ns}", kind="Namespace", name=ns, health="healthy"))

    # Pods
    all_pods: List[Dict[str, Any]] = []
    for ns in namespaces:
        pods = await k8s_service.list_pods(ns, context=context)
        for p in pods:
            pod_id = f"pod/{ns}/{p['name']}"
            health = _pod_health(p["status"])
            nodes.append(TopoNode(id=pod_id, kind="Pod", name=p["name"], namespace=ns, health=health))
            all_pods.append({"id": pod_id, "namespace": ns, "labels": p.get("labels", {}), "node_name": p.get("node_name", "")})
            # Physical edge: node hosts pod
            if p.get("node_name"):
                edges.append(TopoEdge(source=f"node/{p['node_name']}", target=pod_id, kind="hosts"))

    # Services (logical view)
    for ns in namespaces:
        services = await k8s_service.list_services(ns, context=context)
        for svc in services:
            svc_id = f"svc/{ns}/{svc['name']}"
            nodes.append(TopoNode(id=svc_id, kind="Service", name=svc["name"], namespace=ns, health="healthy"))
            edges.append(TopoEdge(source=f"ns/{ns}", target=svc_id, kind="owns"))
            # Route edges: service -> matching pods
            selector = svc.get("selector", {})
            if selector:
                for pod in all_pods:
                    if pod["namespace"] == ns and _labels_match(selector, pod["labels"]):
                        edges.append(TopoEdge(source=svc_id, target=pod["id"], kind="routes"))

    return TopologySnapshot(nodes=nodes, edges=edges, version=int(time.time()))


async def _validate_token(token: str, db: AsyncSession) -> User:
    try:
        payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = (await db.exec(select(User).where(User.username == username))).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive or unknown user")
    return user


# --- Endpoints ---

@router.get("/stream")
async def topology_stream(
    token: str = Query(...),
    cluster_context: Optional[str] = Query(None),
    db: AsyncSession = Depends(deps.get_async_db),
):
    """SSE stream of TopologySnapshot, refreshed every 10 seconds."""
    await _validate_token(token, db)

    async def event_generator():
        while True:
            snapshot = await build_topology_snapshot(cluster_context)
            yield f"data: {snapshot.model_dump_json()}\n\n"
            await asyncio.sleep(10)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/node/{kind}/{name}")
async def get_node_detail(
    kind: str,
    name: str,
    namespace: Optional[str] = Query(None),
    cluster_context: Optional[str] = Query(None),
    current_user: User = Depends(deps.get_current_user),
) -> Dict[str, Any]:
    """Return full detail for a topology node (pod, node, or service)."""
    try:
        if kind == "Pod" and namespace:
            events = await k8s_service.get_pod_events(namespace, name, context=cluster_context)
            details = await k8s_service.get_pod_details(namespace, name, context=cluster_context)
            pods = await k8s_service.list_pods(namespace, context=cluster_context)
            pod = next((p for p in pods if p["name"] == name), None)
            health = _pod_health(pod["status"]) if pod else "unknown"
            return {
                "id": f"pod/{namespace}/{name}",
                "kind": "Pod",
                "name": name,
                "namespace": namespace,
                "health": health,
                "events": events,
                "details": details,
                "restart_count": 0,
                "mock": k8s_service.mock_mode,
            }
        elif kind == "Node":
            k8s_nodes = await k8s_service.get_nodes(context=cluster_context)
            node = next((n for n in k8s_nodes if n["name"] == name), None)
            health = "healthy" if node and node["status"] == "Ready" else "critical"
            return {
                "id": f"node/{name}",
                "kind": "Node",
                "name": name,
                "namespace": None,
                "health": health,
                "events": "",
                "details": f"Status: {node['status'] if node else 'Unknown'}",
                "restart_count": 0,
                "mock": k8s_service.mock_mode,
            }
        elif kind == "Service" and namespace:
            services = await k8s_service.list_services(namespace, context=cluster_context)
            svc = next((s for s in services if s["name"] == name), None)
            return {
                "id": f"svc/{namespace}/{name}",
                "kind": "Service",
                "name": name,
                "namespace": namespace,
                "health": "healthy",
                "events": "",
                "details": f"Selector: {svc['selector'] if svc else 'N/A'}",
                "restart_count": 0,
                "mock": k8s_service.mock_mode,
            }
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported kind: {kind}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
