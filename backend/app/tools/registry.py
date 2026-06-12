import inspect
from typing import Any, Dict, List
from . import k8s_tools
from . import minion_tools
from . import middleware_tools
from . import mssql_tools
from . import rabbitmq_tools
from . import redis_tools
from . import postgres_tools
from . import couchdb_tools
from . import mysql_tools
from . import mongodb_tools


async def _search_knowledge_base(query: str) -> Dict[str, Any]:
    from app.services.rag_service import rag_service
    result = await rag_service.retrieve(query, collection_name="knowledge_base")
    return {"success": True, "data": result, "error": None, "source": "rag"}


async def _search_past_incidents(query: str) -> Dict[str, Any]:
    from app.services.rag_service import rag_service
    result = await rag_service.retrieve(query, collection_name="incidents")
    return {"success": True, "data": result, "error": None, "source": "rag"}



async def _get_azure_cost_recommendations() -> Dict[str, Any]:
    """AI-callable tool to fetch Azure Advisor cost recommendations."""
    try:
        from app.services.azure_service import get_advisor_recommendations, get_connection
        from app.models.integration import AzureFeatureConfig
        from app.core.db import AsyncSessionLocal

        conn = await get_connection()
        if not conn or not conn.is_connected:
            return {"success": False, "data": None, "error": "Azure not connected", "source": "azure"}

        async with AsyncSessionLocal() as session:
            feature = await session.get(AzureFeatureConfig, "ai_cost_recommendations")
            if not feature or not feature.enabled:
                return {"success": False, "data": None, "error": "AI Cost Recommendations feature is not enabled", "source": "azure"}

        from app.models.audit import AuditLog
        from datetime import datetime, timezone
        audit = AuditLog(
            actor="system",
            action="AZURE_RECOMMENDATIONS_FETCH",
            resource="azure/recommendations",
            result="SUCCESS",
            mode="NORMAL",
            source="AZURE",
            details="triggered_by=ai_tool",
        )
        async with AsyncSessionLocal() as session:
            session.add(audit)
            await session.commit()

        data = await get_advisor_recommendations()
        return {"success": True, "data": data, "error": None, "source": "azure"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "azure"}


from app.services.registry_service import registry_service as _registry_svc


async def _fix_image_pull_tool(pod_name: str, namespace: str) -> Dict[str, Any]:
    """
    Atomic ImagePullBackOff repair: describe pod → find owner Deployment →
    search registry for valid tags → build apply_manifest payload.
    Returns a pending_confirmation manifest ready for apply_manifest, or
    a clear error if no valid tag was found.
    """
    try:
        # 1. Describe the pod to get the broken image and owner
        pod_info = await k8s_tools.describe_pod(pod_name, namespace)
        if not pod_info.get("success"):
            return {"success": False, "error": f"Could not describe pod: {pod_info.get('error')}", "source": "fix_image_pull"}

        pod_data = pod_info.get("data", {})
        containers = pod_data.get("containers", [])
        if not containers:
            return {"success": False, "error": "Pod has no containers.", "source": "fix_image_pull"}

        broken_image = containers[0].get("image", "")
        if not broken_image:
            return {"success": False, "error": "Could not determine broken image.", "source": "fix_image_pull"}

        owner_refs = pod_data.get("owner_references", [])
        deployment_name = None
        for ref in owner_refs:
            if ref.get("kind") == "ReplicaSet":
                # Strip the hash suffix from ReplicaSet name to get Deployment name
                rs_name = ref.get("name", "")
                parts = rs_name.rsplit("-", 1)
                deployment_name = parts[0] if len(parts) == 2 else rs_name
                break
            if ref.get("kind") == "Deployment":
                deployment_name = ref.get("name")
                break

        # 2. Search registries for a valid tag
        registry_result = await _search_container_image_tool(broken_image)
        if not registry_result.get("success"):
            # Registry Lookup unavailable or returned error — return a clear action for the agent
            return {
                "success": False,
                "error": registry_result.get("error", "Registry search failed."),
                "broken_image": broken_image,
                "deployment": deployment_name,
                "namespace": namespace,
                "action_required": (
                    f"Registry Lookup could not find a replacement. "
                    f"Ask the user: 'What is the correct image tag for {broken_image}?' "
                    f"Then call apply_manifest to patch deployment/{deployment_name} in {namespace}."
                ),
                "source": "fix_image_pull",
            }

        matches = registry_result.get("data", {}).get("matches", [])
        if not matches or not matches[0].get("tags"):
            return {
                "success": False,
                "error": f"No available tags found for {broken_image} in any configured registry.",
                "broken_image": broken_image,
                "deployment": deployment_name,
                "namespace": namespace,
                "action_required": (
                    f"Ask the user: 'What is the correct image tag for {broken_image}?' "
                    f"Then call apply_manifest to patch deployment/{deployment_name} in {namespace}."
                ),
                "source": "fix_image_pull",
            }

        # 3. Pick the best tag — prefer stable/versioned over platform-specific variants
        import re as _re
        best_match = matches[0]
        raw_tags = best_match.get("tags", [])

        def _tag_score(tag: str) -> int:
            t = tag.lower()
            if t == "stable": return 100
            if t == "latest": return 90
            if _re.match(r"^\d+\.\d+\.\d+$", t): return 80   # 1.27.0
            if _re.match(r"^\d+\.\d+$", t): return 75        # 1.27
            if _re.match(r"^\d+$", t): return 70             # 7
            if t == "alpine": return 60
            if "alpine" in t and _re.match(r"^[\d.]+$", t.replace("alpine", "").strip("-")): return 50
            return 10

        best_tag = sorted(raw_tags, key=_tag_score, reverse=True)[0] if raw_tags else "latest"
        # Reconstruct full image ref: use registry from match if different from broken
        registry_host = best_match.get("registry", "")
        image_path = best_match.get("image", broken_image.split(":")[0].split("@")[0])
        if registry_host and registry_host not in ("hub.docker.com", "index.docker.io") and not image_path.startswith(registry_host):
            fixed_image = f"{registry_host}/{image_path}:{best_tag}"
        elif ":" in image_path or "@" in image_path:
            fixed_image = f"{image_path.split(':')[0].split('@')[0]}:{best_tag}"
        else:
            fixed_image = f"{image_path}:{best_tag}"

        # 4. Build the apply_manifest payload
        if deployment_name:
            manifest = (
                f"apiVersion: apps/v1\n"
                f"kind: Deployment\n"
                f"metadata:\n"
                f"  name: {deployment_name}\n"
                f"  namespace: {namespace}\n"
                f"spec:\n"
                f"  template:\n"
                f"    spec:\n"
                f"      containers:\n"
                f"      - name: {containers[0].get('name', 'app')}\n"
                f"        image: {fixed_image}\n"
            )
            return {
                "success": True,
                "data": {
                    "broken_image": broken_image,
                    "fixed_image": fixed_image,
                    "deployment": deployment_name,
                    "namespace": namespace,
                    "all_available_tags": best_match.get("tags", []),
                    "manifest": manifest,
                    "next_step": (
                        f"Call apply_manifest with the manifest above to patch {deployment_name} "
                        f"from {broken_image} → {fixed_image}."
                    ),
                },
                "error": None,
                "source": "fix_image_pull",
            }
        else:
            return {
                "success": True,
                "data": {
                    "broken_image": broken_image,
                    "fixed_image": fixed_image,
                    "all_available_tags": best_match.get("tags", []),
                    "next_step": (
                        f"Standalone pod (no Deployment owner). "
                        f"Call apply_manifest to recreate the pod with image {fixed_image}."
                    ),
                },
                "error": None,
                "source": "fix_image_pull",
            }
    except Exception as e:
        return {"success": False, "error": str(e), "source": "fix_image_pull"}


