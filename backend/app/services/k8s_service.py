import logging
from contextvars import ContextVar
from typing import List, Optional, Dict, Any
from kubernetes_asyncio import client, config
from kubernetes_asyncio.client.rest import ApiException
from app.core.config import settings

logger = logging.getLogger(__name__)

# Set this before running an agent loop to scope all tool calls to a specific cluster.
# Uses ContextVar so concurrent asyncio tasks each see their own value.
active_cluster_ctx: ContextVar[Optional[str]] = ContextVar("active_cluster_ctx", default=None)

class K8sService:
    def __init__(self):
        self.mock_mode = True  # safe default; real init happens in initialize()
        # Structure: { "context_name": { "CoreV1Api": client, "AppsV1Api": client, ... } }
        self.clients: Dict[str, Dict[str, Any]] = {}
        self.api_clients: Dict[str, Any] = {}  # stored for lifecycle cleanup
        self.default_context = "default"

    async def initialize(self) -> None:
        """Call once from FastAPI lifespan before serving requests."""
        await self._load_default_config()
        await self.load_from_db()

    async def _load_default_config(self) -> None:
        try:
            if settings.K8S_IN_CLUSTER_CONFIG:
                await config.load_incluster_config()
                self.default_context = "in-cluster"
                logger.info("Loaded in-cluster config")
            else:
                await config.load_kube_config()
                try:
                    # Attempt to get the actual current context name
                    # list_kube_config_contexts() is synchronous (reads already-loaded config)
                    _, active_context = config.list_kube_config_contexts()
                    if active_context:
                        self.default_context = active_context["name"]
                        logger.info(f"Loaded active context: {self.default_context}")
                except Exception as e:
                    logger.warning(f"Could not fetch context name, defaulting to 'default': {e}")

            api_client = await config.new_client_from_config(context=self.default_context)
            self._initialize_clients(self.default_context, api_client)
            self.mock_mode = False
        except Exception as e:
            logger.warning(f"No local kubeconfig available ({e}). Will use DB cluster connections if present.")
            self.mock_mode = True

    def _initialize_clients(self, context_name: str, api_client: Any) -> None:
        """Registers API clients for a context. Always pass an ApiClient."""
        try:
            self.api_clients[context_name] = api_client
            self.clients[context_name] = {
                "CoreV1Api": client.CoreV1Api(api_client),
                "AppsV1Api": client.AppsV1Api(api_client),
                "BatchV1Api": client.BatchV1Api(api_client),
                "CustomObjectsApi": client.CustomObjectsApi(api_client),
                "AutoscalingV1Api": client.AutoscalingV1Api(api_client),
                "NetworkingV1Api": client.NetworkingV1Api(api_client),
                "RbacAuthorizationV1Api": client.RbacAuthorizationV1Api(api_client),
                "AutoscalingV2Api": client.AutoscalingV2Api(api_client),
                "PolicyV1Api": client.PolicyV1Api(api_client),
                "StorageV1Api": client.StorageV1Api(api_client),
            }
        except Exception as e:
            logger.error(f"Failed to initialize clients for {context_name}: {e}")
            if context_name == self.default_context:
                self.mock_mode = True

    async def _ensure_context_loaded(self, ctx: str) -> None:
        """Ensures the context is loaded into self.clients. Must be awaited before _get_api in async methods."""
        if ctx in self.clients or self.mock_mode:
            return
        try:
            new_api_client = await config.new_client_from_config(context=ctx)
            self._initialize_clients(ctx, new_api_client)
            logger.info(f"Lazy-loaded context: {ctx}")
        except Exception as e:
            logger.warning(f"Could not lazy-load context '{ctx}': {e}")

    def _build_client_from_connection(self, conn: "ClusterConnection") -> Any:
        """Build a kubernetes_asyncio ApiClient from a ClusterConnection row."""
        import tempfile
        import os
        import base64
        from app.core.encryption import decrypt

        configuration = client.Configuration()
        configuration.host = conn.api_server
        tmp_paths: list[str] = []

        def _write_tmp(data_b64: str, suffix: str) -> str:
            raw = base64.b64decode(data_b64)
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(raw)
                tmp_paths.append(f.name)
                return f.name

        try:
            # Client-certificate auth (AKS admin creds) takes precedence
            if conn.client_cert_data and conn.client_key_data:
                configuration.cert_file = _write_tmp(conn.client_cert_data, ".crt")
                configuration.key_file  = _write_tmp(decrypt(conn.client_key_data), ".key")
            else:
                token = decrypt(conn.token)
                configuration.api_key["authorization"] = f"Bearer {token}"

            if conn.ca_cert:
                configuration.ssl_ca_cert = _write_tmp(conn.ca_cert, ".pem")
                configuration.verify_ssl = True
            else:
                configuration.verify_ssl = False

            api_client = client.ApiClient(configuration=configuration)
            # Attach tmp_paths so remove_connection can clean them up
            api_client._dokops_tmp_paths = tmp_paths
            return api_client
        except Exception:
            for p in tmp_paths:
                if os.path.exists(p):
                    os.unlink(p)
            raise

    async def add_connection(self, conn: "ClusterConnection") -> None:
        """Register a ClusterConnection as a live k8s client. Safe to call at runtime."""
        try:
            api_client = self._build_client_from_connection(conn)
            self._initialize_clients(conn.name, api_client)
            self.mock_mode = False
            # Promote to default if no real default is registered yet
            if self.default_context not in self.clients:
                self.default_context = conn.name
                logger.info(f"Set default context to '{conn.name}'")
            logger.info(f"Registered cluster connection: {conn.name}")
        except Exception as e:
            logger.error(f"Failed to register connection '{conn.name}': {e}")
            raise

    async def remove_connection(self, cluster_id: str) -> None:
        """De-register a cluster client by name."""
        import os
        self.clients.pop(cluster_id, None)
        api_client = self.api_clients.pop(cluster_id, None)
        if api_client:
            try:
                # Clean up all temp files (CA cert, client cert, client key)
                for p in getattr(api_client, "_dokops_tmp_paths", []):
                    if os.path.exists(p):
                        os.unlink(p)
            except Exception:
                pass
            try:
                await api_client.close()
            except Exception:
                pass
        logger.info(f"Removed cluster connection: {cluster_id}")

    async def load_from_db(self) -> None:
        """Load all ClusterConnection rows from DB and register live clients."""
        from sqlmodel import select
        from app.core.db import AsyncSessionLocal
        from app.models.cluster import ClusterConnection

        try:
            async with AsyncSessionLocal() as db:
                connections = (await db.exec(select(ClusterConnection))).all()
            loaded: list[str] = []
            for conn in connections:
                try:
                    await self.add_connection(conn)
                    loaded.append(conn.name)
                except Exception as e:
                    logger.warning(f"Skipping DB cluster '{conn.name}': {e}")
            # If no kubeconfig was available at startup, promote the first DB cluster
            # to default so context=None calls resolve correctly.
            if loaded and self.default_context not in self.clients:
                self.default_context = loaded[0]
                logger.info(f"No kubeconfig default — using DB cluster '{loaded[0]}' as default context")
            logger.info(f"Loaded {len(loaded)} cluster connection(s) from DB")
        except Exception as e:
            logger.error(f"load_from_db failed: {e}")

    async def close(self) -> None:
        """Close all aiohttp sessions. Call from FastAPI lifespan shutdown."""
        for ctx, api_client in list(self.api_clients.items()):
            try:
                await api_client.close()
            except Exception as e:
                logger.warning(f"Error closing ApiClient for context '{ctx}': {e}")
        self.api_clients.clear()
        self.clients.clear()
        self.mock_mode = True
        self.default_context = "default"

    def _get_api(self, api_type: str, context: Optional[str] = None) -> Any:
        """Retrieves the requested API client for the specified context (pure dict lookup — call _ensure_context_loaded first in async methods)."""
        ctx = context or active_cluster_ctx.get() or self.default_context

        # If the requested context exists, use it!
        if ctx in self.clients:
            return self.clients[ctx][api_type]

        # Usage of Mock Mode fallback
        if self.mock_mode:
            return None

        # If we reach here, the context is truly invalid/unreachable
        # Instead of crashing, we log and return None so methods can handle graceful degradation
        logger.error(f"Context '{ctx}' not found and could not be loaded.")
        return None

    async def add_context_from_file(self, config_file: str) -> List[str]:
        """Loads all contexts from a kubeconfig file."""
        import yaml
        added_contexts = []
        try:
            with open(config_file, "r") as f:
                kubeconfig = yaml.safe_load(f)

            contexts = kubeconfig.get("contexts", [])
            if not contexts:
                raise ValueError("No contexts found in kubeconfig file.")

            for ctx in contexts:
                context_name = ctx["name"]
                try:
                    new_api_client = await config.new_client_from_config(
                        config_file=config_file, context=context_name
                    )
                    self._initialize_clients(context_name, new_api_client)
                    added_contexts.append(context_name)
                    logger.info(f"Successfully added context: {context_name}")
                except Exception as e:
                    logger.warning(f"Failed to load context '{context_name}': {e}")

            if added_contexts:
                self.mock_mode = False
                if self.default_context == "default":
                    self.default_context = added_contexts[0]
                logger.info(f"Kubeconfig uploaded; mock_mode disabled, default context: {self.default_context}")

            return added_contexts
        except Exception as e:
            logger.error(f"Failed to parse kubeconfig file: {e}")
            raise e

    def get_contexts(self) -> List[str]:
        return list(self.clients.keys())

    def _parse_cpu(self, cpu_str: str) -> float:
        """Converts k8s CPU string to millicores."""
        if cpu_str.endswith('n'): return float(cpu_str[:-1]) / 1_000_000
        if cpu_str.endswith('u'): return float(cpu_str[:-1]) / 1_000
        if cpu_str.endswith('m'): return float(cpu_str[:-1])
        return float(cpu_str) * 1000

    def _parse_memory(self, mem_str: str) -> float:
        """Converts k8s memory string to MiB."""
        unit_multipliers = {
            'Ki': 1 / 1024, 'Mi': 1, 'Gi': 1024, 'Ti': 1024**2,
            'K': 0.001, 'M': 1, 'G': 1000, 'T': 1000**2
        }
        for unit, mult in unit_multipliers.items():
            if mem_str.endswith(unit):
                return float(mem_str[:-len(unit)]) * mult
        return float(mem_str) / (1024**2) # Assume bytes if no unit

    def _format_cpu(self, millis: float) -> str:
        """Formats millicores to human readable string."""
        if millis >= 1000:
            return f"{millis/1000:.2f} cores"
        return f"{int(millis)}m"

    def _format_memory(self, mib: float) -> str:
        """Formats MiB to human readable string."""
        if mib >= 1024:
            return f"{mib/1024:.2f} Gi"
        return f"{int(mib)} Mi"

    async def get_node_metrics(self, context: str = None) -> Dict[str, Any]:
        """
        Fetches node metrics and calculates utilization percentages.
        """
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            # 1. Fetch Node Capacity (Allocatable)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                 return {
                    "available": False,
                    "error": "No Kubeconfig loaded",
                    "nodes": []
                }
            nodes_list = await core_api.list_node()
            node_capacities = {}
            for node in nodes_list.items:
                node_capacities[node.metadata.name] = {
                    "cpu": self._parse_cpu(node.status.allocatable["cpu"]),
                    "memory": self._parse_memory(node.status.allocatable["memory"])
                }

            # 2. Fetch Metrics (Usage)
            custom_api = self._get_api("CustomObjectsApi", ctx)
            metrics = await custom_api.list_cluster_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                plural="nodes"
            )

            nodes_data = []

            for item in metrics["items"]:
                name = item["metadata"]["name"]
                usage = item["usage"]

                # Parse Usage (float values)
                cpu_usage_float = self._parse_cpu(usage["cpu"])
                mem_usage_float = self._parse_memory(usage["memory"])

                # Get Capacity
                capacity = node_capacities.get(name)

                # Calculate percentages
                if capacity:
                    cpu_percent = round((cpu_usage_float / capacity["cpu"]) * 100, 1)
                    mem_percent = round((mem_usage_float / capacity["memory"]) * 100, 1)
                else:
                    # Fallback if capacity not found: assume usage is valid but % is unknown
                    # avoiding 100% assumption which confuses users
                    cpu_percent = 0
                    mem_percent = 0

                nodes_data.append({
                    "name": name,
                    "cpu_usage": self._format_cpu(cpu_usage_float),
                    "cpu_percent": cpu_percent,
                    "memory_usage": self._format_memory(mem_usage_float),
                    "memory_percent": mem_percent,
                    "raw_cpu": usage["cpu"], # Keep raw for debug if needed, but not used in UI
                    "raw_mem": usage["memory"]
                })

            return {
                "available": True,
                "nodes": nodes_data
            }

        except ApiException as e:
            if e.status in [404, 403]:
                logger.warning("Metrics Server not found or not accessible.")
                return {"available": False, "error": "Metrics Server not installed"}
            logger.error(f"Error fetching metrics: {e}")
            return {"available": False, "error": str(e)}
        except Exception as e:
            logger.warning("Could not reach cluster for metrics: %s", e)
            return {"available": False, "error": "Cluster unreachable"}


    def _check_permission(self, god_mode: bool, operation: str) -> None:
        if operation == "DELETE" and not god_mode:
            raise PermissionError("DELETE operations require God Mode enabled.")

    # --- Discovery ---
    async def list_namespaces(self, context: str = None) -> List[str]:
        ctx = context or self.default_context
        await self._ensure_context_loaded(ctx)
        # Try to get API. If None (Mock Mode + No Context), return empty.
        core_api = self._get_api("CoreV1Api", ctx)
        if not core_api:
            return []
        namespaces = await core_api.list_namespace()
        return [ns.metadata.name for ns in namespaces.items]

    async def list_pods(self, namespace: str, context: str = None) -> List[Dict[str, Any]]:
        ctx = context or self.default_context
        await self._ensure_context_loaded(ctx)
        core_api = self._get_api("CoreV1Api", ctx)
        if not core_api:
            return []
        pods = await core_api.list_namespaced_pod(namespace)
        result = []
        for p in pods.items:
            phase = p.status.phase or "Unknown"
            status = phase
            # Detect container-level failure states that override "Running" phase
            if p.status.container_statuses:
                for cs in p.status.container_statuses:
                    if cs.state and cs.state.waiting and cs.state.waiting.reason:
                        status = cs.state.waiting.reason
                        break
                    elif cs.state and cs.state.terminated and cs.state.terminated.reason:
                        status = cs.state.terminated.reason
                        break
            result.append({
                "name": p.metadata.name,
                "status": status,
                "ip": p.status.pod_ip,
                "node_name": p.spec.node_name or "",
                "labels": p.metadata.labels or {},
                "namespace": p.metadata.namespace or namespace,
            })
        return result

    async def list_services(self, namespace: str, context: str = None) -> List[Dict[str, Any]]:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return []
            services = await core_api.list_namespaced_service(namespace)
            result = []
            for svc in services.items:
                result.append({
                    "name": svc.metadata.name,
                    "namespace": svc.metadata.namespace or namespace,
                    "selector": svc.spec.selector or {},
                })
            return result
        except ApiException as e:
            logger.error(f"Failed to list services in {namespace}: {e}")
            return []

    async def get_pod_logs(self, namespace: str, pod_name: str, tail_lines: int = 100, context: str = None) -> str:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return "No Kubeconfig loaded. Cannot fetch logs."
            return await core_api.read_namespaced_pod_log(pod_name, namespace, tail_lines=tail_lines)
        except ApiException as e:
            return f"Error getting logs: {e}"

    async def get_pod_events(self, namespace: str, pod_name: str, context: str = None) -> str:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return "No Kubeconfig loaded. Cannot fetch events."

            field_selector = f"involvedObject.name={pod_name},involvedObject.kind=Pod"
            events = await core_api.list_namespaced_event(
                namespace,
                field_selector=field_selector
            )

            if not events.items:
                return "No events found for this pod."

            formatted_events = []
            for e in events.items[-20:]: # Last 20 events
                formatted_events.append(f"[{e.type}] {e.reason}: {e.message}")
            return "\n".join(formatted_events)
        except ApiException as e:
            return f"Error getting events: {e}"

    async def get_pod_details(self, namespace: str, pod_name: str, context: str = None) -> str:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return "No Kubeconfig loaded."
            pod = await core_api.read_namespaced_pod(pod_name, namespace)
            return f"Phase: {pod.status.phase}\nNode: {pod.spec.node_name}\nCreated: {pod.metadata.creation_timestamp}\nLabels: {pod.metadata.labels}"
        except ApiException as e:
            return f"Error getting pod details: {e}"

    # --- Diagnostics ---
    async def get_nodes(self, context: str = None) -> List[Dict[str, Any]]:
        ctx = context or self.default_context
        await self._ensure_context_loaded(ctx)
        core_api = self._get_api("CoreV1Api", ctx)
        if not core_api:
            return []
        nodes = await core_api.list_node()
        return [{"name": n.metadata.name, "status": n.status.conditions[-1].type} for n in nodes.items]

    # --- Management (Protected) ---
    async def delete_pod(self, namespace: str, pod_name: str, god_mode: bool = False, context: str = None) -> str:
        self._check_permission(god_mode, "DELETE")
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                 return "No Kubeconfig loaded. Cannot delete pod."
            await core_api.delete_namespaced_pod(pod_name, namespace)
            return f"Pod {pod_name} deleted successfully."
        except ApiException as e:
            return f"Failed to delete pod: {e}"

    async def scale_deployment(self, namespace: str, deployment_name: str, replicas: int, god_mode: bool = False, context: str = None) -> str:
        self._check_permission(god_mode, "MODIFY")
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            # Check if HPA exists for this deployment
            autoscaling_api = self._get_api("AutoscalingV1Api", ctx)
            if not autoscaling_api:
                return "No Kubeconfig loaded. Cannot scale deployment."

            # Using dynamic lookup for HPA (simplified)
            hpas = await autoscaling_api.list_namespaced_horizontal_pod_autoscaler(namespace)
            for hpa in hpas.items:
                if hpa.spec.scale_target_ref.kind == "Deployment" and hpa.spec.scale_target_ref.name == deployment_name:
                    return f"Cannot scale {deployment_name}: Managed by HPA '{hpa.metadata.name}' (min: {hpa.spec.min_replicas}, max: {hpa.spec.max_replicas}). Modify the HPA instead."

            # Patch the Deployment spec directly for robust scaling
            apps_api = self._get_api("AppsV1Api", ctx)
            if not apps_api:
                return "Error: AppsV1Api not available (mock mode or context not loaded)"
            patch = {"spec": {"replicas": replicas}}
            await apps_api.patch_namespaced_deployment(deployment_name, namespace, patch)
            return f"Scaled {deployment_name} to {replicas}."
        except ApiException as e:
            return f"Failed to scale deployment: {e}"

    # --- Resource Management ---
    async def list_deployments(self, namespace: str, context: str = None) -> List[Dict[str, Any]]:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            apps_api = self._get_api("AppsV1Api", ctx)
            if not apps_api:
                return []
            deployments = await apps_api.list_namespaced_deployment(namespace)
            return [
                {
                    "name": d.metadata.name,
                    "replicas": d.spec.replicas,
                    "available": d.status.available_replicas or 0,
                    "namespace": namespace
                }
                for d in deployments.items
            ]
        except ApiException as e:
            logger.error(f"Failed to list deployments: {e}")
            return []

    # Alias for compatibility if needed
    list_deployments_with_context = list_deployments

    async def restart_deployment(self, namespace: str, deployment_name: str, god_mode: bool = False, context: str = None) -> str:
        self._check_permission(god_mode, "MODIFY")
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            apps_api = self._get_api("AppsV1Api", ctx)
            if not apps_api:
                return "No Kubeconfig loaded. Cannot restart deployment."

            # Trigger rollout restart by adding/updating annotation
            from datetime import datetime
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": datetime.utcnow().isoformat()
                            }
                        }
                    }
                }
            }
            await apps_api.patch_namespaced_deployment(deployment_name, namespace, patch)
            return f"Deployment {deployment_name} restart initiated."
        except ApiException as e:
            return f"Failed to restart deployment: {e}"

    async def delete_deployment(self, namespace: str, deployment_name: str, god_mode: bool = False, context: str = None) -> str:
        self._check_permission(god_mode, "DELETE")
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            apps_api = self._get_api("AppsV1Api", ctx)
            if not apps_api:
                return "No Kubeconfig loaded. Cannot delete deployment."
            await apps_api.delete_namespaced_deployment(deployment_name, namespace)
            return f"Deployment {deployment_name} deleted successfully."
        except ApiException as e:
            return f"Failed to delete deployment: {e}"

    async def list_configmaps(self, namespace: str, context: str = None) -> List[Dict[str, Any]]:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return []
            configmaps = await core_api.list_namespaced_config_map(namespace)
            return [
                {
                    "name": cm.metadata.name,
                    "data_count": len(cm.data) if cm.data else 0,
                    "namespace": namespace
                }
                for cm in configmaps.items
            ]
        except ApiException as e:
            logger.error(f"Failed to list configmaps: {e}")
            return []

    async def get_configmap(self, namespace: str, name: str, context: str = None) -> Dict[str, Any]:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return {}
            cm = await core_api.read_namespaced_config_map(name, namespace)
            return {
                "name": cm.metadata.name,
                "namespace": cm.metadata.namespace,
                "data": cm.data or {}
            }
        except ApiException as e:
            logger.error(f"Failed to get configmap {name}: {e}")
            raise e

    async def patch_configmap(self, namespace: str, name: str, data: Dict[str, str], god_mode: bool = False, context: str = None) -> str:
        self._check_permission(god_mode, "MODIFY")
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return "No Kubeconfig loaded. Cannot patch configmap."

            patch = {"data": data}
            await core_api.patch_namespaced_config_map(name, namespace, patch)
            return f"Successfully patched ConfigMap {name}."
        except ApiException as e:
            raise Exception(f"Failed to patch configmap {name}: {e}")

    async def list_secrets(self, namespace: str, context: str = None) -> List[Dict[str, Any]]:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return []
            secrets = await core_api.list_namespaced_secret(namespace)
            return [
                {
                    "name": s.metadata.name,
                    "type": s.type,
                    "namespace": namespace
                }
                for s in secrets.items
            ]
        except ApiException as e:
            logger.error(f"Failed to list secrets: {e}")
            return []

    async def search_pods(self, query: str, context: str = None) -> List[Dict[str, Any]]:
        query = query.lower()
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            logger.info(f"Searching pods with query='{query}' in context='{ctx}'")
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                logger.error("CoreV1Api not available for search")
                return []

            # Natural Language Pre-processing
            stop_words = {"check", "logs", "log", "the", "a", "an", "for", "please", "find", "show", "what", "are", "which"}
            failure_words = {"crash", "crashing", "fail", "failing", "failed", "error", "errors", "issue", "issues", "broken"}

            keywords = [w for w in query.split() if w not in stop_words and len(w) > 2]

            if not keywords:
                keywords = query.split()

            is_failure_search = any(k in failure_words for k in keywords)
            logger.info(f"Search Keywords: {keywords}, Failure Search: {is_failure_search}")

            all_pods = await core_api.list_pod_for_all_namespaces()
            logger.info(f"Total pods found in cluster: {len(all_pods.items)}")

            results = []

            for pod in all_pods.items:
                pod_name = pod.metadata.name.lower()
                status = pod.status.phase

                is_failing = False
                if status in ["Failed", "Unknown"]:
                    is_failing = True
                if pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        if cs.state.waiting and cs.state.waiting.reason in ["CrashLoopBackOff", "ErrImagePull", "ImagePullBackOff", "CreateContainerConfigError", "CreateContainerError"]:
                            is_failing = True
                        if cs.state.terminated and cs.state.terminated.exit_code != 0:
                            is_failing = True

                match = False
                if any(k in pod_name for k in keywords):
                    match = True
                if is_failure_search and is_failing:
                    match = True

                if match:
                    # Provide a more descriptive status for frontend if it's failing
                    display_status = status
                    if is_failing and pod.status.container_statuses:
                        for cs in pod.status.container_statuses:
                            if cs.state.waiting and cs.state.waiting.reason:
                                display_status = cs.state.waiting.reason
                                break

                    results.append({
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "status": display_status,
                        "ip": pod.status.pod_ip
                    })

            logger.info(f"Matched {len(results)} pods")
            return results[:50]
        except ApiException as e:
            logger.error(f"Failed to search pods: {e}")
            return []

    # --- Actions (God Mode) ---
    async def _scale_deployment(self, namespace: str, deployment_name: str, replicas: int, god_mode: bool = False, context: str = None) -> str:
        self._check_permission(god_mode, "MODIFY")
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            apps_api = self._get_api("AppsV1Api", ctx)
            if not apps_api:
                return "No Kubeconfig loaded. Cannot scale deployment."

            # Patch the deployment
            body = {"spec": {"replicas": replicas}}
            await apps_api.patch_namespaced_deployment_scale(
                name=deployment_name,
                namespace=namespace,
                body=body
            )
            return f"Successfully scaled {deployment_name} to {replicas} replicas."
        except ApiException as e:
            raise Exception(f"Failed to scale deployment: {e}")

    async def create_namespace(self, name: str, context: str = None) -> str:
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return "No Kubeconfig loaded. Cannot create namespace."
            ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=name))
            await core_api.create_namespace(body=ns)
            return f"Namespace {name} created."
        except ApiException as e:
            if e.status == 409:
                return f"Namespace {name} already exists."
            raise Exception(f"Failed to create namespace: {e}")

    async def delete_namespace(self, name: str, god_mode: bool = False, context: str = None) -> str:
        self._check_permission(god_mode, "DELETE")
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return "No Kubeconfig loaded. Cannot delete namespace."
            await core_api.delete_namespace(name)
            return f"Namespace {name} deletion initiated."
        except ApiException as e:
            raise Exception(f"Failed to delete namespace: {e}")

    async def get_cluster_health(self, context: str = None) -> str:
        """
        Generates a health report of the cluster.
        """
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            if not core_api:
                return "No Kubeconfig loaded. Please upload a kubeconfig file or mount it to /root/.kube/config."

            # 1. Check Nodes
            nodes_response = await core_api.list_node()
            nodes = nodes_response.items
            total_nodes = len(nodes)
            ready_nodes = 0
            node_report = []

            for node in nodes:
                name = node.metadata.name
                conditions = node.status.conditions
                is_ready = False
                for c in conditions:
                    if c.type == "Ready" and c.status == "True":
                        is_ready = True
                        break

                if is_ready:
                    ready_nodes += 1
                else:
                    node_report.append(f"- Warning: Node {name} is NotReady")

            # 2. Check All Pods Health
            all_pods_response = await core_api.list_pod_for_all_namespaces()
            system_pods = all_pods_response.items
            unhealthy_pods = []
            for pod in system_pods:
                phase = pod.status.phase
                is_unhealthy = False

                if phase not in ["Running", "Succeeded"]:
                    is_unhealthy = True

                if pod.status.container_statuses:
                     for cs in pod.status.container_statuses:
                         if cs.state.waiting and cs.state.waiting.reason in ["CrashLoopBackOff", "ErrImagePull", "ImagePullBackOff", "CreateContainerConfigError", "CreateContainerError"]:
                             is_unhealthy = True
                         if cs.state.terminated and cs.state.terminated.exit_code != 0:
                             is_unhealthy = True

                if is_unhealthy:
                    ns = pod.metadata.namespace
                    unhealthy_pods.append(f"- {ns}/{pod.metadata.name} ({phase})")

            status = "HEALTHY" if ready_nodes == total_nodes and not unhealthy_pods else "DEGRADED"

            report = f"""
# Cluster Health Report
**Status**: {status}

## Nodes
- Total: {total_nodes}
- Ready: {ready_nodes}
{chr(10).join(node_report)}

## Cluster Workloads (All Namespaces)
- Unhealthy Pods: {len(unhealthy_pods)}
{chr(10).join(unhealthy_pods)}
            """
            return report.strip()

        except ApiException as e:
            return f"Failed to check cluster health: {e}"

    async def create_deployment_simple(self, namespace: str, name: str, image: str, replicas: int, god_mode: bool = False, context: str = None) -> str:
        self._check_permission(god_mode, "MODIFY")
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            core_api = self._get_api("CoreV1Api", ctx)
            apps_api = self._get_api("AppsV1Api", ctx)
            if not core_api or not apps_api:
                return "No Kubeconfig loaded. Cannot create deployment."

            # 1. Ensure namespace exists
            try:
                await core_api.read_namespace(namespace)
            except ApiException as e:
                if e.status == 404:
                    # Namespace not found, create it
                    logger.info(f"Namespace {namespace} not found. Creating it.")
                    await self.create_namespace(namespace, context=context)
                else:
                    raise e

            # 2. Create Deployment
            deployment = client.V1Deployment(
                api_version="apps/v1",
                kind="Deployment",
                metadata=client.V1ObjectMeta(name=name),
                spec=client.V1DeploymentSpec(
                    replicas=replicas,
                    selector=client.V1LabelSelector(match_labels={"app": name}),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(labels={"app": name}),
                        spec=client.V1PodSpec(
                            containers=[
                                client.V1Container(
                                    name=name,
                                    image=image,
                                    ports=[client.V1ContainerPort(container_port=80)]
                                )
                            ]
                        )
                    )
                )
            )
            await apps_api.create_namespaced_deployment(namespace=namespace, body=deployment)
            return f"Successfully created deployment {name} with image {image} in {namespace}."
        except ApiException as e:
            raise Exception(f"Failed to create deployment: {e}")

    async def find_deployments_by_name(self, name: str, context: str = None) -> List[Dict[str, Any]]:
        """
        Search for deployments with a specific name across ALL namespaces.
        Returns a list of match details.
        """
        matches = []
        try:
            ctx = context or self.default_context
            await self._ensure_context_loaded(ctx)
            apps_api = self._get_api("AppsV1Api", ctx)
            if not apps_api:
                return []

            # List all deployments across all namespaces
            deployments = await apps_api.list_deployment_for_all_namespaces(
                field_selector=f"metadata.name={name}"
            )
            for d in deployments.items:
                matches.append({
                    "namespace": d.metadata.namespace,
                    "name": d.metadata.name,
                    "replicas": d.spec.replicas,
                    "images": [c.image for c in d.spec.template.spec.containers]
                })
            return matches
        except ApiException as e:
             logger.error(f"Failed to find deployments: {e}")
             return []

    async def restart_pod(self, namespace: str, pod_name: str, context: Optional[str] = None) -> str:
        """Delete a pod so its controller (Deployment/StatefulSet) recreates it."""
        ctx = context or self.default_context
        await self._ensure_context_loaded(ctx)
        core = self._get_api("CoreV1Api", ctx)
        if self.mock_mode or not core:
            logger.info(f"[MOCK] restart_pod {namespace}/{pod_name}")
            return f"MOCK: pod {pod_name} restarted"
        try:
            await core.delete_namespaced_pod(name=pod_name, namespace=namespace)
            return f"Pod {namespace}/{pod_name} deleted — controller will recreate it"
        except ApiException as e:
            logger.error(f"restart_pod failed: {e}")
            return f"Error restarting pod: {e.reason}"

k8s_service = K8sService()
