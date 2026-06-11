# backend/app/services/topology_service.py
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import networkx as nx

from app.services.k8s_service import k8s_service

logger = logging.getLogger(__name__)

# ── Tunable constants ─────────────────────────────────────────────────────────
MAX_GRAPH_NODES_FULL_BFS = 2000
STALE_THRESHOLD_SECONDS = 90
BFS_HOPS = 2
MAX_SEARCH_RESULTS = 3
TIER1_NAMESPACE_TRUNCATE_THRESHOLD = 10
TIER1_DEPLOYMENT_TRUNCATE_THRESHOLD = 30


def _node_id(kind: str, namespace: str, name: str) -> str:
    return f"{kind}/{namespace}/{name}"


class TopologyService:
    def __init__(self) -> None:
        self._graphs: Dict[str, nx.DiGraph] = {}
        self._last_built: Dict[str, datetime] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Called at app startup via FastAPI lifespan."""
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info("TopologyService background loop started")

    async def stop(self) -> None:
        """Called at app shutdown."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TopologyService stopped")

    async def _refresh_loop(self) -> None:
        await asyncio.sleep(10)  # let uvicorn finish startup before first K8s scan
        while True:
            try:
                await self._build_all_graphs()
            except Exception as e:
                logger.error(f"TopologyService refresh error: {e}")
            await asyncio.sleep(30)

    async def _build_all_graphs(self) -> None:
        contexts = list(k8s_service.clients.keys())
        for context in contexts:
            try:
                graph = await self._build_graph_for_context(context)
                async with self._lock:
                    self._graphs[context] = graph
                    self._last_built[context] = datetime.now(timezone.utc)
                logger.info(
                    f"Topology built for '{context}': "
                    f"{graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"
                )
            except Exception as e:
                logger.error(f"Failed to build topology for context '{context}': {e}")

    # ── Graph Build ───────────────────────────────────────────────────────────

    def _build_graph_for_context_sync(self, context: str) -> nx.DiGraph:
        """Synchronous wrapper around :meth:`_build_graph_for_context`.

        Used only in unit tests where there is no running event loop.
        """
        return asyncio.run(self._build_graph_for_context(context))

    async def _build_graph_for_context(self, context: str) -> nx.DiGraph:
        if k8s_service.mock_mode:
            return self._build_mock_graph()

        g: nx.DiGraph = nx.DiGraph()
        core_api = k8s_service._get_api("CoreV1Api", context)
        apps_api = k8s_service._get_api("AppsV1Api", context)
        batch_api = k8s_service._get_api("BatchV1Api", context)
        net_api = k8s_service._get_api("NetworkingV1Api", context)
        auto_api = k8s_service._get_api("AutoscalingV2Api", context)
        storage_api = k8s_service._get_api("StorageV1Api", context)

        (ns_res, pod_res, dep_res, ss_res, ds_res, job_res, cj_res,
         svc_res, ing_res, hpa_res, pvc_res, pv_res, sc_res) = await asyncio.gather(
            core_api.list_namespace(limit=500),
            core_api.list_pod_for_all_namespaces(limit=500),
            apps_api.list_deployment_for_all_namespaces(limit=500),
            apps_api.list_stateful_set_for_all_namespaces(limit=500),
            apps_api.list_daemon_set_for_all_namespaces(limit=500),
            batch_api.list_job_for_all_namespaces(limit=500),
            batch_api.list_cron_job_for_all_namespaces(limit=500),
            core_api.list_service_for_all_namespaces(limit=500),
            net_api.list_ingress_for_all_namespaces(limit=500),
            auto_api.list_horizontal_pod_autoscaler_for_all_namespaces(limit=500),
            core_api.list_persistent_volume_claim_for_all_namespaces(limit=500),
            core_api.list_persistent_volume(limit=500),
            storage_api.list_storage_class(limit=500),
            return_exceptions=True,
        )

        def _items(res: Any) -> list:
            """Return .items for a successful result, or [] if that fetch failed."""
            if isinstance(res, Exception):
                logger.debug(f"[{context}] resource scan failed: {res}")
                return []
            return res.items

        # 1. Namespaces
        for ns in _items(ns_res):
            nid = _node_id("Namespace", "", ns.metadata.name)
            g.add_node(nid, kind="Namespace", name=ns.metadata.name,
                       namespace="", labels=ns.metadata.labels or {},
                       status=ns.status.phase or "")

        # 2. Pods (must be fetched before Services for selector matching)
        pods = _items(pod_res)
        for pod in pods:
            ns = pod.metadata.namespace
            name = pod.metadata.name
            nid = _node_id("Pod", ns, name)
            g.add_node(nid, kind="Pod", name=name, namespace=ns,
                       labels=pod.metadata.labels or {},
                       status=pod.status.phase or "Unknown")
            for ref in (pod.metadata.owner_references or []):
                owner_id = _node_id(ref.kind, ns, ref.name)
                if not g.has_node(owner_id):
                    g.add_node(owner_id, kind=ref.kind, name=ref.name,
                               namespace=ns, labels={}, status="")
                g.add_edge(owner_id, nid, relation="owns")
            for vol in (pod.spec.volumes or []):
                if vol.config_map:
                    cm_id = _node_id("ConfigMap", ns, vol.config_map.name)
                    if not g.has_node(cm_id):
                        g.add_node(cm_id, kind="ConfigMap",
                                   name=vol.config_map.name,
                                   namespace=ns, labels={}, status="")
                    g.add_edge(nid, cm_id, relation="mounts")
                if vol.secret:
                    sec_id = _node_id("Secret", ns, vol.secret.secret_name)
                    if not g.has_node(sec_id):
                        g.add_node(sec_id, kind="Secret",
                                   name=vol.secret.secret_name,
                                   namespace=ns, labels={}, status="")
                    g.add_edge(nid, sec_id, relation="mounts")
                if vol.persistent_volume_claim:
                    pvc_id = _node_id("PVC", ns,
                                      vol.persistent_volume_claim.claim_name)
                    if not g.has_node(pvc_id):
                        g.add_node(pvc_id, kind="PVC",
                                   name=vol.persistent_volume_claim.claim_name,
                                   namespace=ns, labels={}, status="")
                    g.add_edge(nid, pvc_id, relation="mounts")
            for container in (pod.spec.containers or []):
                for env_from in (container.env_from or []):
                    if env_from.config_map_ref:
                        cm_id = _node_id("ConfigMap", ns,
                                         env_from.config_map_ref.name)
                        if not g.has_node(cm_id):
                            g.add_node(cm_id, kind="ConfigMap",
                                       name=env_from.config_map_ref.name,
                                       namespace=ns, labels={}, status="")
                        g.add_edge(nid, cm_id, relation="mounts")
                    if env_from.secret_ref:
                        sec_id = _node_id("Secret", ns,
                                          env_from.secret_ref.name)
                        if not g.has_node(sec_id):
                            g.add_node(sec_id, kind="Secret",
                                       name=env_from.secret_ref.name,
                                       namespace=ns, labels={}, status="")
                        g.add_edge(nid, sec_id, relation="mounts")

        # 3. Deployments
        for dep in _items(dep_res):
            ns = dep.metadata.namespace
            name = dep.metadata.name
            ready = dep.status.ready_replicas or 0
            desired = dep.spec.replicas or 0
            nid = _node_id("Deployment", ns, name)
            g.add_node(nid, kind="Deployment", name=name, namespace=ns,
                       labels=dep.metadata.labels or {},
                       status=f"{ready}/{desired}")

        # 4. StatefulSets
        for ss in _items(ss_res):
            ns = ss.metadata.namespace
            name = ss.metadata.name
            ready = ss.status.ready_replicas or 0
            desired = ss.spec.replicas or 0
            nid = _node_id("StatefulSet", ns, name)
            g.add_node(nid, kind="StatefulSet", name=name, namespace=ns,
                       labels=ss.metadata.labels or {},
                       status=f"{ready}/{desired}")

        # 5. DaemonSets
        for ds in _items(ds_res):
            ns = ds.metadata.namespace
            name = ds.metadata.name
            desired = ds.status.desired_number_scheduled or 0
            ready = ds.status.number_ready or 0
            nid = _node_id("DaemonSet", ns, name)
            g.add_node(nid, kind="DaemonSet", name=name, namespace=ns,
                       labels=ds.metadata.labels or {},
                       status=f"{ready}/{desired}")

        # 6. Jobs
        for job in _items(job_res):
            ns = job.metadata.namespace
            name = job.metadata.name
            succeeded = job.status.succeeded or 0
            failed = job.status.failed or 0
            nid = _node_id("Job", ns, name)
            if succeeded > 0:
                job_status = "Succeeded"
            elif failed > 0:
                job_status = "Failed"
            else:
                job_status = "Running"
            g.add_node(nid, kind="Job", name=name, namespace=ns,
                       labels=job.metadata.labels or {},
                       status=job_status)
            for ref in (job.metadata.owner_references or []):
                if ref.kind == "CronJob":
                    cj_id = _node_id("CronJob", ns, ref.name)
                    if not g.has_node(cj_id):
                        g.add_node(cj_id, kind="CronJob", name=ref.name,
                                   namespace=ns, labels={}, status="")
                    g.add_edge(cj_id, nid, relation="owns")

        # 7. CronJobs
        for cj in _items(cj_res):
            ns = cj.metadata.namespace
            name = cj.metadata.name
            nid = _node_id("CronJob", ns, name)
            status = "Suspended" if cj.spec.suspend else "Active"
            if not g.has_node(nid):
                g.add_node(nid, kind="CronJob", name=name, namespace=ns,
                           labels=cj.metadata.labels or {}, status=status)
            else:
                g.nodes[nid]["status"] = status

        # Build a namespace -> pods index once (replaces the O(services x pods) scan).
        pods_by_ns: Dict[str, list] = {}
        for pod in pods:
            pods_by_ns.setdefault(pod.metadata.namespace, []).append(pod)

        # 8. Services + label selector -> pod matching
        for svc in _items(svc_res):
            ns = svc.metadata.namespace
            name = svc.metadata.name
            nid = _node_id("Service", ns, name)
            g.add_node(nid, kind="Service", name=name, namespace=ns,
                       labels=svc.metadata.labels or {},
                       status=svc.spec.type or "")
            if svc.spec.selector:
                for pod in pods_by_ns.get(ns, []):
                    pod_labels = pod.metadata.labels or {}
                    if all(pod_labels.get(k) == v for k, v in svc.spec.selector.items()):
                        pod_id = _node_id("Pod", ns, pod.metadata.name)
                        if g.has_node(pod_id):
                            g.add_edge(nid, pod_id, relation="selects")

        # 9. Ingresses
        for ing in _items(ing_res):
            ns = ing.metadata.namespace
            name = ing.metadata.name
            nid = _node_id("Ingress", ns, name)
            g.add_node(nid, kind="Ingress", name=name, namespace=ns,
                       labels=ing.metadata.labels or {}, status="")
            for rule in (ing.spec.rules or []):
                if rule.http:
                    for path in (rule.http.paths or []):
                        svc_name = (
                            path.backend.service.name
                            if path.backend and path.backend.service
                            else None
                        )
                        if svc_name:
                            svc_id = _node_id("Service", ns, svc_name)
                            if g.has_node(svc_id):
                                g.add_edge(nid, svc_id, relation="routes-to")

        # 10. HPAs
        for hpa in _items(hpa_res):
            ns = hpa.metadata.namespace
            name = hpa.metadata.name
            nid = _node_id("HPA", ns, name)
            g.add_node(nid, kind="HPA", name=name, namespace=ns,
                       labels=hpa.metadata.labels or {}, status="")
            ref = hpa.spec.scale_target_ref
            if ref:
                target_id = _node_id(ref.kind, ns, ref.name)
                if g.has_node(target_id):
                    g.add_edge(nid, target_id, relation="scales")

        # 11. PVCs
        for pvc in _items(pvc_res):
            ns = pvc.metadata.namespace
            name = pvc.metadata.name
            nid = _node_id("PVC", ns, name)
            if not g.has_node(nid):
                g.add_node(nid, kind="PVC", name=name, namespace=ns,
                           labels=pvc.metadata.labels or {},
                           status=pvc.status.phase or "")
            else:
                g.nodes[nid]["status"] = pvc.status.phase or ""
            if pvc.spec.volume_name:
                pv_id = _node_id("PV", "", pvc.spec.volume_name)
                if not g.has_node(pv_id):
                    g.add_node(pv_id, kind="PV", name=pvc.spec.volume_name,
                               namespace="", labels={}, status="")
                g.add_edge(nid, pv_id, relation="bound-to")
            if pvc.spec.storage_class_name:
                sc_id = _node_id("StorageClass", "",
                                 pvc.spec.storage_class_name)
                if not g.has_node(sc_id):
                    g.add_node(sc_id, kind="StorageClass",
                               name=pvc.spec.storage_class_name,
                               namespace="", labels={}, status="")
                g.add_edge(nid, sc_id, relation="requests")

        # 12. PVs
        for pv in _items(pv_res):
            pv_id = _node_id("PV", "", pv.metadata.name)
            cap = (pv.spec.capacity.get("storage", "")
                   if pv.spec.capacity else "")
            if not g.has_node(pv_id):
                g.add_node(pv_id, kind="PV", name=pv.metadata.name,
                           namespace="", labels={}, status=pv.status.phase or "")
            else:
                g.nodes[pv_id]["status"] = pv.status.phase or ""
            g.nodes[pv_id]["capacity"] = cap

        # 13. StorageClasses
        for sc in _items(sc_res):
            sc_id = _node_id("StorageClass", "", sc.metadata.name)
            if not g.has_node(sc_id):
                g.add_node(sc_id, kind="StorageClass", name=sc.metadata.name,
                           namespace="", labels={}, status="")

        return g

    def _build_mock_graph(self) -> nx.DiGraph:
        g: nx.DiGraph = nx.DiGraph()
        g.add_node("Namespace//default", kind="Namespace", name="default",
                   namespace="", labels={}, status="Active")
        dep_id = _node_id("Deployment", "default", "mock-api")
        pod_id = _node_id("Pod", "default", "mock-api-abc123")
        svc_id = _node_id("Service", "default", "mock-api-svc")
        g.add_node(dep_id, kind="Deployment", name="mock-api",
                   namespace="default", labels={}, status="1/1")
        g.add_node(pod_id, kind="Pod", name="mock-api-abc123",
                   namespace="default", labels={"app": "mock-api"},
                   status="Running")
        g.add_node(svc_id, kind="Service", name="mock-api-svc",
                   namespace="default", labels={}, status="ClusterIP")
        g.add_edge(dep_id, pod_id, relation="owns")
        g.add_edge(svc_id, pod_id, relation="selects")
        return g

    # ── Tier 1: Cluster Overview ──────────────────────────────────────────────

    def get_cluster_overview(self, context: str) -> str:
        graph = self._graphs.get(context)
        if not graph:
            return "Topology snapshot not yet available (building...)"

        last = self._last_built.get(context)
        age_s = int((datetime.now(timezone.utc) - last).total_seconds()) if last else 0
        staleness = ""
        if age_s > STALE_THRESHOLD_SECONDS:
            staleness = f"\n⚠ Topology may be stale (last built {age_s // 60}m ago)"

        by_kind: Dict[str, List[Any]] = {}
        for _nid, attrs in graph.nodes(data=True):
            k = attrs.get("kind", "Unknown")
            by_kind.setdefault(k, []).append(attrs)

        namespaces = [a["name"] for a in by_kind.get("Namespace", [])]
        deployments = by_kind.get("Deployment", [])
        statefulsets = by_kind.get("StatefulSet", [])
        daemonsets = by_kind.get("DaemonSet", [])
        services = [a["name"] for a in by_kind.get("Service", [])]
        ingresses = by_kind.get("Ingress", [])
        pods = by_kind.get("Pod", [])

        large = (len(namespaces) > TIER1_NAMESPACE_TRUNCATE_THRESHOLD
                 or len(deployments) > TIER1_DEPLOYMENT_TRUNCATE_THRESHOLD)

        lines = [f"CLUSTER TOPOLOGY SNAPSHOT (context: {context}, as of {age_s}s ago)"]

        ns_names = ", ".join(namespaces) if namespaces else "none"
        lines.append(
            f"Namespaces ({len(namespaces)}): "
            + ("[too many to list]" if large else ns_names)
        )

        if large:
            lines.append(f"Deployments ({len(deployments)}): {len(deployments)} total")
        else:
            dep_strs = [f"{a['name']}[{a.get('status', '')}]" for a in deployments]
            lines.append(f"Deployments ({len(deployments)}): "
                         + (", ".join(dep_strs) if dep_strs else "none"))

        if statefulsets:
            ss_strs = [f"{a['name']}[{a.get('status', '')}]" for a in statefulsets]
            lines.append(f"StatefulSets ({len(statefulsets)}): {', '.join(ss_strs)}")

        if daemonsets:
            ds_strs = [f"{a['name']}[{a.get('status', '')}]" for a in daemonsets]
            lines.append(f"DaemonSets ({len(daemonsets)}): {', '.join(ds_strs)}")

        if services:
            svc_str = (f"{len(services)} total" if large
                       else ", ".join(services[:20]))
            lines.append(f"Services ({len(services)}): {svc_str}")

        if ingresses:
            lines.append(f"Ingresses ({len(ingresses)}): "
                         + ", ".join(a["name"] for a in ingresses))

        unhealthy_pods = [a for a in pods
                          if a.get("status") not in ("Running", "Succeeded", "")]
        unhealthy_pvcs = [a for a in by_kind.get("PVC", [])
                          if a.get("status") == "Pending"]
        if unhealthy_pods or unhealthy_pvcs:
            parts: List[str] = []
            for p in unhealthy_pods[:5]:
                parts.append(f"{p['name']} ({p.get('status', 'Unknown')})")
            for p in unhealthy_pvcs:
                parts.append(f"{p['name']} PVC (Pending)")
            lines.append(f"\nUnhealthy: {', '.join(parts)}")

        if staleness:
            lines.append(staleness)

        return "\n".join(lines).strip()

    # ── Tier 2: Topology Search ───────────────────────────────────────────────

    def search_topology(self, query: str, context: str) -> str:
        graph = self._graphs.get(context)
        if not graph:
            return f"No topology data for context: {context}"

        q = query.lower()
        matches = [
            (nid, attrs) for nid, attrs in graph.nodes(data=True)
            if (q in attrs.get("name", "").lower()
                or q in attrs.get("namespace", "").lower()
                or q in attrs.get("kind", "").lower()
                or q in attrs.get("status", "").lower())
        ][:MAX_SEARCH_RESULTS]

        if not matches:
            return f"No topology matches found for '{query}'"

        hops = 1 if graph.number_of_nodes() > MAX_GRAPH_NODES_FULL_BFS else BFS_HOPS
        lines: List[str] = []

        for nid, attrs in matches:
            ns_label = attrs.get("namespace") or "cluster-scoped"
            lines.append(
                f"TOPOLOGY: {attrs['name']} ({attrs['kind']}/{ns_label})"
            )
            lines.append(f"  Status: {attrs.get('status', 'Unknown')}")

            # Ancestors (incoming)
            ancestors = [
                a for a in nx.bfs_tree(graph.reverse(copy=False), nid, depth_limit=hops).nodes()
                if a != nid
            ]
            for anid in ancestors[:10]:
                a = graph.nodes[anid]
                rel = (graph.edges[anid, nid].get("relation", "?")
                       if graph.has_edge(anid, nid) else "ancestor")
                lines.append(f"  ← {rel}: {a['name']} ({a['kind']})")

            # Descendants (outgoing)
            descendants = [
                d for d in nx.bfs_tree(graph, nid, depth_limit=hops).nodes()
                if d != nid
            ]
            for dnid in descendants[:10]:
                d = graph.nodes[dnid]
                rel = (graph.edges[nid, dnid].get("relation", "?")
                       if graph.has_edge(nid, dnid) else "downstream")
                lines.append(
                    f"  → {rel}: {d['name']} ({d['kind']}, {d.get('status', '')})"
                )

            if len(ancestors) > 10 or len(descendants) > 10:
                lines.append("  ... (+ more related resources, use more specific query)")
            lines.append("")

        return "\n".join(lines).strip()

    def get_blast_radius(self, kind: str, name: str, namespace: str,
                         context: str) -> str:
        graph = self._graphs.get(context)
        if not graph:
            return f"No topology data for context: {context}"

        nid = _node_id(kind, namespace, name)
        if not graph.has_node(nid):
            return f"Resource not found in topology: {kind}/{namespace}/{name}"

        descendants = [
            d for d in nx.bfs_tree(graph, nid, depth_limit=BFS_HOPS).nodes()
            if d != nid
        ]

        if not descendants:
            return f"No downstream dependencies found for {kind}/{name}"

        ns_label = namespace or "cluster-scoped"
        lines = [
            f"BLAST RADIUS: {name} ({kind}/{ns_label})",
            "If this resource is degraded or deleted, the following are affected:",
        ]
        for dnid in descendants[:20]:
            d = graph.nodes[dnid]
            rel = (graph.edges[nid, dnid].get("relation", "?")
                   if graph.has_edge(nid, dnid) else "downstream")
            d_ns = d.get("namespace") or "cluster-scoped"
            lines.append(
                f"  → {rel}: {d['name']} ({d['kind']}/{d_ns}, {d.get('status', '')})"
            )
        if len(descendants) > 20:
            lines.append(f"  ... and {len(descendants) - 20} more resources")
        return "\n".join(lines)


topology_service = TopologyService()