async def _search_container_image_tool(image_name: str) -> Dict[str, Any]:
    # Allow if: registry lookup is enabled OR private registries are configured.
    # The is_enabled() setting gates public registry lookups in the UI, but the AI
    # should always be able to query private registries the user has explicitly connected.
    has_private = bool(await _registry_svc._get_user_registries())
    if not await _registry_svc.is_enabled() and not has_private:
        return {
            "success": False,
            "data": None,
            "error": (
                "Registry Lookup is disabled and no private registries are configured. "
                "Enable Registry Lookup in Settings, or add a private registry in Integrations → Container Registries."
            ),
            "source": "registry",
        }
    try:
        matches = await _registry_svc.search_image(image_name)
        if not matches:
            return {
                "success": True,
                "data": {
                    "matches": [],
                    "message": (
                        f"No results found for '{image_name}' in any configured registry. "
                        f"The image or tag may not exist. "
                        f"If you know the exact tag, use registry_check_image(registry_name, image) to verify directly."
                    ),
                },
                "error": None,
                "source": "registry",
            }
        return {"success": True, "data": {"matches": matches}, "error": None, "source": "registry"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "registry"}


async def _fetch_url_tool(url: str) -> Dict[str, Any]:
    if not await _registry_svc.is_enabled():
        return {
            "success": False,
            "data": None,
            "error": "Registry Lookup is disabled. Enable it in Settings → Registry Lookup.",
            "source": "registry",
        }
    try:
        content = await _registry_svc.fetch_url(url)
        return {
            "success": True,
            "data": {"content": content, "url": url},
            "error": None,
            "source": "registry",
        }
    except ValueError as e:
        return {"success": False, "data": None, "error": str(e), "source": "registry"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "registry"}


async def _check_registry_image_tool(registry_name: str, image: str) -> Dict[str, Any]:
    """Check if a specific image:tag exists in a named connected registry."""
    reg = await _registry_svc.find_registry_by_name_or_url(registry_name)
    if not reg:
        all_regs = await _registry_svc._get_user_registries()
        names = [r.name for r in all_regs]
        return {
            "success": False,
            "data": None,
            "error": (
                f"Registry '{registry_name}' not found. "
                f"Connected registries: {names or ['none configured']}. "
                "Add it in Integrations → Container Registries."
            ),
            "source": "registry",
        }
    try:
        result = await _registry_svc.check_image(reg.id, image)
        return {"success": True, "data": result, "error": None, "source": "registry"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "registry"}


async def _list_registry_catalog_tool(registry_name: str) -> Dict[str, Any]:
    """List all repositories (image names) available in a named connected registry."""
    reg = await _registry_svc.find_registry_by_name_or_url(registry_name)
    if not reg:
        all_regs = await _registry_svc._get_user_registries()
        names = [r.name for r in all_regs]
        return {
            "success": False,
            "data": None,
            "error": (
                f"Registry '{registry_name}' not found. "
                f"Connected registries: {names or ['none configured']}. "
                "Add it in Integrations → Container Registries."
            ),
            "source": "registry",
        }
    try:
        repos, message = await _registry_svc.list_catalog(reg.id)
        return {
            "success": True,
            "data": {"registry": reg.url, "repositories": repos, "count": len(repos), "message": message},
            "error": None,
            "source": "registry",
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "registry"}


RAG_TOOL_REGISTRY: Dict[str, Any] = {
    "search_knowledge_base": {
        "function": _search_knowledge_base,
        "description": "Search the knowledge base (runbooks, uploaded docs, external sources) for relevant information about a topic.",
        "inputs": ["query"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "search_past_incidents": {
        "function": _search_past_incidents,
        "description": "Search past incident resolutions from previous chat sessions for similar problems and their solutions.",
        "inputs": ["query"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
}

TOOL_REGISTRY = {
    "search_topology": {
        "function": k8s_tools.search_topology_tool,
        "description": (
            "Search the pre-built cluster topology graph for resources matching the query. "
            "Returns a subgraph showing the matched resource and all connected resources "
            "(2 hops: what owns it, what it owns, what it mounts, what selects it). "
            "Use before investigating a resource — faster than calling 5 separate tools. "
            "query: resource name, partial name, or kind (e.g. 'rabbitmq', 'payments-api', 'CrashLoopBackOff'). "
            "context: optional, omit to use default cluster."
        ),
        "inputs": ["query", "context"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_blast_radius": {
        "function": k8s_tools.get_blast_radius_tool,
        "description": (
            "Return all downstream resources that depend on a given resource. "
            "Use when user asks 'what breaks if X goes down?' or before deleting/patching "
            "a shared resource (Service, ConfigMap, Secret, PVC). "
            "kind: 'Service' | 'Deployment' | 'ConfigMap' | 'Secret' | 'PVC' | 'StatefulSet'. "
            "name: exact resource name. namespace: resource namespace."
        ),
        "inputs": ["kind", "name", "namespace", "context"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "diagnose_pod": {
        "function": k8s_tools.diagnose_pod_tool,
        "description": (
            "Run a full 10-category diagnostic sweep on a pod. "
            "Checks container state, probes, networking (port mismatch, selector, ingress), "
            "config refs (missing configmap/secret keys), storage (PVC pending/stuck), "
            "resources (OOM risk, quota, node capacity), scheduling (node selector, taints), "
            "RBAC (missing SA, no binding), workload health (deployment rollout, HPA), "
            "and security context (PSA enforcement). "
            "Use this FIRST for any vague troubleshooting query before calling targeted tools. "
            "pod_name: exact pod name. namespace: optional, omit to search all namespaces."
        ),
        "inputs": ["pod_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "diagnose_service": {
        "function": k8s_tools.diagnose_service_tool,
        "description": (
            "Run a full diagnostic sweep starting from a service name. "
            "Resolves pods via label selector, runs diagnose_pod on each (up to 3 pods), "
            "then checks service-level issues: endpoint ready count, ingress backend port alignment. "
            "Use when the user mentions a service name but not a specific pod. "
            "service_name: exact service name. namespace: optional."
        ),
        "inputs": ["service_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_cluster_health": {
        "function": k8s_tools.get_cluster_health,
        "description": "Fetch a high-level health report of all nodes and pods in the cluster.",
        "inputs": [],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "search_pods": {
        "function": k8s_tools.search_pods,
        "description": "Search for pods by keyword or status (e.g., 'crash', 'fail', 'error'). Returns top 50 matches. Use this if you need to find broken pods.",
        "inputs": ["keyword", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_pod_status": {
        "function": k8s_tools.get_pod_status,
        "description": "Get full status and container states for a pod. namespace is optional — omit to auto-discover across all namespaces.",
        "inputs": ["pod_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_pod_logs": {
        "function": k8s_tools.get_pod_logs,
        "description": "Get logs from a pod container. namespace is optional — omit to auto-discover across all namespaces. Options: container_name, previous=True/False, tail_lines",
        "inputs": ["pod_name", "namespace", "container_name", "previous", "tail_lines"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_pod_events": {
        "function": k8s_tools.get_pod_events,
        "description": "Get all events for a specific pod. namespace is optional — omit to auto-discover across all namespaces.",
        "inputs": ["pod_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_logs": {
        "function": k8s_tools.get_logs,
        "description": "Get logs from a pod with automatic namespace discovery. namespace is optional — searches all namespaces when omitted.",
        "inputs": ["pod_name", "namespace", "container_name", "previous", "tail_lines"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_events": {
        "function": k8s_tools.get_events,
        "description": "List events across all namespaces or a specific one. All parameters optional: namespace (omit for all), resource_name, resource_kind (e.g. Pod, Deployment).",
        "inputs": ["namespace", "resource_name", "resource_kind"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_deployment_status": {
        "function": k8s_tools.get_deployment_status,
        "description": "Get deployment rollout status, replica counts, and conditions",
        "inputs": ["deployment_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_node_status": {
        "function": k8s_tools.get_node_status,
        "description": "Get status and conditions for one or all nodes (node_name is optional)",
        "inputs": ["node_name"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_node_capacity": {
        "function": k8s_tools.get_node_capacity,
        "description": "Get resource usage vs allocatable capacity per node",
        "inputs": ["node_name"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_replicasets": {
        "function": k8s_tools.get_replicasets,
        "description": "List replicasets for a deployment to inspect rollout history",
        "inputs": ["deployment_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "describe_pod_scheduling": {
        "function": k8s_tools.describe_pod_scheduling,
        "description": "Get scheduling constraints (node selectors, affinity, limits). Must provide namespace and one of pod_name/deployment_name",
        "inputs": ["namespace", "pod_name", "deployment_name"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_pvc_status": {
        "function": k8s_tools.get_pvc_status,
        "description": "Get PVC binding status and associated PV details",
        "inputs": ["pvc_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_deployment_rollout_history": {
        "function": k8s_tools.get_deployment_rollout_history,
        "description": "Get rollout revision history for a deployment",
        "inputs": ["deployment_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "list_pods_on_node": {
        "function": k8s_tools.list_pods_on_node,
        "description": "List all pods on a specific node. namespace is optional — omit to list pods across all namespaces on that node.",
        "inputs": ["node_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_secret_exists": {
        "function": k8s_tools.get_secret_exists,
        "description": "Check if a secret exists in a namespace (name and type only, never values)",
        "inputs": ["secret_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "list_secrets": {
        "function": k8s_tools.list_secrets,
        "description": "List secrets in a namespace — returns names and key counts only, never values. Use to discover what secrets exist and which keys they contain.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_secret_keys": {
        "function": k8s_tools.get_secret_keys,
        "description": "Get the key names stored in a Kubernetes secret WITHOUT their values. Use to identify which key holds a credential (e.g. 'password', 'RABBITMQ_PASS') before proposing a patch.",
        "inputs": ["secret_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "patch_secret": {
        "function": k8s_tools.patch_secret,
        "description": "Update a single key's value in a Kubernetes secret. Use to fix incorrect credentials (e.g. wrong RabbitMQ password). Requires God Mode confirmation. After patching, restart affected pods.",
        "inputs": ["secret_name", "namespace", "key", "value", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "search_configmaps": {
        "function": k8s_tools.search_configmaps,
        "description": "Search for configmaps by keyword in their name across all (or one) namespace. Use this when you don't know the exact configmap name — returns matching names and their keys. namespace is optional.",
        "inputs": ["keyword", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_configmap": {
        "function": k8s_tools.get_configmap,
        "description": "Get configmap keys and values by exact name. namespace is optional — omit to search all namespaces automatically.",
        "inputs": ["configmap_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False
    },
    "get_azure_cost_recommendations": {
        "function": _get_azure_cost_recommendations,
        "description": (
            "Fetch Azure Advisor cost optimization recommendations for the connected Azure subscription. "
            "Use when the user asks about Azure costs, cost savings, underutilized resources, or 'what can I optimize?' "
            "Correlate results with K8s resource utilization for richer advice. "
            "Only works if Azure is connected and the AI Cost Recommendations feature is enabled."
        ),
        "inputs": [],
        "operation_type": "read",
        "requires_confirmation": False,
    },

    "get_service": {
        "function": k8s_tools.get_service,
        "description": "Get a Kubernetes Service's ports (with names and protocols), selector, ClusterIP, and type. Use to check what port a service actually exposes. namespace is optional — omit to search all namespaces.",
        "inputs": ["service_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_services": {
        "function": k8s_tools.list_services,
        "description": "List all services in a namespace or across all namespaces. Use to discover what services exist alongside a failing pod.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_endpoints": {
        "function": k8s_tools.get_endpoints,
        "description": "Get the actual pod IPs and ports backing a service. Use to check if a service has any live backends or if endpoints are empty (nothing is behind it).",
        "inputs": ["service_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_ingress": {
        "function": k8s_tools.get_ingress,
        "description": "Get an Ingress resource's routing rules, hosts, backends, and TLS config. namespace is optional.",
        "inputs": ["ingress_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_ingresses": {
        "function": k8s_tools.list_ingresses,
        "description": "List all ingresses in a namespace or across all namespaces.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_network_policies": {
        "function": k8s_tools.get_network_policies,
        "description": "Get all network policies in a namespace — shows pod selectors, ingress/egress rules, and allowed ports/CIDRs. Use when traffic between pods is unexpectedly blocked.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },

    "list_configmaps": {
        "function": k8s_tools.list_configmaps,
        "description": "List all configmaps in a namespace with their key names. Use for overview of what config exists before drilling into specific configmaps.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "search_configmap_values": {
        "function": k8s_tools.search_configmap_values,
        "description": "Search for a keyword in configmap VALUES across a namespace or all namespaces. Use when you know a specific value (port number, hostname, URL) and need to find which configmap contains it. namespace is optional.",
        "inputs": ["keyword", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_workload_config": {
        "function": k8s_tools.get_workload_config,
        "description": "Get all configmaps, secrets, and environment variables mounted or referenced by a deployment's pod spec. Use to trace exactly what config a failing workload is using — shows volumes, envFrom, env valueFrom, and literal env vars per container.",
        "inputs": ["deployment_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },

    "get_statefulset_status": {
        "function": k8s_tools.get_statefulset_status,
        "description": "Get a StatefulSet's replica counts, conditions, update strategy, and volume claim templates.",
        "inputs": ["statefulset_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_statefulsets": {
        "function": k8s_tools.list_statefulsets,
        "description": "List all statefulsets in a namespace or across all namespaces. namespace is optional.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_daemonset_status": {
        "function": k8s_tools.get_daemonset_status,
        "description": "Get a DaemonSet's desired vs ready counts, node selector, and update strategy.",
        "inputs": ["daemonset_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_daemonsets": {
        "function": k8s_tools.list_daemonsets,
        "description": "List all daemonsets in a namespace or across all namespaces. namespace is optional.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_job_status": {
        "function": k8s_tools.get_job_status,
        "description": "Get a Job's completion status, conditions, active/succeeded/failed counts, duration, and backoff limit.",
        "inputs": ["job_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_jobs": {
        "function": k8s_tools.list_jobs,
        "description": "List all jobs in a namespace or across all namespaces with status. namespace is optional.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_cronjob": {
        "function": k8s_tools.get_cronjob,
        "description": "Get a CronJob's schedule, last run time, active jobs, suspend status, and concurrency policy.",
        "inputs": ["cronjob_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_cronjobs": {
        "function": k8s_tools.list_cronjobs,
        "description": "List all cronjobs in a namespace or across all namespaces. namespace is optional.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },

    "get_hpa": {
        "function": k8s_tools.get_hpa,
        "description": "Get an HPA's target ref, min/max replicas, current/desired replicas, metrics (current vs target), and conditions.",
        "inputs": ["hpa_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_hpa": {
        "function": k8s_tools.list_hpa,
        "description": "List all HPAs in a namespace or across all namespaces. namespace is optional.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_role_bindings": {
        "function": k8s_tools.get_role_bindings,
        "description": "Get all role bindings in a namespace — shows which roles are bound to which users, groups, and service accounts.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_service_account": {
        "function": k8s_tools.get_service_account,
        "description": "Get a service account's annotations, image pull secrets, and mounted secrets. Use when investigating image pull failures or permission issues.",
        "inputs": ["name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_resource_quota": {
        "function": k8s_tools.get_resource_quota,
        "description": "Get resource quotas in a namespace — hard limits vs current usage for CPU, memory, pods, etc. Use when pods won't schedule due to quota.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_limit_range": {
        "function": k8s_tools.get_limit_range,
        "description": "Get limit ranges in a namespace — default limits and requests applied to new pods. Use when investigating OOMKilled or resource constraint issues.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_namespaces": {
        "function": k8s_tools.list_namespaces,
        "description": "List all namespaces with status and labels. Use for cluster-wide overview or to discover namespaces.",
        "inputs": [],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_pdb": {
        "function": k8s_tools.get_pdb,
        "description": "Get pod disruption budgets in a namespace — min available, max unavailable, current healthy count. Use when rollouts or drains are blocked.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "describe_pod": {
        "function": k8s_tools.describe_pod,
        "description": "Get full describe output for a pod — shows events, conditions, container specs, mounts, resource limits. Equivalent to kubectl describe pod.",
        "inputs": ["pod_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_deployments": {
        "function": k8s_tools.list_deployments,
        "description": "List all Deployments in a namespace with replica counts. Omit namespace to search all namespaces.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_resource_yaml": {
        "function": k8s_tools.get_resource_yaml,
        "description": "Get the full YAML manifest of any Kubernetes resource (deployment, service, configmap, secret, etc). Use to inspect exact config or diff against expected state.",
        "inputs": ["kind", "name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "exec_pod": {
        "function": k8s_tools.exec_pod,
        "description": "Execute a shell command inside a running pod container. Use for live diagnostics: 'nslookup rabbitmq', 'curl http://svc:port/health', 'env | grep PASSWORD', 'cat /etc/config/app.yaml'. Do not use for write operations.",
        "inputs": ["pod_name", "namespace", "command", "container_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },

    "update_configmap": {
        "function": k8s_tools.update_configmap,
        "description": "Update a single key-value pair in a ConfigMap. Use when user asks to change a config value (e.g. port, flag, setting). Action Input MUST be JSON: {\"configmap_name\": \"<name>\", \"namespace\": \"<ns>\", \"key\": \"<key>\", \"value\": \"<value>\", \"reason\": \"<why>\"}",
        "inputs": ["configmap_name", "namespace", "key", "value", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium"
    },

    # PROVISIONING TOOLS
    "create_namespace": {
        "function": k8s_tools.create_namespace,
        "description": 'Create a new Kubernetes namespace. Action Input MUST be JSON: {"namespace": "<name>", "reason": "<why>"}',
        "inputs": ["namespace", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "low"
    },
    "deploy_application": {
        "function": k8s_tools.deploy_application,
        "description": 'Deploy an app (Deployment + Service). Action Input MUST be JSON: {"name": "<app-name>", "image": "<image:tag>", "namespace": "<ns>", "reason": "<why>", "replicas": 1, "port": 6379}. Use port 6379 for Redis, 5432 for Postgres, 80 for HTTP apps.',
        "inputs": ["name", "image", "namespace", "reason", "replicas", "port"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium"
    },

    # WRITE TOOLS
    "delete_deployment": {
        "function": k8s_tools.delete_deployment,
        "description": "Permanently delete a Deployment and all its pods. Use when user explicitly asks to remove, delete, or uninstall a deployment. This is irreversible.",
        "inputs": ["deployment_name", "namespace", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high"
    },
    "delete_namespace": {
        "function": k8s_tools.delete_namespace,
        "description": "Permanently delete an entire namespace and ALL resources inside it (pods, deployments, services, secrets, PVCs). Extremely destructive and irreversible.",
        "inputs": ["namespace", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high"
    },
    "restart_pod": {
        "function": k8s_tools.restart_pod,
        "description": (
            "Delete a pod so its controller (Deployment/DaemonSet/StatefulSet) recreates it. "
            "ONLY use for CrashLoopBackOff or OOMKill where a fresh start helps. "
            "NEVER use for ImagePullBackOff or ErrImagePull — restarting changes nothing because "
            "the pod will attempt the same broken image again (or disappear permanently if the pod "
            "has no owner/controller). For image issues, patch the image via apply_manifest instead."
        ),
        "inputs": ["pod_name", "namespace", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "low"
    },
    "rollback_deployment": {
        "function": k8s_tools.rollback_deployment,
        "description": "Roll back a deployment to a previous revision",
        "inputs": ["deployment_name", "namespace", "target_revision", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium"
    },
    "cordon_node": {
        "function": k8s_tools.cordon_node,
        "description": "Mark a node as unschedulable to prevent new pod placement",
        "inputs": ["node_name", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "low"
    },
    "uncordon_node": {
        "function": k8s_tools.uncordon_node,
        "description": "Mark a node as schedulable again (reverse of cordon). Use after maintenance is complete.",
        "inputs": ["node_name", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "low",
    },
    "drain_node": {
        "function": k8s_tools.drain_node,
        "description": "Evict all pods from a node and cordon it",
        "inputs": ["node_name", "reason", "ignore_daemonsets", "delete_emptydir_data"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high"
    },
    "patch_deployment_resources": {
        "function": k8s_tools.patch_deployment_resources,
        "description": "Update resource requests and limits for a deployment",
        "inputs": ["deployment_name", "namespace", "container_name", "reason", "cpu_request", "memory_request", "cpu_limit", "memory_limit"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium"
    },
    "scale_deployment": {
        "function": k8s_tools.scale_deployment,
        "description": "Scale a deployment to a specific replica count",
        "inputs": ["deployment_name", "namespace", "replicas", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium"
    },
    "get_pod_metrics": {
        "function": k8s_tools.get_pod_metrics,
        "description": "Get actual CPU and memory usage for a specific pod (requires metrics-server). Use when diagnosing OOMKilled or CPU throttling.",
        "inputs": ["pod_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_node_metrics": {
        "function": k8s_tools.get_node_metrics,
        "description": "Get actual CPU and memory usage for a specific node (requires metrics-server). Use when diagnosing node pressure or evictions.",
        "inputs": ["node_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_top_pods": {
        "function": k8s_tools.get_top_pods,
        "description": "List CPU and memory usage for all pods in a namespace. Equivalent to kubectl top pods. Omit namespace for cluster-wide view.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_pvcs": {
        "function": k8s_tools.list_pvcs,
        "description": "List PersistentVolumeClaims in a namespace. Shows phase (Bound/Pending/Lost), capacity, and storage class. Omit namespace for cluster-wide.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_pv": {
        "function": k8s_tools.get_pv,
        "description": "Get details of a PersistentVolume — phase, capacity, reclaim policy, and which PVC it is bound to.",
        "inputs": ["pv_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_pvs": {
        "function": k8s_tools.list_pvs,
        "description": "List all PersistentVolumes in the cluster with their phase, capacity, and bound claims.",
        "inputs": [],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_storage_class": {
        "function": k8s_tools.get_storage_class,
        "description": "Get details of a StorageClass — provisioner, reclaim policy, binding mode, and whether it is the default.",
        "inputs": ["name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "list_storage_classes": {
        "function": k8s_tools.list_storage_classes,
        "description": "List all StorageClasses in the cluster. Use to identify available storage options and the default class.",
        "inputs": [],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "patch_deployment_env": {
        "function": k8s_tools.patch_deployment_env,
        "description": "Update a single environment variable in a deployment container. Use to fix misconfigured credentials, service URLs, or feature flags. Triggers a rolling restart. Requires God Mode.",
        "inputs": ["deployment_name", "namespace", "container_name", "env_var", "value", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "apply_manifest": {
        "function": k8s_tools.apply_manifest,
        "description": "Apply a raw YAML manifest to the cluster (kubectl apply -f). Use to create or update any Kubernetes resource. Requires God Mode.",
        "inputs": ["manifest_yaml", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "get_roles": {
        "function": k8s_tools.get_roles,
        "description": "List RBAC Roles in a namespace with their rules (which resources and verbs are allowed). Use to diagnose permission denied errors.",
        "inputs": ["namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_cluster_roles": {
        "function": k8s_tools.get_cluster_roles,
        "description": "List ClusterRoles in the cluster. Use to understand cluster-wide permissions granted to service accounts or users.",
        "inputs": [],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_cluster_role_bindings": {
        "function": k8s_tools.get_cluster_role_bindings,
        "description": "List ClusterRoleBindings — shows which users, groups, or service accounts have been granted cluster-wide roles.",
        "inputs": [],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "minion_list": {
        "function": minion_tools.minion_list,
        "description": (
            "List all on-premise minion devices registered with DokOps. "
            "Returns hostname, status (active/pending/offline), grains summary, and last_seen. "
            "Use to discover available on-prem hosts before running minion_exec_read."
        ),
        "inputs": [],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "minion_grains": {
        "function": minion_tools.minion_grains,
        "description": (
            "Get full system facts (grains) for an on-premise minion device. "
            "Returns OS, arch, kernel, Docker version, Ansible version, systemctl availability. "
            "minion_id: the device UUID or hostname."
        ),
        "inputs": ["minion_id"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "minion_exec_read": {
        "function": minion_tools.minion_exec_read,
        "description": (
            "Run a read-only diagnostic command on an on-premise minion device. "
            "Allowed commands: docker ps/inspect/logs, systemctl status/list-units, "
            "journalctl, df, free, top -bn1, uptime, ansible --version, ansible-inventory. "
            "minion_id: device UUID. cmd: the shell command to run. "
            "Do NOT use for write operations — use minion_exec_write instead."
        ),
        "inputs": ["minion_id", "cmd", "timeout"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "minion_exec_write": {
        "function": minion_tools.minion_exec_write,
        "description": (
            "Run a write/mutating command on an on-premise minion device. Requires God Mode. "
            "Examples: systemctl restart <svc>, docker pull/stop/rm, ansible-playbook <file>, "
            "bash -c '<command>', apt install <pkg>. "
            "minion_id: device UUID. cmd: exact shell command. reason: why this change is needed."
        ),
        "inputs": ["minion_id", "cmd", "reason"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "list_minion_services": {
        "function": middleware_tools.list_minion_services,
        "description": "List middleware services discovered on a minion (RabbitMQ, Redis, CouchDB, etc). Call this first before running probes to know what is running and what probes are available.",
        "inputs": ["minion_id"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "run_service_probe": {
        "function": middleware_tools.run_service_probe,
        "description": "Run a diagnostic probe for a middleware service on a minion. Available probe names are returned by list_minion_services. Credentials are resolved automatically.",
        "inputs": ["minion_id", "service_type", "probe_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "get_service_logs": {
        "function": middleware_tools.get_service_logs,
        "description": "Fetch recent logs for a middleware service on a minion. Use when you see errors in probe output and need to investigate further.",
        "inputs": ["minion_id", "service_type"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "fix_image_pull": {
        "function": _fix_image_pull_tool,
        "description": (
            "One-shot repair for ImagePullBackOff / ErrImagePull. "
            "Given a pod name and namespace: describes the pod, finds the broken image, searches all "
            "configured registries for a valid replacement tag, and returns a ready-to-apply Deployment "
            "manifest with the corrected image. After calling this, call apply_manifest with the returned "
            "manifest to complete the fix. Use this as the FIRST action whenever a pod has ImagePullBackOff."
        ),
        "inputs": ["pod_name", "namespace"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "registry_search_image": {
        "function": _search_container_image_tool,
        "description": (
            "Search all configured container registries for an image by name and return available tags. "
            "Use when ImagePullBackOff or ErrImagePull is caused by a missing or moved image. "
            "Strips broken SHA digests automatically. Returns matches as [{registry, full_image, tags}]. "
            "NEVER use for general web search — queries OCI registry APIs only."
        ),
        "inputs": ["image_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "fetch_url": {
        "function": _fetch_url_tool,
        "description": (
            "Fetch a URL from a configured registry host or a known safe domain "
            "(hub.docker.com, ghcr.io, quay.io, registry.k8s.io, raw.githubusercontent.com, api.github.com). "
            "Use to read upstream manifests, release notes, or registry tag metadata. "
            "Blocked for any domain not in the allowlist — do NOT use for general web browsing."
        ),
        "inputs": ["url"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "registry_check_image": {
        "function": _check_registry_image_tool,
        "description": (
            "Check whether a specific image (and tag) actually exists in a connected private registry (e.g. ACR, ECR, Harbor). "
            "Use when you need to verify a pod's image reference is valid before or after a deployment, "
            "or when diagnosing ImagePullBackOff on a private registry. "
            "Returns exists=true/false, the full image ref, and the content digest if found. "
            "registry_name is the display name or hostname as configured in Integrations (e.g. 'My ACR' or 'mycompany.azurecr.io'). "
            "image is the image path and tag, e.g. 'myapp:v1.2.3' or 'team/myapp:latest'."
        ),
        "inputs": ["registry_name", "image"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "registry_list_catalog": {
        "function": _list_registry_catalog_tool,
        "description": (
            "List all image repositories available in a connected private registry. "
            "Use to discover what images are stored in ACR/ECR/Harbor, or to audit registry contents. "
            "registry_name is the display name or hostname as configured in Integrations."
        ),
        "inputs": ["registry_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },

    # --- SQL SERVER TOOLS ---
    "mssql_list_databases": {
        "function": mssql_tools.mssql_list_databases,
        "description": "List all user databases on the configured SQL Server — name, state, recovery model, size. Call this first to discover database names before running queries.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_connections": {
        "function": mssql_tools.mssql_connections,
        "description": "Show all active SQL Server sessions — login, host, program, status, database, CPU time, memory, and logical reads per session.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_slow_queries": {
        "function": mssql_tools.mssql_slow_queries,
        "description": "Show queries currently running longer than 5 seconds — session ID, database, wait type, elapsed time, CPU, and query text.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_blocking_chains": {
        "function": mssql_tools.mssql_blocking_chains,
        "description": "Show the full blocking tree — which session is blocking which, with both the blocking and blocked query text and wait time.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_wait_stats": {
        "function": mssql_tools.mssql_wait_stats,
        "description": "Top 20 server-wide wait types by total wait time — identifies whether the bottleneck is IO, locks, CPU, or network. Benign idle waits are excluded.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_database_sizes": {
        "function": mssql_tools.mssql_database_sizes,
        "description": "All databases with data file size (MB), log file size (MB), state, and recovery model.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_index_fragmentation": {
        "function": mssql_tools.mssql_index_fragmentation,
        "description": "Indexes with fragmentation above 10% — shows fragmentation %, page count, and whether to REBUILD or REORGANIZE.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_missing_indexes": {
        "function": mssql_tools.mssql_missing_indexes,
        "description": "Top 20 missing indexes suggested by the SQL Server query optimizer — ranked by estimated impact score with the affected table and columns.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_top_queries_by_cpu": {
        "function": mssql_tools.mssql_top_queries_by_cpu,
        "description": "Top 20 cached query plans ranked by total CPU time — execution count, average CPU, average elapsed time, and query text.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_ag_status": {
        "function": mssql_tools.mssql_ag_status,
        "description": "Always On Availability Group replica health — synchronization state, redo queue size, and log send queue per replica. Returns empty if AG is not configured.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_query": {
        "function": mssql_tools.mssql_query,
        "description": "Run a read-only SELECT query against a specific database. Use mssql_list_databases first to discover database names. Runs under READ UNCOMMITTED to avoid locking.",
        "inputs": ["database_name", "query", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mssql_execute": {
        "function": mssql_tools.mssql_execute,
        "description": "Execute any T-SQL statement (INSERT, UPDATE, DELETE, DDL) against a specific database. Requires God Mode confirmation before running.",
        "inputs": ["database_name", "query", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "mssql_kill_spid": {
        "function": mssql_tools.mssql_kill_spid,
        "description": "Terminate a SQL Server session by SPID. The client receives a connection error and any open transaction is rolled back. Requires God Mode confirmation.",
        "inputs": ["spid", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "mssql_rebuild_index": {
        "function": mssql_tools.mssql_rebuild_index,
        "description": "Rebuild a specific index on a table (ONLINE=ON where supported). Use after mssql_index_fragmentation shows REBUILD recommendation. Requires God Mode confirmation.",
        "inputs": ["database_name", "schema_name", "table_name", "index_name", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium",
    },
    "mssql_update_statistics": {
        "function": mssql_tools.mssql_update_statistics,
        "description": "Run UPDATE STATISTICS WITH FULLSCAN on a table — forces query plan recompilation. Use when the query optimizer is making bad plan choices. Requires God Mode confirmation.",
        "inputs": ["database_name", "schema_name", "table_name", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "low",
    },

    # -----------------------------------------------------------------------
    # RabbitMQ
    # -----------------------------------------------------------------------
    "rabbitmq_list_queues": {
        "function": rabbitmq_tools.rabbitmq_list_queues,
        "description": "List all RabbitMQ queues with depth, ready/unacked counts, consumer count, state, and publish rate.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "rabbitmq_queue_detail": {
        "function": rabbitmq_tools.rabbitmq_queue_detail,
        "description": "Full stats for a specific queue: publish/deliver/ack rates, memory, consumer count. Use rabbitmq_list_queues first.",
        "inputs": ["queue_name", "vhost", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "rabbitmq_dead_letter_queues": {
        "function": rabbitmq_tools.rabbitmq_dead_letter_queues,
        "description": "Queues with dead-letter exchange (DLX) configured — shows DLX name, routing key, and current depth.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "rabbitmq_list_consumers": {
        "function": rabbitmq_tools.rabbitmq_list_consumers,
        "description": "All active consumers — queue, consumer tag, prefetch count, ack mode (auto vs manual), exclusive flag.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "rabbitmq_list_connections": {
        "function": rabbitmq_tools.rabbitmq_list_connections,
        "description": "Open client connections — peer IP, port, state, channel count, user.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "rabbitmq_node_health": {
        "function": rabbitmq_tools.rabbitmq_node_health,
        "description": "Node health: memory alarm, disk alarm, FD usage, process count, memory used vs limit, uptime.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "rabbitmq_list_exchanges": {
        "function": rabbitmq_tools.rabbitmq_list_exchanges,
        "description": "Named exchanges with type (direct/fanout/topic/headers), durability, and publish rate.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "rabbitmq_purge_queue": {
        "function": rabbitmq_tools.rabbitmq_purge_queue,
        "description": "Purge all messages from a queue. Queue definition remains but all messages are dropped. Requires God Mode confirmation.",
        "inputs": ["queue_name", "vhost", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "rabbitmq_delete_queue": {
        "function": rabbitmq_tools.rabbitmq_delete_queue,
        "description": "Delete a queue and all its messages permanently. Requires God Mode confirmation.",
        "inputs": ["queue_name", "vhost", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "rabbitmq_close_connection": {
        "function": rabbitmq_tools.rabbitmq_close_connection,
        "description": "Force-close a client connection by name. Use rabbitmq_list_connections to get connection names. Requires God Mode confirmation.",
        "inputs": ["connection_name", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },

    # -----------------------------------------------------------------------
    # Redis
    # -----------------------------------------------------------------------
    "redis_info": {
        "function": redis_tools.redis_info,
        "description": "Full Redis server stats: version, connected clients, memory, replication role, persistence, and keyspace.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "redis_memory_usage": {
        "function": redis_tools.redis_memory_usage,
        "description": "Redis memory stats: used memory, peak, fragmentation ratio, eviction policy, and maxmemory limit.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "redis_slow_log": {
        "function": redis_tools.redis_slow_log,
        "description": "Last 25 slow Redis commands with execution time in microseconds and client address.",
        "inputs": ["count", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "redis_client_list": {
        "function": redis_tools.redis_client_list,
        "description": "Connected clients with addr, db, last command, idle time, and flags.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "redis_replication_status": {
        "function": redis_tools.redis_replication_status,
        "description": "Replication role (master/replica), connected replicas, and replication offset/lag.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "redis_config_get": {
        "function": redis_tools.redis_config_get,
        "description": "Read Redis server configuration parameters matching a glob pattern (e.g. 'maxmemory*', 'save', '*').",
        "inputs": ["pattern", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "redis_keyspace_stats": {
        "function": redis_tools.redis_keyspace_stats,
        "description": "Key count per database, number of keys with TTL, and average TTL.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "redis_big_keys": {
        "function": redis_tools.redis_big_keys,
        "description": "Top 20 largest keys by memory consumption (samples up to 1000 keys using MEMORY USAGE).",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "redis_flushdb": {
        "function": redis_tools.redis_flushdb,
        "description": "Flush ALL keys from the connected Redis database (FLUSHDB ASYNC). Irreversible. Requires God Mode confirmation.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "critical",
    },
    "redis_delete_key": {
        "function": redis_tools.redis_delete_key,
        "description": "Delete a specific Redis key by exact name. Requires God Mode confirmation.",
        "inputs": ["key", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "redis_kill_client": {
        "function": redis_tools.redis_kill_client,
        "description": "Disconnect a Redis client by IP:port address. Use redis_client_list to get addresses. Requires God Mode confirmation.",
        "inputs": ["client_id", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium",
    },

    # -----------------------------------------------------------------------
    # PostgreSQL
    # -----------------------------------------------------------------------
    "postgres_active_connections": {
        "function": postgres_tools.postgres_active_connections,
        "description": "Active, idle, and waiting PostgreSQL connections grouped by state and application name.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_long_running_queries": {
        "function": postgres_tools.postgres_long_running_queries,
        "description": "Queries running longer than min_seconds — PID, duration, wait event type, and query text.",
        "inputs": ["min_seconds", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_lock_waits": {
        "function": postgres_tools.postgres_lock_waits,
        "description": "Blocking locks — which PID blocks which, with both the blocking and blocked query texts.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_table_sizes": {
        "function": postgres_tools.postgres_table_sizes,
        "description": "Top 20 tables by total size including indexes and TOAST. Shows table size, index size, total size.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_index_usage": {
        "function": postgres_tools.postgres_index_usage,
        "description": "Unused indexes (zero scans since last stats reset) that waste disk and slow write operations.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_bloat_estimate": {
        "function": postgres_tools.postgres_bloat_estimate,
        "description": "Tables with the most dead tuples — dead tuple %, last autovacuum and autoanalyze time.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_replication_lag": {
        "function": postgres_tools.postgres_replication_lag,
        "description": "Streaming replica lag in bytes and write/flush/replay lag per standby server.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_cache_hit_ratio": {
        "function": postgres_tools.postgres_cache_hit_ratio,
        "description": "Buffer cache hit ratio per table — tables below 95% suggest insufficient shared_buffers.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_database_stats": {
        "function": postgres_tools.postgres_database_stats,
        "description": "Per-database stats: connections, commits, rollbacks, cache hit ratio, deadlocks, temp file usage.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_query": {
        "function": postgres_tools.postgres_query,
        "description": "Run a read-only SELECT query against a specific PostgreSQL database. Use postgres_active_connections first to confirm connectivity.",
        "inputs": ["database", "query", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "postgres_kill_query": {
        "function": postgres_tools.postgres_kill_query,
        "description": "Cancel a query by PID using pg_cancel_backend (graceful — connection stays open). Requires God Mode confirmation.",
        "inputs": ["pid", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium",
    },
    "postgres_terminate_connection": {
        "function": postgres_tools.postgres_terminate_connection,
        "description": "Hard-terminate a backend connection by PID using pg_terminate_backend. Client gets a connection error. Requires God Mode confirmation.",
        "inputs": ["pid", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "postgres_run_vacuum": {
        "function": postgres_tools.postgres_run_vacuum,
        "description": "Run VACUUM ANALYZE on a specific table to reclaim dead tuple space and update planner statistics. Requires God Mode confirmation.",
        "inputs": ["table", "analyze", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "low",
    },

    # -----------------------------------------------------------------------
    # CouchDB
    # -----------------------------------------------------------------------
    "couchdb_server_info": {
        "function": couchdb_tools.couchdb_server_info,
        "description": "CouchDB server version, UUID, enabled features, and vendor info.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "couchdb_list_databases": {
        "function": couchdb_tools.couchdb_list_databases,
        "description": "List all CouchDB databases separated into user and system databases.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "couchdb_database_info": {
        "function": couchdb_tools.couchdb_database_info,
        "description": "Detailed info for one CouchDB database: doc count, deleted docs, data/disk sizes, update sequence.",
        "inputs": ["database", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "couchdb_active_tasks": {
        "function": couchdb_tools.couchdb_active_tasks,
        "description": "Ongoing background tasks: indexing, compaction, replication — with node, database, and progress %.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "couchdb_replication_status": {
        "function": couchdb_tools.couchdb_replication_status,
        "description": "All replication documents in _replicator with source, target, and state.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "couchdb_node_stats": {
        "function": couchdb_tools.couchdb_node_stats,
        "description": "CouchDB node stats: HTTP request count, database reads/writes, open databases, OS process count.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "couchdb_compact_db": {
        "function": couchdb_tools.couchdb_compact_db,
        "description": "Trigger compaction on a CouchDB database to reclaim disk space from deleted and updated documents. Requires God Mode confirmation.",
        "inputs": ["database", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "medium",
    },
    "couchdb_delete_db": {
        "function": couchdb_tools.couchdb_delete_db,
        "description": "Delete a CouchDB database and all its documents permanently. Requires God Mode confirmation.",
        "inputs": ["database", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "critical",
    },

    # -----------------------------------------------------------------------
    # MySQL
    # -----------------------------------------------------------------------
    "mysql_processlist": {
        "function": mysql_tools.mysql_processlist,
        "description": "Active MySQL connections — user, host, database, command, time, state, and current query.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mysql_global_status": {
        "function": mysql_tools.mysql_global_status,
        "description": "Key MySQL global status variables: connections, queries, uptime, InnoDB buffer pool hit ratio.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mysql_innodb_status": {
        "function": mysql_tools.mysql_innodb_status,
        "description": "InnoDB engine status — transactions, lock waits, deadlocks, buffer pool usage (SHOW ENGINE INNODB STATUS).",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mysql_slow_queries": {
        "function": mysql_tools.mysql_slow_queries,
        "description": "Top queries from performance_schema by total execution time — digest, exec count, avg/max latency.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mysql_lock_waits": {
        "function": mysql_tools.mysql_lock_waits,
        "description": "InnoDB lock waits — which thread is blocking which, with both query texts and wait duration.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mysql_table_sizes": {
        "function": mysql_tools.mysql_table_sizes,
        "description": "Top 20 MySQL tables by total size (data + index) in MB with row count estimate.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mysql_replication_status": {
        "function": mysql_tools.mysql_replication_status,
        "description": "MySQL replication status: IO/SQL thread state, seconds behind source, last error. Returns empty if this is a primary.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mysql_user_grants": {
        "function": mysql_tools.mysql_user_grants,
        "description": "All MySQL users with host, account_locked, and password_expired status.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mysql_execute": {
        "function": mysql_tools.mysql_execute,
        "description": "Execute any SQL statement (INSERT, UPDATE, DELETE, DDL) against a specific database. Requires God Mode confirmation.",
        "inputs": ["query", "database", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "mysql_kill_connection": {
        "function": mysql_tools.mysql_kill_connection,
        "description": "Terminate a MySQL connection by ID. Use mysql_processlist to get IDs. Requires God Mode confirmation.",
        "inputs": ["connection_id", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "mysql_optimize_table": {
        "function": mysql_tools.mysql_optimize_table,
        "description": "Run OPTIMIZE TABLE on a table to reclaim fragmented space and rebuild indexes. Requires God Mode confirmation.",
        "inputs": ["table", "database", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "low",
    },

    # -----------------------------------------------------------------------
    # MongoDB
    # -----------------------------------------------------------------------
    "mongo_list_databases": {
        "function": mongodb_tools.mongo_list_databases,
        "description": "List all MongoDB databases with their size on disk.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mongo_server_status": {
        "function": mongodb_tools.mongo_server_status,
        "description": "MongoDB server status: version, uptime, connections, opcounters, memory usage.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mongo_replication_status": {
        "function": mongodb_tools.mongo_replication_status,
        "description": "Replica set member health, state (PRIMARY/SECONDARY), and optime per member.",
        "inputs": ["cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mongo_collection_stats": {
        "function": mongodb_tools.mongo_collection_stats,
        "description": "Collection stats for a database: document count, size, storage size, index count per collection.",
        "inputs": ["database", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mongo_slow_ops": {
        "function": mongodb_tools.mongo_slow_ops,
        "description": "MongoDB operations running longer than min_seconds — opid, op type, namespace, elapsed seconds.",
        "inputs": ["min_seconds", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mongo_index_stats": {
        "function": mongodb_tools.mongo_index_stats,
        "description": "Index usage stats for a collection — name, key spec, and access count since last restart.",
        "inputs": ["database", "collection", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mongo_query": {
        "function": mongodb_tools.mongo_query,
        "description": "Query a MongoDB collection with a JSON filter (returns up to 20 docs). Pass '{}' for first documents.",
        "inputs": ["database", "collection", "filter_json", "limit", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mongo_explain": {
        "function": mongodb_tools.mongo_explain,
        "description": "EXPLAIN a MongoDB query to inspect the winning plan and index usage.",
        "inputs": ["database", "collection", "filter_json", "cluster_id", "instance_name"],
        "operation_type": "read",
        "requires_confirmation": False,
    },
    "mongo_kill_op": {
        "function": mongodb_tools.mongo_kill_op,
        "description": "Kill a running MongoDB operation by opid. Use mongo_slow_ops to find opids. Requires God Mode confirmation.",
        "inputs": ["opid", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "high",
    },
    "mongo_drop_collection": {
        "function": mongodb_tools.mongo_drop_collection,
        "description": "Drop a MongoDB collection and all its documents and indexes permanently. Requires God Mode confirmation.",
        "inputs": ["database", "collection", "cluster_id", "instance_name"],
        "operation_type": "write",
        "requires_confirmation": True,
        "risk_level": "critical",
    },
}

def get_rag_tool_descriptions_for_prompt() -> str:
    """Returns RAG tool descriptions to append to the agent system prompt."""
    lines = ["RAG TOOLS (call these to retrieve context from the knowledge base):"]
    for name, info in RAG_TOOL_REGISTRY.items():
        inputs = ", ".join(info.get("inputs", []))
        lines.append(f"- {name}({inputs}): {info['description']} - EXECUTES IMMEDIATELY (READ)")
    return "\n".join(lines)


async def execute_rag_tool(tool_name: str, inputs: dict) -> Dict[str, Any]:
    """Execute a RAG tool by name."""
    if tool_name not in RAG_TOOL_REGISTRY:
        return {"success": False, "data": None, "error": f"RAG tool '{tool_name}' not found", "source": "system"}
    tool_info = RAG_TOOL_REGISTRY[tool_name]
    func = tool_info["function"]
    query = inputs.get("query", "")
    return await func(query=query)


def get_tool_descriptions_for_prompt() -> str:
    """Returns formatted tool list for injection into AI system prompt"""
    lines = []
    lines.append("CRITICAL INSTRUCTIONS FOR TOOLS:")
    lines.append("1. You have access to both READ and WRITE tools.")
    lines.append("2. READ operations execute immediately.")
    lines.append("3. WRITE operations: call them directly — do NOT ask 'would you like me to…' or describe the action in text first. Just call the tool. The platform presents an Approve/Reject card to the user automatically.")
    lines.append("4. If a tool returns 'requires_confirmation: true', IMMEDIATELY STOP and surface the pending_operation to the user. Do not call any more tools.")
    lines.append("5. NEVER produce a text description of a fix without calling the corresponding write tool when the user has asked you to fix something.")
    lines.append("")
    lines.append("AVAILABLE TOOLS:")
    for name, info in TOOL_REGISTRY.items():
        inputs_raw = info.get("inputs", [])
        inputs = ", ".join([str(i) for i in inputs_raw]) if isinstance(inputs_raw, list) else ""
        desc = info.get("description", "")
        req = "- IMMEDIATELY YIELDS FOR USER CONFIRMATION (WRITE)" if info.get("requires_confirmation") else "- EXECUTES IMMEDIATELY (READ)"
        lines.append(f"- {name}({inputs}): {desc} {req}")
    return "\n".join(lines)

def get_tools_for_runbook(tool_names: List[str]) -> List[Dict[str, Any]]:
    """Returns tool metadata for a specific runbook's steps"""
    return [TOOL_REGISTRY[name] for name in tool_names if name in TOOL_REGISTRY]


def build_openai_tools_schema(extra_tools: list | None = None) -> list:
    """Convert TOOL_REGISTRY into OpenAI function-calling tools format."""
    tools = []
    for name, info in TOOL_REGISTRY.items():
        inputs = info.get("inputs", [])
        properties = {
            inp: {"type": "string", "description": inp}
            for inp in inputs
            if inp
        }
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": [],
                },
            },
        })
    if extra_tools:
        for tool in extra_tools:
            extra_inputs = tool.get("inputs", [])
            extra_props = {inp: {"type": "string", "description": inp} for inp in extra_inputs if inp}
            tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": {"type": "object", "properties": extra_props, "required": []},
                },
            })
    return tools

def build_gemini_tools_schema(extra_tools: list | None = None) -> list:
    """Convert TOOL_REGISTRY into Gemini function_declarations format."""
    declarations = []
    for name, info in TOOL_REGISTRY.items():
        inputs = info.get("inputs", [])
        properties = {inp: {"type": "STRING"} for inp in inputs if inp}
        declarations.append({
            "name": name,
            "description": info["description"],
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        })
    if extra_tools:
        for tool in extra_tools:
            extra_inputs = tool.get("inputs", [])
            extra_props = {inp: {"type": "STRING"} for inp in extra_inputs if inp}
            declarations.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": {"type": "object", "properties": extra_props},
            })
    return [{"function_declarations": declarations}]


def execute_tool(tool_name: str, inputs: dict, confirmed: bool = False) -> Dict[str, Any]:
    """
    Central tool executor for SYNC tools only.
    For read tools: executes immediately.
    For write tools: if confirmed=False, returns pending confirmation object.
                     if confirmed=True, executes and returns result.

    IMPORTANT: If the tool is async, raises RuntimeError. Use execute_tool_async() instead.
    """
    if tool_name not in TOOL_REGISTRY:
        return {"success": False, "data": None, "error": f"Tool '{tool_name}' not found", "source": "system"}

    tool_info = TOOL_REGISTRY[tool_name]
    func = tool_info["function"]

    # Check if the tool is async BEFORE executing
    if inspect.iscoroutinefunction(func):
        raise RuntimeError(
            f"Tool '{tool_name}' is async — use execute_tool_async() instead"
        )

    # Auto-map raw query strings to proper kwargs if AI didn't use JSON
    if "query" in inputs and "query" not in tool_info["inputs"]:
        query_val = inputs.pop("query")
        if query_val and tool_info["inputs"]:
            primary_arg = tool_info["inputs"][0]
            if "namespace" in tool_info["inputs"] and "/" in str(query_val):
                ns, name = str(query_val).split("/", 1)
                inputs["namespace"] = ns
                inputs[primary_arg] = name
            else:
                inputs[primary_arg] = query_val

    # Prune inputs to only what the function accepts
    valid_inputs = {k: v for k, v in inputs.items() if k in tool_info["inputs"]}

    # Missing-args check
    sig = inspect.signature(func)
    missing = [
        p.name for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and p.name not in valid_inputs
    ]
    if missing:
        return {"success": False, "error": f"Missing required args: {missing}"}

    try:
        if tool_info["requires_confirmation"]:
            if "reason" not in valid_inputs:
                valid_inputs["reason"] = inputs.get("reason", "No reason provided by AI")
            valid_inputs["confirmed"] = confirmed
            result = func(**valid_inputs)
        else:
            result = func(**valid_inputs)
        if isinstance(result, dict) and result.get("requires_confirmation"):
            return result
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def execute_tool_async(tool_name: str, inputs: dict, confirmed: bool = False) -> Dict[str, Any]:
    """
    Async-aware tool dispatcher. Use this from async callers (agentic loops, API routes).
    Handles both sync and async tools transparently.

    For read tools: executes immediately.
    For write tools: if confirmed=False, returns pending confirmation object.
                     if confirmed=True, executes and returns result.
    """
    if tool_name not in TOOL_REGISTRY:
        return {"success": False, "data": None, "error": f"Tool '{tool_name}' not found", "source": "system"}

    tool_info = TOOL_REGISTRY[tool_name]
    func = tool_info["function"]

    # Auto-map raw query strings to proper kwargs if AI didn't use JSON
    if "query" in inputs and "query" not in tool_info["inputs"]:
        query_val = inputs.pop("query")
        if query_val and tool_info["inputs"]:
            primary_arg = tool_info["inputs"][0]
            if "namespace" in tool_info["inputs"] and "/" in str(query_val):
                ns, name = str(query_val).split("/", 1)
                inputs["namespace"] = ns
                inputs[primary_arg] = name
            else:
                inputs[primary_arg] = query_val

    # Prune inputs to only what the function accepts
    valid_inputs = {k: v for k, v in inputs.items() if k in tool_info["inputs"]}

    # Missing-args check
    sig = inspect.signature(func)
    missing = [
        p.name for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and p.name not in valid_inputs
    ]
    if missing:
        return {"success": False, "error": f"Missing required args: {missing}"}

    try:
        if tool_info["requires_confirmation"]:
            if "reason" not in valid_inputs:
                valid_inputs["reason"] = inputs.get("reason", "No reason provided by AI")
            valid_inputs["confirmed"] = confirmed

        if inspect.iscoroutinefunction(func):
            result = await func(**valid_inputs)
        else:
            result = func(**valid_inputs)

        if isinstance(result, dict) and result.get("requires_confirmation"):
            return result
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
