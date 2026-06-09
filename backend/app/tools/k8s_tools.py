import asyncio
import json
import logging
import os
import re as _re
import shlex
import stat
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple
from kubernetes_asyncio.client.rest import ApiException
from app.services.k8s_service import k8s_service


logger = logging.getLogger(__name__)

_K8S_NAME_RE = _re.compile(r'^[a-z0-9][a-z0-9\-\.]*$')


def _safe_kubectl_env() -> Tuple[dict, Optional[str]]:
    """Return (env_overrides, tmp_kubeconfig_path) for subprocess kubectl calls.

    Detects the "is a directory" problem that occurs in Docker when
    /root/.kube/config is a mounted directory instead of a file.
    Returns a patched env that points kubectl at a valid kubeconfig.
    The caller must delete tmp_kubeconfig_path (if not None) after kubectl exits.
    """
    import yaml as _yaml
    from sqlmodel import Session as _Session, select as _select
    from app.core.db import engine as _engine
    from app.models.cluster import ClusterConnection
    from app.core.encryption import decrypt as _decrypt

    # 1. Explicit KUBECONFIG env var pointing to a real file — nothing to do.
    kc_env = os.environ.get("KUBECONFIG", "")
    if kc_env and os.path.isfile(kc_env):
        return {}, None

    # 2. Default ~/.kube/config is a real file — nothing to do.
    default_kc = os.path.expanduser("~/.kube/config")
    if os.path.isfile(default_kc):
        return {}, None

    # 3. Kubeconfig path is missing or is a directory (container mount issue).
    #    Build a temp kubeconfig from the first available DB cluster.
    try:
        with _Session(_engine) as _db:
            conn = _db.exec(_select(ClusterConnection)).first()
        if not conn:
            return {}, None

        cluster_entry: dict = {"name": conn.name, "cluster": {"server": conn.api_server}}
        if conn.ca_cert:
            cluster_entry["cluster"]["certificate-authority-data"] = conn.ca_cert
        else:
            cluster_entry["cluster"]["insecure-skip-tls-verify"] = True

        user_entry: dict = {"name": conn.name, "user": {}}
        if conn.client_cert_data and conn.client_key_data:
            user_entry["user"]["client-certificate-data"] = conn.client_cert_data
            user_entry["user"]["client-key-data"] = _decrypt(conn.client_key_data)
        elif conn.token:
            user_entry["user"]["token"] = _decrypt(conn.token)

        kconfig = {
            "apiVersion": "v1", "kind": "Config",
            "clusters": [cluster_entry],
            "users": [user_entry],
            "contexts": [{"name": conn.name, "context": {"cluster": conn.name, "user": conn.name, "namespace": conn.namespace or "default"}}],
            "current-context": conn.name,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, prefix="dokops_kube_") as tf:
            _yaml.dump(kconfig, tf)
            tmp_path = tf.name
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        env = {**os.environ, "KUBECONFIG": tmp_path}
        return env, tmp_path
    except Exception as exc:
        logger.warning(f"_safe_kubectl_env: could not build temp kubeconfig: {exc}")
        return {}, None


def validate_k8s_name(value: str, field: str) -> str:
    """Validate that value is a safe Kubernetes resource name.
    Blocks kubectl argument injection (e.g. flag injection via spaces)."""
    if not value or not _K8S_NAME_RE.match(value):
        raise ValueError(
            f"Invalid {field}: {value!r}. "
            "Must match [a-z0-9][a-z0-9-.]*"
        )
    return value

async def kubectl_fallback(command: str) -> Dict[str, Any]:
    """
    Execute a kubectl command as subprocess fallback.
    Only called when kubernetes-client raises an exception.
    """
    logger.warning(f"Using kubectl fallback for command: {command}")
    env_override, tmp_kc = _safe_kubectl_env()
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            shlex.split(command),
            capture_output=True, text=True, timeout=30,
            env=env_override if env_override else None,
        )
        if result.returncode == 0:
            try:
                return {"success": True, "data": json.loads(result.stdout), "error": None, "source": "kubectl_fallback"}
            except json.JSONDecodeError:
                return {"success": True, "data": result.stdout.strip(), "error": None, "source": "kubectl_fallback"}
        else:
            return {"success": False, "data": None, "error": result.stderr.strip(), "source": "kubectl_fallback"}
    except subprocess.TimeoutExpired:
        return {"success": False, "data": None, "error": "kubectl command timed out after 30s", "source": "kubectl_fallback"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "kubectl_fallback"}
    finally:
        if tmp_kc:
            try:
                os.unlink(tmp_kc)
            except OSError:
                pass

# --- READ TOOLS (safe, no confirmation needed) ---

async def get_cluster_health() -> Dict[str, Any]:
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")
        nodes = (await core_api.list_node()).items
        pods = (await core_api.list_pod_for_all_namespaces()).items

        node_count = len(nodes)
        ready_nodes = len([n for n in nodes if any(c.type == "Ready" and c.status == "True" for c in (n.status.conditions or []))])

        pod_count = len(pods)
        running_pods = 0
        pending_pods = 0
        unhealthy_pods = []

        for p in pods:
            phase = p.status.phase or "Unknown"
            name = p.metadata.name
            namespace = p.metadata.namespace

            # Skip completed/succeeded jobs — they are not errors
            if phase == "Succeeded":
                continue

            if phase == "Running":
                # Check if all containers are actually ready
                container_statuses = p.status.container_statuses or []
                total = len(container_statuses)
                ready = sum(1 for c in container_statuses if c.ready)

                # Detect crash/waiting reasons
                for cs in container_statuses:
                    if cs.state and cs.state.waiting:
                        reason = cs.state.waiting.reason or ""
                        if reason in ("CrashLoopBackOff", "Error", "OOMKilled", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"):
                            unhealthy_pods.append({
                                "name": name,
                                "namespace": namespace,
                                "phase": phase,
                                "issue": reason,
                                "restarts": cs.restart_count,
                            })
                            break
                else:
                    if total > 0 and ready < total:
                        unhealthy_pods.append({
                            "name": name,
                            "namespace": namespace,
                            "phase": phase,
                            "issue": f"NotReady ({ready}/{total} containers ready)",
                            "restarts": max((cs.restart_count for cs in container_statuses), default=0),
                        })
                    else:
                        running_pods += 1

            elif phase == "Pending":
                pending_pods += 1
                unhealthy_pods.append({
                    "name": name,
                    "namespace": namespace,
                    "phase": phase,
                    "issue": "Pending",
                    "restarts": 0,
                })

            elif phase in ("Failed", "Unknown"):
                unhealthy_pods.append({
                    "name": name,
                    "namespace": namespace,
                    "phase": phase,
                    "issue": phase,
                    "restarts": 0,
                })

        is_healthy = ready_nodes == node_count and len(unhealthy_pods) == 0
        data = {
            "node_count": node_count,
            "ready_nodes": ready_nodes,
            "pod_count": pod_count,
            "running_pods": running_pods,
            "pending_pods": pending_pods,
            "unhealthy_pod_count": len(unhealthy_pods),
            "unhealthy_pods": unhealthy_pods,
            "status": "Healthy" if is_healthy else "Degraded",
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_cluster_health: {e}")
        return await kubectl_fallback("kubectl get nodes,pods -A")

async def search_pods(keyword: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")
        if namespace:
            pods = (await core_api.list_namespaced_pod(namespace)).items
        else:
            pods = (await core_api.list_pod_for_all_namespaces()).items

        kw = keyword.lower().strip()
        # Synonyms: when user/agent asks generically, match all non-running pods
        _unhealthy_synonyms = {"fail", "failing", "failed", "broken", "unhealthy", "bad", "crash", "crashing", "error", "problem", "issue", "notrunning", "not running"}
        broad_unhealthy = not kw or any(s in kw for s in _unhealthy_synonyms)

        data = []
        for p in pods:
            phase = p.status.phase or "Unknown"

            # Resolve the real container-level status (waiting reason > phase)
            real_status = phase
            container_statuses = p.status.container_statuses or []
            for cs in container_statuses:
                if cs.state.waiting and cs.state.waiting.reason:
                    real_status = cs.state.waiting.reason
                    break
                if cs.state.terminated and cs.state.terminated.reason:
                    real_status = cs.state.terminated.reason
                    break

            is_unhealthy = phase not in ("Running", "Succeeded") or real_status != phase

            match = False
            if broad_unhealthy:
                match = is_unhealthy
            else:
                if kw in p.metadata.name.lower(): match = True
                if kw in p.metadata.namespace.lower(): match = True
                if kw in phase.lower(): match = True
                if kw in real_status.lower(): match = True
                for cs in container_statuses:
                    if cs.state.waiting and cs.state.waiting.reason and kw in cs.state.waiting.reason.lower():
                        match = True
                        break

            if match:
                data.append({
                    "name": p.metadata.name,
                    "namespace": p.metadata.namespace,
                    "status": real_status,
                    "phase": phase,
                    "restarts": sum(cs.restart_count for cs in container_statuses),
                    "node": p.spec.node_name,
                })

        data = data[:50]
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in search_pods: {e}")
        return await kubectl_fallback(f"kubectl get pods -A | grep -i {keyword} | head -n 50")

async def _find_pod_namespace(pod_name: str) -> Optional[str]:
    """Search all namespaces to find which namespace a pod lives in."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            return None
        pods = await core_api.list_pod_for_all_namespaces(
            field_selector=f"metadata.name={pod_name}"
        )
        if pods.items:
            return pods.items[0].metadata.namespace
    except Exception:
        pass
    return None

async def get_pod_status(pod_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    if not namespace:
        namespace = await _find_pod_namespace(pod_name)
        if not namespace:
            return {"success": False, "data": None, "error": f"Pod '{pod_name}' not found in any namespace", "source": "k8s_client"}
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        pod = await core_api.read_namespaced_pod(pod_name, namespace)

        container_statuses = []
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                state = {}
                if cs.state.running:
                    state["running"] = {"started_at": str(cs.state.running.started_at)}
                elif cs.state.waiting:
                    state["waiting"] = {"reason": cs.state.waiting.reason, "message": cs.state.waiting.message}
                elif cs.state.terminated:
                    state["terminated"] = {"exit_code": cs.state.terminated.exit_code, "reason": cs.state.terminated.reason, "message": cs.state.terminated.message}
                
                container_statuses.append({
                    "name": cs.name,
                    "ready": cs.ready,
                    "restart_count": cs.restart_count,
                    "state": state
                })

        conditions = [{"type": c.type, "status": c.status, "reason": c.reason, "message": c.message} for c in (pod.status.conditions or [])]

        data = {
            "phase": pod.status.phase,
            "conditions": conditions,
            "container_statuses": container_statuses,
            "node_name": pod.spec.node_name,
            "pod_ip": pod.status.pod_ip,
            "start_time": str(pod.status.start_time) if pod.status.start_time else None
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_pod_status: {e}")
        return await kubectl_fallback(f"kubectl get pod {pod_name} -n {namespace} -o json")

async def get_pod_logs(pod_name: str, namespace: Optional[str] = None, container_name: Optional[str] = None, previous: bool = False, tail_lines: int = 200) -> Dict[str, Any]:
    if not namespace:
        namespace = await _find_pod_namespace(pod_name)
        if not namespace:
            return {"success": False, "data": None, "error": f"Pod '{pod_name}' not found in any namespace", "source": "k8s_client"}
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        kwargs = {"tail_lines": tail_lines, "previous": previous}
        if container_name:
            kwargs["container"] = container_name

        logs = await core_api.read_namespaced_pod_log(pod_name, namespace, **kwargs)
        # truncate if over 50k
        if len(logs) > 50000:
            logs = logs[-50000:]
            
        return {"success": True, "data": logs, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_pod_logs: {e}")
        pod_name = validate_k8s_name(pod_name, "pod_name")
        namespace = validate_k8s_name(namespace, "namespace")
        cmd = f"kubectl logs {pod_name} -n {namespace} --tail={tail_lines}"
        if previous:
            cmd += " --previous"
        if container_name:
            container_name = validate_k8s_name(container_name, "container_name")
            cmd += f" -c {container_name}"
        return await kubectl_fallback(cmd)

async def get_pod_events(pod_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    if not namespace:
        namespace = await _find_pod_namespace(pod_name)
        if not namespace:
            return {"success": False, "data": None, "error": f"Pod '{pod_name}' not found in any namespace", "source": "k8s_client"}
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        field_selector = f"involvedObject.name={pod_name},involvedObject.kind=Pod"
        events = await core_api.list_namespaced_event(namespace, field_selector=field_selector)

        data = []
        for e in events.items:
            data.append({
                "type": e.type,
                "reason": e.reason,
                "message": e.message,
                "count": e.count,
                "last_timestamp": str(e.last_timestamp) if e.last_timestamp else None
            })
            
        # sort by last_timestamp
        data.sort(key=lambda x: x["last_timestamp"] or "")
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_pod_events: {e}")
        return await kubectl_fallback(f"kubectl get events -n {namespace} --field-selector involvedObject.name={pod_name} -o json")

async def get_deployment_status(deployment_name: str, namespace: str) -> Dict[str, Any]:
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")

        dep = await apps_api.read_namespaced_deployment(deployment_name, namespace)

        conditions = [{"type": c.type, "status": c.status, "reason": c.reason, "message": c.message} for c in (dep.status.conditions or [])]
        image_per_container = {c.name: c.image for c in dep.spec.template.spec.containers}
        
        data = {
            "desired_replicas": dep.spec.replicas,
            "ready_replicas": dep.status.ready_replicas or 0,
            "available_replicas": dep.status.available_replicas or 0,
            "updated_replicas": dep.status.updated_replicas or 0,
            "conditions": conditions,
            "strategy": dep.spec.strategy.type,
            "image_per_container": image_per_container
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_deployment_status: {e}")
        return await kubectl_fallback(f"kubectl get deployment {deployment_name} -n {namespace} -o json")

async def get_node_status(node_name: Optional[str] = None) -> Dict[str, Any]:
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        nodes_to_process = []
        if node_name:
            nodes_to_process.append(await core_api.read_node(node_name))
        else:
            nodes_to_process = (await core_api.list_node()).items

        data = []
        for n in nodes_to_process:
            conditions = [{"type": c.type, "status": c.status, "reason": c.reason, "message": c.message} for c in (n.status.conditions or [])]
            data.append({
                "name": n.metadata.name,
                "status": conditions[-1]["type"] if conditions else "Unknown",
                "conditions": conditions,
                "capacity": n.status.capacity,
                "allocatable": n.status.allocatable,
                "taints": [{"key": t.key, "value": t.value, "effect": t.effect} for t in (n.spec.taints or [])],
                "labels": n.metadata.labels,
                "kubelet_version": n.status.node_info.kubelet_version
            })
            
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_node_status: {e}")
        cmd = f"kubectl get node {node_name} -o json" if node_name else "kubectl get nodes -o json"
        return await kubectl_fallback(cmd)

async def get_node_capacity(node_name: Optional[str] = None) -> Dict[str, Any]:
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        custom_api = k8s_service._get_api("CustomObjectsApi")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        metrics_available = False
        metrics_by_node = {}
        if custom_api:
            try:
                metrics = await custom_api.list_cluster_custom_object(
                    group="metrics.k8s.io", version="v1beta1", plural="nodes"
                )
                for item in metrics.get("items", []):
                    metrics_by_node[item["metadata"]["name"]] = item["usage"]
                metrics_available = True
            except Exception:
                pass

        nodes_to_process = []
        if node_name:
            nodes_to_process.append(await core_api.read_node(node_name))
        else:
            nodes_to_process = (await core_api.list_node()).items

        data = {}
        for n in nodes_to_process:
            name = n.metadata.name
            alloc = n.status.allocatable
            
            # For requested_cpu/memory, we cannot get it easily from node status without aggregating pods.
            # But the metric server gives live usage, which is often what's wanted. 
            # The prompt asks for requested_cpu, requested_memory which normally requires iterating all pods.
            # We'll return allocatable and metrics.k8s.io usage if available.
            
            node_data = {
                "allocatable_cpu": alloc.get("cpu"),
                "allocatable_memory": alloc.get("memory"),
                "pods_capacity": alloc.get("pods")
            }
            if metrics_available and name in metrics_by_node:
                node_data["usage_cpu"] = metrics_by_node[name].get("cpu")
                node_data["usage_memory"] = metrics_by_node[name].get("memory")
            else:
                node_data["note"] = "Metrics server unavailable, live usage unavailable."
                
            data[name] = node_data
            
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_node_capacity: {e}")
        cmd = f"kubectl describe node {node_name}" if node_name else "kubectl describe nodes"
        # We can't safely grep -A5 in a simple subprocess call without pipeline, so just describe
        return await kubectl_fallback(f"{cmd} | grep -A5 'Allocated resources' || true")

async def get_replicasets(deployment_name: str, namespace: str) -> Dict[str, Any]:
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")

        # Get the deployment to find its selector and match labels
        dep = await apps_api.read_namespaced_deployment(deployment_name, namespace)
        match_labels = dep.spec.selector.match_labels
        label_selector = ",".join([f"{k}={v}" for k, v in match_labels.items()])

        rss = await apps_api.list_namespaced_replica_set(namespace, label_selector=label_selector)
        
        data = []
        for rs in rss.items:
            # Check owner references to be completely sure
            is_owned = False
            if rs.metadata.owner_references:
                for ref in rs.metadata.owner_references:
                    if ref.kind == "Deployment" and ref.name == deployment_name:
                        is_owned = True
                        break
            
            if is_owned:
                rev = rs.metadata.annotations.get("deployment.kubernetes.io/revision", "unknown") if rs.metadata.annotations else "unknown"
                data.append({
                    "name": rs.metadata.name,
                    "desired": rs.spec.replicas,
                    "ready": rs.status.ready_replicas or 0,
                    "image": rs.spec.template.spec.containers[0].image if rs.spec.template.spec.containers else "unknown",
                    "creation_timestamp": str(rs.metadata.creation_timestamp),
                    "revision": rev
                })
        
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_replicasets: {e}")
        # fallback needs label_selector but it's hard without parsing deployment
        # default to empty label filtering in fallback
        return await kubectl_fallback(f"kubectl get rs -n {namespace} -o json")

async def describe_pod_scheduling(namespace: str, pod_name: Optional[str] = None, deployment_name: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not pod_name and not deployment_name:
            return {"success": False, "data": None, "error": "Must provide pod_name or deployment_name", "source": "k8s_client"}

        spec = None
        if pod_name:
            core_api = k8s_service._get_api("CoreV1Api")
            pod = await core_api.read_namespaced_pod(pod_name, namespace)
            spec = pod.spec
        else:
            apps_api = k8s_service._get_api("AppsV1Api")
            dep = await apps_api.read_namespaced_deployment(deployment_name, namespace)
            spec = dep.spec.template.spec
            
        requests = {}
        limits = {}
        for c in spec.containers:
            if c.resources:
                if c.resources.requests: requests[c.name] = c.resources.requests
                if c.resources.limits: limits[c.name] = c.resources.limits
                
        data = {
            "node_selector": spec.node_selector,
            "affinity_rules": spec.affinity.to_dict() if hasattr(spec, 'affinity') and spec.affinity else None,
            "tolerations": [t.to_dict() for t in (spec.tolerations or [])],
            "resource_requests": requests,
            "resource_limits": limits,
            "image_pull_secrets": [s.name for s in (spec.image_pull_secrets or [])]
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in describe_pod_scheduling: {e}")
        if pod_name:
            return await kubectl_fallback(f"kubectl get pod {pod_name} -n {namespace} -o json")
        else:
            return await kubectl_fallback(f"kubectl get deployment {deployment_name} -n {namespace} -o json")

async def get_pvc_status(pvc_name: str, namespace: str) -> Dict[str, Any]:
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        pvc = await core_api.read_namespaced_persistent_volume_claim(pvc_name, namespace)
        
        data = {
            "phase": pvc.status.phase,
            "capacity": pvc.status.capacity,
            "access_modes": pvc.status.access_modes,
            "storage_class": pvc.spec.storage_class_name,
            "bound_pv_name": pvc.spec.volume_name,
            "volume_mode": pvc.spec.volume_mode
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_pvc_status: {e}")
        return await kubectl_fallback(f"kubectl get pvc {pvc_name} -n {namespace} -o json")

async def get_deployment_rollout_history(deployment_name: str, namespace: str) -> Dict[str, Any]:
    try:
        res = await get_replicasets(deployment_name, namespace)
        if not res["success"]:
            return res

        history = []
        for rs in res["data"]:
            history.append({
                "revision": rs["revision"],
                "image": rs["image"],
                "change_cause": "unknown (can check annotations)", # In k8s client, usually kubernetes.io/change-cause annotation
                "creation_timestamp": rs["creation_timestamp"]
            })

        history.sort(key=lambda x: int(x["revision"]) if x["revision"].isdigit() else 0)
        return {"success": True, "data": history, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_deployment_rollout_history: {e}")
        return await kubectl_fallback(f"kubectl rollout history deployment/{deployment_name} -n {namespace}")

async def list_pods_on_node(node_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        field_selector = f"spec.nodeName={node_name}"

        if namespace:
            pods = await core_api.list_namespaced_pod(namespace, field_selector=field_selector)
        else:
            pods = await core_api.list_pod_for_all_namespaces(field_selector=field_selector)
            
        data = []
        for p in pods.items:
            dep_name = None
            if p.metadata.owner_references:
                for ref in p.metadata.owner_references:
                    if ref.kind == "ReplicaSet":
                        # Hacky way to guess deployment name from RS name
                        dep_name = "-".join(ref.name.split("-")[:-1])
            
            data.append({
                "name": p.metadata.name,
                "namespace": p.metadata.namespace,
                "status": p.status.phase,
                "restarts": sum([cs.restart_count for cs in p.status.container_statuses]) if p.status.container_statuses else 0,
                "deployment_name": dep_name
            })
            
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_pods_on_node: {e}")
        cmd = f"kubectl get pods -A --field-selector spec.nodeName={node_name} -o json"
        if namespace:
            cmd = f"kubectl get pods -n {namespace} --field-selector spec.nodeName={node_name} -o json"
        return await kubectl_fallback(cmd)

async def get_secret_exists(secret_name: str, namespace: str) -> Dict[str, Any]:
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        secret = await core_api.read_namespaced_secret(secret_name, namespace)

        data = {
            "exists": True,
            "name": secret.metadata.name,
            "namespace": secret.metadata.namespace,
            "type": secret.type,
            "creation_timestamp": str(secret.metadata.creation_timestamp)
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except ApiException as e:
        if e.status == 404:
            return {"success": True, "data": {"exists": False, "name": secret_name, "namespace": namespace}, "error": None, "source": "k8s_client"}
        logger.error(f"k8s_client error in get_secret_exists: {e}")
        return await kubectl_fallback(f"kubectl get secret {secret_name} -n {namespace} -o json | jq 'del(.data)'")
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def list_secrets(namespace=None):
    """List secrets in a namespace — returns names and types only, never values."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")
        if namespace:
            result = await core_api.list_namespaced_secret(namespace)
        else:
            result = await core_api.list_secret_for_all_namespaces()
        secrets = [
            {
                "name": s.metadata.name,
                "namespace": s.metadata.namespace,
                "type": s.type,
                "key_count": len(s.data) if s.data else 0,
                "creation_timestamp": str(s.metadata.creation_timestamp),
            }
            for s in result.items
        ]
        return {"success": True, "data": {"secrets": secrets, "count": len(secrets)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_secrets: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_secret_keys(secret_name: str, namespace: str):
    """Get the key names stored in a secret — values are NEVER returned."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")
        secret = await core_api.read_namespaced_secret(secret_name, namespace)
        keys = list(secret.data.keys()) if secret.data else []
        return {
            "success": True,
            "data": {
                "name": secret.metadata.name,
                "namespace": secret.metadata.namespace,
                "type": secret.type,
                "keys": keys,
                "key_count": len(keys),
            },
            "error": None,
            "source": "k8s_client",
        }
    except ApiException as e:
        if e.status == 404:
            return {"success": False, "data": None, "error": f"Secret '{secret_name}' not found in namespace '{namespace}'", "source": "k8s_client"}
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_secret_keys: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def patch_secret(secret_name: str, namespace: str, key: str, value: str, reason: str, confirmed: bool = False):
    """Update a single key in a Kubernetes Secret. Requires God Mode confirmation."""
    if not confirmed:
        msg = (
            f"The AI wants to update secret '{secret_name}' in namespace '{namespace}'.\n\n"
            f"Key to update: `{key}`\n"
            f"Reason: {reason}\n\n"
            f"⚠️ This will change a credential or configuration value stored in Kubernetes. "
            f"Pods that mount this secret may need a restart to pick up the change.\n\n"
            f"Approve or cancel?"
        )
        return _pending_confirmation("patch_secret", {"secret_name": secret_name, "namespace": namespace, "key": key, "value": "***", "reason": reason}, msg, "high")
    try:
        import base64
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")
        encoded_value = base64.b64encode(value.encode()).decode()
        patch_body = {"data": {key: encoded_value}}
        await core_api.patch_namespaced_secret(secret_name, namespace, patch_body)
        return {
            "success": True,
            "data": f"Secret '{secret_name}/{key}' in namespace '{namespace}' updated successfully. Restart affected pods to pick up the change.",
            "error": None,
            "source": "k8s_client",
        }
    except Exception as e:
        logger.error(f"k8s_client error in patch_secret: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_events(namespace: Optional[str] = None, resource_name: Optional[str] = None, resource_kind: Optional[str] = None) -> Dict[str, Any]:
    """List events across all namespaces or a specific one, optionally filtered by resource."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        field_selector_parts = []
        if resource_name:
            field_selector_parts.append(f"involvedObject.name={resource_name}")
        if resource_kind:
            field_selector_parts.append(f"involvedObject.kind={resource_kind}")
        kwargs = {}
        if field_selector_parts:
            kwargs["field_selector"] = ",".join(field_selector_parts)

        if namespace:
            events = await core_api.list_namespaced_event(namespace, **kwargs)
        else:
            events = await core_api.list_event_for_all_namespaces(**kwargs)

        data = []
        for e in events.items:
            data.append({
                "namespace": e.metadata.namespace,
                "type": e.type,
                "reason": e.reason,
                "message": e.message,
                "involved_object": f"{e.involved_object.kind}/{e.involved_object.name}",
                "count": e.count,
                "last_timestamp": str(e.last_timestamp) if e.last_timestamp else None
            })

        data.sort(key=lambda x: x["last_timestamp"] or "")
        # cap at 200 events to avoid overwhelming context
        data = data[-200:]
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_events: {e}")
        cmd = f"kubectl get events -n {namespace} -o json" if namespace else "kubectl get events -A -o json"
        if resource_name:
            cmd += f" --field-selector involvedObject.name={resource_name}"
        return await kubectl_fallback(cmd)

async def get_logs(pod_name: str, namespace: Optional[str] = None, container_name: Optional[str] = None, previous: bool = False, tail_lines: int = 200) -> Dict[str, Any]:
    """Get logs from a pod, with automatic namespace discovery if namespace is omitted."""
    return await get_pod_logs(pod_name, namespace, container_name, previous, tail_lines)

async def search_configmaps(keyword: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """Search for configmaps by keyword in their name across all (or one) namespace."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        kw = keyword.lower()
        matches = []

        if namespace:
            cms = await core_api.list_namespaced_config_map(namespace)
            all_cms = [(namespace, cm) for cm in cms.items]
        else:
            cms = await core_api.list_config_map_for_all_namespaces()
            all_cms = [(cm.metadata.namespace, cm) for cm in cms.items]

        for ns, cm in all_cms:
            if kw in cm.metadata.name.lower():
                matches.append({
                    "name": cm.metadata.name,
                    "namespace": ns,
                    "keys": list(cm.data.keys()) if cm.data else []
                })

        if not matches:
            searched = f"namespace '{namespace}'" if namespace else "all namespaces"
            return {"success": False, "data": None, "error": f"No ConfigMaps matching '{keyword}' found in {searched}", "source": "k8s_client"}

        return {"success": True, "data": {"matches": matches, "total": len(matches)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in search_configmaps: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get configmap {flag} -o json")


async def get_configmap(configmap_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        # If no namespace given, or not found in given namespace, search all namespaces
        namespaces_to_try: List[str] = []
        if namespace:
            namespaces_to_try = [namespace]
        else:
            try:
                ns_list = await core_api.list_namespace()
                namespaces_to_try = [n.metadata.name for n in ns_list.items]
            except Exception:
                namespaces_to_try = ["default"]

        for ns in namespaces_to_try:
            try:
                cm = await core_api.read_namespaced_config_map(configmap_name, ns)
                data = {
                    "name": cm.metadata.name,
                    "namespace": cm.metadata.namespace,
                    "data": cm.data,
                    "creation_timestamp": str(cm.metadata.creation_timestamp)
                }
                return {"success": True, "data": data, "error": None, "source": "k8s_client"}
            except ApiException as e:
                if e.status == 404:
                    continue
                raise

        searched = namespace or "all namespaces"
        return {"success": False, "data": None, "error": f"ConfigMap '{configmap_name}' not found in {searched}", "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_configmap: {e}")
        cmd = f"kubectl get configmap {configmap_name} -n {namespace} -o json" if namespace else f"kubectl get configmap {configmap_name} -A -o json"
        return await kubectl_fallback(cmd)

async def get_service(service_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """Get a Kubernetes Service's ports, selector, ClusterIP, and type."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            namespaces_to_try = [namespace]
        else:
            try:
                ns_list = await core_api.list_namespace()
                namespaces_to_try = [n.metadata.name for n in ns_list.items]
            except Exception:
                namespaces_to_try = ["default"]

        for ns in namespaces_to_try:
            try:
                svc = await core_api.read_namespaced_service(service_name, ns)
                ports = []
                for p in (svc.spec.ports or []):
                    ports.append({
                        "name": p.name,
                        "port": p.port,
                        "target_port": str(p.target_port),
                        "protocol": p.protocol,
                        "node_port": p.node_port,
                    })
                data = {
                    "name": svc.metadata.name,
                    "namespace": svc.metadata.namespace,
                    "type": svc.spec.type,
                    "cluster_ip": svc.spec.cluster_ip,
                    "external_ips": svc.spec.external_i_ps,
                    "selector": svc.spec.selector,
                    "ports": ports,
                    "creation_timestamp": str(svc.metadata.creation_timestamp),
                }
                return {"success": True, "data": data, "error": None, "source": "k8s_client"}
            except ApiException as e:
                if e.status == 404:
                    continue
                raise

        searched = namespace or "all namespaces"
        return {"success": False, "data": None, "error": f"Service '{service_name}' not found in {searched}", "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_service: {e}")
        cmd = f"kubectl get svc {service_name} -n {namespace} -o json" if namespace else f"kubectl get svc {service_name} -A -o json"
        return await kubectl_fallback(cmd)

async def list_services(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List all services in a namespace or across all namespaces."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            svcs = await core_api.list_namespaced_service(namespace)
        else:
            svcs = await core_api.list_service_for_all_namespaces()

        results = []
        for svc in svcs.items:
            ports_summary = ", ".join([
                f"{p.name or 'unnamed'}:{p.port}/{p.protocol}" for p in (svc.spec.ports or [])
            ])
            results.append({
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "ports": ports_summary,
            })

        return {"success": True, "data": {"services": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_services: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get svc {flag} -o json")

async def get_endpoints(service_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """Get endpoints backing a service — shows actual pod IPs and ports."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            namespaces_to_try = [namespace]
        else:
            try:
                ns_list = await core_api.list_namespace()
                namespaces_to_try = [n.metadata.name for n in ns_list.items]
            except Exception:
                namespaces_to_try = ["default"]

        for ns in namespaces_to_try:
            try:
                ep = await core_api.read_namespaced_endpoints(service_name, ns)
                subsets = []
                for subset in (ep.subsets or []):
                    addresses = [{"ip": addr.ip, "target_ref": addr.target_ref.name if addr.target_ref else None} for addr in (subset.addresses or [])]
                    not_ready = [{"ip": addr.ip, "target_ref": addr.target_ref.name if addr.target_ref else None} for addr in (subset.not_ready_addresses or [])]
                    ports = [{"name": p.name, "port": p.port, "protocol": p.protocol} for p in (subset.ports or [])]
                    subsets.append({"addresses": addresses, "not_ready_addresses": not_ready, "ports": ports})

                data = {
                    "name": ep.metadata.name,
                    "namespace": ep.metadata.namespace,
                    "subsets": subsets,
                    "total_ready": sum(len(s["addresses"]) for s in subsets),
                    "total_not_ready": sum(len(s["not_ready_addresses"]) for s in subsets),
                }
                return {"success": True, "data": data, "error": None, "source": "k8s_client"}
            except ApiException as e:
                if e.status == 404:
                    continue
                raise

        searched = namespace or "all namespaces"
        return {"success": False, "data": None, "error": f"Endpoints '{service_name}' not found in {searched}", "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_endpoints: {e}")
        cmd = f"kubectl get endpoints {service_name} -n {namespace} -o json" if namespace else f"kubectl get endpoints {service_name} -A -o json"
        return await kubectl_fallback(cmd)

async def get_ingress(ingress_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """Get an Ingress resource's rules, hosts, backends, and TLS config."""
    try:
        net_api = k8s_service._get_api("NetworkingV1Api")
        if not net_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            namespaces_to_try = [namespace]
        else:
            core_api = k8s_service._get_api("CoreV1Api")
            try:
                ns_list = await core_api.list_namespace()
                namespaces_to_try = [n.metadata.name for n in ns_list.items]
            except Exception:
                namespaces_to_try = ["default"]

        for ns in namespaces_to_try:
            try:
                ing = await net_api.read_namespaced_ingress(ingress_name, ns)
                rules = []
                for rule in (ing.spec.rules or []):
                    paths = []
                    for path in (rule.http.paths if rule.http else []):
                        paths.append({
                            "path": path.path,
                            "path_type": path.path_type,
                            "backend_service": path.backend.service.name if path.backend and path.backend.service else None,
                            "backend_port": path.backend.service.port.number if path.backend and path.backend.service and path.backend.service.port else None,
                        })
                    rules.append({"host": rule.host, "paths": paths})

                tls = []
                for t in (ing.spec.tls or []):
                    tls.append({"hosts": t.hosts, "secret_name": t.secret_name})

                data = {
                    "name": ing.metadata.name,
                    "namespace": ing.metadata.namespace,
                    "ingress_class": ing.spec.ingress_class_name,
                    "rules": rules,
                    "tls": tls,
                    "default_backend": None,
                }
                if ing.spec.default_backend and ing.spec.default_backend.service:
                    data["default_backend"] = {
                        "service": ing.spec.default_backend.service.name,
                        "port": ing.spec.default_backend.service.port.number if ing.spec.default_backend.service.port else None,
                    }
                return {"success": True, "data": data, "error": None, "source": "k8s_client"}
            except ApiException as e:
                if e.status == 404:
                    continue
                raise

        searched = namespace or "all namespaces"
        return {"success": False, "data": None, "error": f"Ingress '{ingress_name}' not found in {searched}", "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_ingress: {e}")
        cmd = f"kubectl get ingress {ingress_name} -n {namespace} -o json" if namespace else f"kubectl get ingress {ingress_name} -A -o json"
        return await kubectl_fallback(cmd)

async def list_ingresses(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List all ingresses in a namespace or across all namespaces."""
    try:
        net_api = k8s_service._get_api("NetworkingV1Api")
        if not net_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            ings = await net_api.list_namespaced_ingress(namespace)
        else:
            ings = await net_api.list_ingress_for_all_namespaces()

        results = []
        for ing in ings.items:
            hosts = []
            for rule in (ing.spec.rules or []):
                if rule.host:
                    hosts.append(rule.host)
            lb_ips = []
            if ing.status and ing.status.load_balancer and ing.status.load_balancer.ingress:
                for lb in ing.status.load_balancer.ingress:
                    lb_ips.append(lb.ip or lb.hostname or "")
            results.append({
                "name": ing.metadata.name,
                "namespace": ing.metadata.namespace,
                "class": ing.spec.ingress_class_name,
                "hosts": hosts,
                "address": ", ".join(lb_ips),
            })

        return {"success": True, "data": {"ingresses": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_ingresses: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get ingress {flag} -o json")

async def get_network_policies(namespace: str) -> Dict[str, Any]:
    """Get all network policies in a namespace — shows who can talk to whom."""
    try:
        net_api = k8s_service._get_api("NetworkingV1Api")
        if not net_api:
            raise Exception("Kubeconfig not loaded")

        policies = await net_api.list_namespaced_network_policy(namespace)
        results = []
        for pol in policies.items:
            ingress_rules = []
            for rule in (pol.spec.ingress or []):
                sources = []
                for fr in (rule._from or []):
                    if fr.pod_selector:
                        sources.append({"type": "podSelector", "labels": fr.pod_selector.match_labels})
                    if fr.namespace_selector:
                        sources.append({"type": "namespaceSelector", "labels": fr.namespace_selector.match_labels})
                    if fr.ip_block:
                        sources.append({"type": "ipBlock", "cidr": fr.ip_block.cidr, "except": fr.ip_block._except})
                ports = [{"port": p.port, "protocol": p.protocol} for p in (rule.ports or [])]
                ingress_rules.append({"sources": sources, "ports": ports})

            egress_rules = []
            for rule in (pol.spec.egress or []):
                destinations = []
                for to in (rule.to or []):
                    if to.pod_selector:
                        destinations.append({"type": "podSelector", "labels": to.pod_selector.match_labels})
                    if to.namespace_selector:
                        destinations.append({"type": "namespaceSelector", "labels": to.namespace_selector.match_labels})
                    if to.ip_block:
                        destinations.append({"type": "ipBlock", "cidr": to.ip_block.cidr, "except": to.ip_block._except})
                ports = [{"port": p.port, "protocol": p.protocol} for p in (rule.ports or [])]
                egress_rules.append({"destinations": destinations, "ports": ports})

            results.append({
                "name": pol.metadata.name,
                "pod_selector": pol.spec.pod_selector.match_labels if pol.spec.pod_selector else {},
                "policy_types": pol.spec.policy_types,
                "ingress_rules": ingress_rules,
                "egress_rules": egress_rules,
            })

        return {"success": True, "data": {"policies": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_network_policies: {e}")
        return await kubectl_fallback(f"kubectl get networkpolicy -n {namespace} -o json")

async def list_configmaps(namespace: str) -> Dict[str, Any]:
    """List all configmaps in a namespace with their key names (not values)."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        cms = await core_api.list_namespaced_config_map(namespace)
        results = []
        for cm in cms.items:
            results.append({
                "name": cm.metadata.name,
                "namespace": cm.metadata.namespace,
                "keys": list(cm.data.keys()) if cm.data else [],
            })

        return {"success": True, "data": {"configmaps": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_configmaps: {e}")
        return await kubectl_fallback(f"kubectl get configmap -n {namespace} -o json")

async def search_configmap_values(keyword: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """Search configmap VALUES for a keyword across a namespace or all namespaces. Returns matching key-value pairs."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        kw = keyword.lower()
        if namespace:
            cms = await core_api.list_namespaced_config_map(namespace)
        else:
            cms = await core_api.list_config_map_for_all_namespaces()

        matches = []
        for cm in cms.items:
            if not cm.data:
                continue
            matching_keys = {}
            for k, v in cm.data.items():
                if kw in str(v).lower():
                    matching_keys[k] = v
            if matching_keys:
                matches.append({
                    "configmap_name": cm.metadata.name,
                    "namespace": cm.metadata.namespace,
                    "matching_entries": matching_keys,
                })

        if not matches:
            searched = f"namespace '{namespace}'" if namespace else "all namespaces"
            return {"success": False, "data": None, "error": f"No configmap values matching '{keyword}' found in {searched}", "source": "k8s_client"}

        return {"success": True, "data": {"matches": matches, "total": len(matches)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in search_configmap_values: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get configmap {flag} -o json")

async def get_workload_config(deployment_name: str, namespace: str) -> Dict[str, Any]:
    """Get all configmaps, secrets, and env vars mounted or referenced by a deployment's pod spec."""
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")

        dep = await apps_api.read_namespaced_deployment(deployment_name, namespace)
        pod_spec = dep.spec.template.spec

        volume_configmaps = []
        volume_secrets = []
        for vol in (pod_spec.volumes or []):
            if vol.config_map:
                volume_configmaps.append({"volume_name": vol.name, "configmap_name": vol.config_map.name})
            if vol.secret:
                volume_secrets.append({"volume_name": vol.name, "secret_name": vol.secret.secret_name})

        containers = []
        for container in (pod_spec.containers or []) + (pod_spec.init_containers or []):
            env_vars = []
            env_from_configmaps = []
            env_from_secrets = []

            for env in (container.env or []):
                entry = {"name": env.name}
                if env.value_from:
                    if env.value_from.config_map_key_ref:
                        entry["source"] = "configMapKeyRef"
                        entry["configmap_name"] = env.value_from.config_map_key_ref.name
                        entry["key"] = env.value_from.config_map_key_ref.key
                    elif env.value_from.secret_key_ref:
                        entry["source"] = "secretKeyRef"
                        entry["secret_name"] = env.value_from.secret_key_ref.name
                        entry["key"] = env.value_from.secret_key_ref.key
                    elif env.value_from.field_ref:
                        entry["source"] = "fieldRef"
                        entry["field_path"] = env.value_from.field_ref.field_path
                    elif env.value_from.resource_field_ref:
                        entry["source"] = "resourceFieldRef"
                        entry["resource"] = env.value_from.resource_field_ref.resource
                    else:
                        entry["source"] = "unknown"
                else:
                    entry["source"] = "literal"
                    entry["value"] = env.value
                env_vars.append(entry)

            for ef in (container.env_from or []):
                if ef.config_map_ref:
                    env_from_configmaps.append({"configmap_name": ef.config_map_ref.name, "prefix": ef.prefix})
                if ef.secret_ref:
                    env_from_secrets.append({"secret_name": ef.secret_ref.name, "prefix": ef.prefix})

            volume_mounts = []
            for vm in (container.volume_mounts or []):
                volume_mounts.append({"name": vm.name, "mount_path": vm.mount_path, "sub_path": vm.sub_path})

            containers.append({
                "container_name": container.name,
                "image": container.image,
                "env_vars": env_vars,
                "env_from_configmaps": env_from_configmaps,
                "env_from_secrets": env_from_secrets,
                "volume_mounts": volume_mounts,
            })

        data = {
            "deployment": deployment_name,
            "namespace": namespace,
            "volume_configmaps": volume_configmaps,
            "volume_secrets": volume_secrets,
            "containers": containers,
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_workload_config: {e}")
        return await kubectl_fallback(f"kubectl get deployment {deployment_name} -n {namespace} -o json")

async def get_statefulset_status(statefulset_name: str, namespace: str) -> Dict[str, Any]:
    """Get status and config for a StatefulSet."""
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")

        sts = await apps_api.read_namespaced_stateful_set(statefulset_name, namespace)
        conditions = []
        for c in (sts.status.conditions or []):
            conditions.append({"type": c.type, "status": c.status, "reason": c.reason, "message": c.message})

        vct = []
        for claim in (sts.spec.volume_claim_templates or []):
            vct.append({
                "name": claim.metadata.name,
                "storage_class": claim.spec.storage_class_name,
                "access_modes": claim.spec.access_modes,
                "storage": claim.spec.resources.requests.get("storage") if claim.spec.resources and claim.spec.resources.requests else None,
            })

        data = {
            "name": sts.metadata.name,
            "namespace": sts.metadata.namespace,
            "replicas_desired": sts.spec.replicas,
            "replicas_ready": sts.status.ready_replicas or 0,
            "replicas_current": sts.status.current_replicas or 0,
            "replicas_updated": sts.status.updated_replicas or 0,
            "update_strategy": sts.spec.update_strategy.type if sts.spec.update_strategy else None,
            "service_name": sts.spec.service_name,
            "conditions": conditions,
            "volume_claim_templates": vct,
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_statefulset_status: {e}")
        return await kubectl_fallback(f"kubectl get statefulset {statefulset_name} -n {namespace} -o json")

async def list_statefulsets(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List all statefulsets in a namespace or across all namespaces."""
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            items = (await apps_api.list_namespaced_stateful_set(namespace)).items
        else:
            items = (await apps_api.list_stateful_set_for_all_namespaces()).items

        results = []
        for sts in items:
            results.append({
                "name": sts.metadata.name,
                "namespace": sts.metadata.namespace,
                "replicas_desired": sts.spec.replicas,
                "replicas_ready": sts.status.ready_replicas or 0,
            })

        return {"success": True, "data": {"statefulsets": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_statefulsets: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get statefulset {flag} -o json")

async def get_daemonset_status(daemonset_name: str, namespace: str) -> Dict[str, Any]:
    """Get status for a DaemonSet — desired vs ready counts, node selector."""
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")

        ds = await apps_api.read_namespaced_daemon_set(daemonset_name, namespace)
        data = {
            "name": ds.metadata.name,
            "namespace": ds.metadata.namespace,
            "desired": ds.status.desired_number_scheduled or 0,
            "current": ds.status.current_number_scheduled or 0,
            "ready": ds.status.number_ready or 0,
            "available": ds.status.number_available or 0,
            "misscheduled": ds.status.number_misscheduled or 0,
            "node_selector": ds.spec.template.spec.node_selector,
            "update_strategy": ds.spec.update_strategy.type if ds.spec.update_strategy else None,
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_daemonset_status: {e}")
        return await kubectl_fallback(f"kubectl get daemonset {daemonset_name} -n {namespace} -o json")

async def list_daemonsets(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List all daemonsets in a namespace or across all namespaces."""
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            items = (await apps_api.list_namespaced_daemon_set(namespace)).items
        else:
            items = (await apps_api.list_daemon_set_for_all_namespaces()).items

        results = []
        for ds in items:
            results.append({
                "name": ds.metadata.name,
                "namespace": ds.metadata.namespace,
                "desired": ds.status.desired_number_scheduled or 0,
                "ready": ds.status.number_ready or 0,
            })

        return {"success": True, "data": {"daemonsets": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_daemonsets: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get daemonset {flag} -o json")

async def get_job_status(job_name: str, namespace: str) -> Dict[str, Any]:
    """Get status for a Job — completions, conditions, duration."""
    try:
        batch_api = k8s_service._get_api("BatchV1Api")
        if not batch_api:
            raise Exception("Kubeconfig not loaded")

        job = await batch_api.read_namespaced_job(job_name, namespace)
        conditions = []
        for c in (job.status.conditions or []):
            conditions.append({"type": c.type, "status": c.status, "reason": c.reason, "message": c.message})

        duration = None
        if job.status.start_time and job.status.completion_time:
            duration = str(job.status.completion_time - job.status.start_time)

        data = {
            "name": job.metadata.name,
            "namespace": job.metadata.namespace,
            "completions": job.spec.completions,
            "parallelism": job.spec.parallelism,
            "backoff_limit": job.spec.backoff_limit,
            "active": job.status.active or 0,
            "succeeded": job.status.succeeded or 0,
            "failed": job.status.failed or 0,
            "conditions": conditions,
            "duration": duration,
            "start_time": str(job.status.start_time) if job.status.start_time else None,
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_job_status: {e}")
        return await kubectl_fallback(f"kubectl get job {job_name} -n {namespace} -o json")

async def list_jobs(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List all jobs in a namespace or across all namespaces."""
    try:
        batch_api = k8s_service._get_api("BatchV1Api")
        if not batch_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            items = (await batch_api.list_namespaced_job(namespace)).items
        else:
            items = (await batch_api.list_job_for_all_namespaces()).items

        results = []
        for job in items:
            status = "Running"
            if (job.status.succeeded or 0) >= (job.spec.completions or 1):
                status = "Complete"
            elif (job.status.failed or 0) > 0:
                status = "Failed"

            results.append({
                "name": job.metadata.name,
                "namespace": job.metadata.namespace,
                "status": status,
                "completions": f"{job.status.succeeded or 0}/{job.spec.completions or 1}",
                "age": str(job.metadata.creation_timestamp),
            })

        return {"success": True, "data": {"jobs": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_jobs: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get jobs {flag} -o json")

async def get_cronjob(cronjob_name: str, namespace: str) -> Dict[str, Any]:
    """Get a CronJob's schedule, last run, active jobs, and suspend status."""
    try:
        batch_api = k8s_service._get_api("BatchV1Api")
        if not batch_api:
            raise Exception("Kubeconfig not loaded")

        cj = await batch_api.read_namespaced_cron_job(cronjob_name, namespace)
        active_jobs = [{"name": ref.name} for ref in (cj.status.active or [])]

        data = {
            "name": cj.metadata.name,
            "namespace": cj.metadata.namespace,
            "schedule": cj.spec.schedule,
            "suspend": cj.spec.suspend,
            "concurrency_policy": cj.spec.concurrency_policy,
            "last_schedule_time": str(cj.status.last_schedule_time) if cj.status.last_schedule_time else None,
            "last_successful_time": str(cj.status.last_successful_time) if cj.status.last_successful_time else None,
            "active_jobs": active_jobs,
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_cronjob: {e}")
        return await kubectl_fallback(f"kubectl get cronjob {cronjob_name} -n {namespace} -o json")

async def list_cronjobs(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List all cronjobs in a namespace or across all namespaces."""
    try:
        batch_api = k8s_service._get_api("BatchV1Api")
        if not batch_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            items = (await batch_api.list_namespaced_cron_job(namespace)).items
        else:
            items = (await batch_api.list_cron_job_for_all_namespaces()).items

        results = []
        for cj in items:
            results.append({
                "name": cj.metadata.name,
                "namespace": cj.metadata.namespace,
                "schedule": cj.spec.schedule,
                "suspend": cj.spec.suspend,
                "last_schedule": str(cj.status.last_schedule_time) if cj.status.last_schedule_time else None,
            })

        return {"success": True, "data": {"cronjobs": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_cronjobs: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get cronjob {flag} -o json")

async def get_hpa(hpa_name: str, namespace: str) -> Dict[str, Any]:
    """Get HPA metrics, target ref, and scaling status."""
    try:
        autoscaling_api = k8s_service._get_api("AutoscalingV2Api")
        if not autoscaling_api:
            autoscaling_api = k8s_service._get_api("AutoscalingV1Api")
            if not autoscaling_api:
                raise Exception("Kubeconfig not loaded")

            hpa = await autoscaling_api.read_namespaced_horizontal_pod_autoscaler(hpa_name, namespace)
            data = {
                "name": hpa.metadata.name,
                "namespace": hpa.metadata.namespace,
                "target": f"{hpa.spec.scale_target_ref.kind}/{hpa.spec.scale_target_ref.name}",
                "min_replicas": hpa.spec.min_replicas,
                "max_replicas": hpa.spec.max_replicas,
                "current_replicas": hpa.status.current_replicas,
                "desired_replicas": hpa.status.desired_replicas,
                "current_cpu_utilization": hpa.status.current_cpu_utilization_percentage,
                "target_cpu_utilization": hpa.spec.target_cpu_utilization_percentage,
            }
            return {"success": True, "data": data, "error": None, "source": "k8s_client"}

        hpa = await autoscaling_api.read_namespaced_horizontal_pod_autoscaler(hpa_name, namespace)
        metrics = []
        for m in (hpa.spec.metrics or []):
            metric_info = {"type": m.type}
            if m.type == "Resource" and m.resource:
                metric_info["resource_name"] = m.resource.name
                if m.resource.target:
                    metric_info["target_type"] = m.resource.target.type
                    metric_info["target_value"] = m.resource.target.average_utilization or str(m.resource.target.average_value or m.resource.target.value)
            metrics.append(metric_info)

        current_metrics = []
        for m in (hpa.status.current_metrics or []):
            cm_info = {"type": m.type}
            if m.type == "Resource" and m.resource:
                cm_info["resource_name"] = m.resource.name
                if m.resource.current:
                    cm_info["current_value"] = m.resource.current.average_utilization or str(m.resource.current.average_value)
            current_metrics.append(cm_info)

        conditions = []
        for c in (hpa.status.conditions or []):
            conditions.append({"type": c.type, "status": c.status, "reason": c.reason, "message": c.message})

        data = {
            "name": hpa.metadata.name,
            "namespace": hpa.metadata.namespace,
            "target": f"{hpa.spec.scale_target_ref.kind}/{hpa.spec.scale_target_ref.name}",
            "min_replicas": hpa.spec.min_replicas,
            "max_replicas": hpa.spec.max_replicas,
            "current_replicas": hpa.status.current_replicas,
            "desired_replicas": hpa.status.desired_replicas,
            "metrics_spec": metrics,
            "current_metrics": current_metrics,
            "conditions": conditions,
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_hpa: {e}")
        return await kubectl_fallback(f"kubectl get hpa {hpa_name} -n {namespace} -o json")

async def list_hpa(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List all HPAs in a namespace or across all namespaces."""
    try:
        autoscaling_api = k8s_service._get_api("AutoscalingV1Api")
        if not autoscaling_api:
            raise Exception("Kubeconfig not loaded")

        if namespace:
            items = (await autoscaling_api.list_namespaced_horizontal_pod_autoscaler(namespace)).items
        else:
            items = (await autoscaling_api.list_horizontal_pod_autoscaler_for_all_namespaces()).items

        results = []
        for hpa in items:
            results.append({
                "name": hpa.metadata.name,
                "namespace": hpa.metadata.namespace,
                "target": f"{hpa.spec.scale_target_ref.kind}/{hpa.spec.scale_target_ref.name}",
                "min_replicas": hpa.spec.min_replicas,
                "max_replicas": hpa.spec.max_replicas,
                "current_replicas": hpa.status.current_replicas,
            })

        return {"success": True, "data": {"hpas": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_hpa: {e}")
        flag = f"-n {namespace}" if namespace else "-A"
        return await kubectl_fallback(f"kubectl get hpa {flag} -o json")

async def get_role_bindings(namespace: str) -> Dict[str, Any]:
    """Get all role bindings in a namespace — shows who can do what."""
    try:
        rbac_api = k8s_service._get_api("RbacAuthorizationV1Api")
        if not rbac_api:
            raise Exception("Kubeconfig not loaded")

        rbs = await rbac_api.list_namespaced_role_binding(namespace)
        results = []
        for rb in rbs.items:
            subjects = []
            for s in (rb.subjects or []):
                subjects.append({"kind": s.kind, "name": s.name, "namespace": s.namespace})
            results.append({
                "name": rb.metadata.name,
                "role_ref": {"kind": rb.role_ref.kind, "name": rb.role_ref.name},
                "subjects": subjects,
            })

        return {"success": True, "data": {"role_bindings": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_role_bindings: {e}")
        return await kubectl_fallback(f"kubectl get rolebinding -n {namespace} -o json")

async def get_service_account(name: str, namespace: str) -> Dict[str, Any]:
    """Get a service account's details — image pull secrets, annotations, mounted secrets."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        sa = await core_api.read_namespaced_service_account(name, namespace)
        data = {
            "name": sa.metadata.name,
            "namespace": sa.metadata.namespace,
            "annotations": sa.metadata.annotations,
            "automount_token": sa.automount_service_account_token,
            "image_pull_secrets": [s.name for s in (sa.image_pull_secrets or [])],
            "secrets": [s.name for s in (sa.secrets or [])],
        }
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_service_account: {e}")
        return await kubectl_fallback(f"kubectl get sa {name} -n {namespace} -o json")

async def get_resource_quota(namespace: str) -> Dict[str, Any]:
    """Get resource quotas in a namespace — hard limits vs current usage."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        quotas = await core_api.list_namespaced_resource_quota(namespace)
        results = []
        for q in quotas.items:
            hard = dict(q.status.hard) if q.status and q.status.hard else {}
            used = dict(q.status.used) if q.status and q.status.used else {}
            results.append({
                "name": q.metadata.name,
                "hard": hard,
                "used": used,
            })

        return {"success": True, "data": {"quotas": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_resource_quota: {e}")
        return await kubectl_fallback(f"kubectl get resourcequota -n {namespace} -o json")

async def get_limit_range(namespace: str) -> Dict[str, Any]:
    """Get limit ranges in a namespace — default limits/requests applied to new pods."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        lrs = await core_api.list_namespaced_limit_range(namespace)
        results = []
        for lr in lrs.items:
            limits = []
            for item in (lr.spec.limits or []):
                limits.append({
                    "type": item.type,
                    "default": dict(item.default) if item.default else None,
                    "default_request": dict(item.default_request) if item.default_request else None,
                    "max": dict(item.max) if item.max else None,
                    "min": dict(item.min) if item.min else None,
                })
            results.append({
                "name": lr.metadata.name,
                "limits": limits,
            })

        return {"success": True, "data": {"limit_ranges": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_limit_range: {e}")
        return await kubectl_fallback(f"kubectl get limitrange -n {namespace} -o json")

async def list_namespaces() -> Dict[str, Any]:
    """List all namespaces with status and labels."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")

        nss = await core_api.list_namespace()
        results = []
        for ns in nss.items:
            results.append({
                "name": ns.metadata.name,
                "status": ns.status.phase,
                "labels": ns.metadata.labels,
                "creation_timestamp": str(ns.metadata.creation_timestamp),
            })

        return {"success": True, "data": {"namespaces": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_namespaces: {e}")
        return await kubectl_fallback("kubectl get namespaces -o json")

async def get_pdb(namespace: str) -> Dict[str, Any]:
    """Get pod disruption budgets in a namespace."""
    try:
        policy_api = k8s_service._get_api("PolicyV1Api")
        if not policy_api:
            raise Exception("Kubeconfig not loaded")

        pdbs = await policy_api.list_namespaced_pod_disruption_budget(namespace)
        results = []
        for pdb in pdbs.items:
            results.append({
                "name": pdb.metadata.name,
                "min_available": str(pdb.spec.min_available) if pdb.spec.min_available is not None else None,
                "max_unavailable": str(pdb.spec.max_unavailable) if pdb.spec.max_unavailable is not None else None,
                "selector": pdb.spec.selector.match_labels if pdb.spec.selector else {},
                "current_healthy": pdb.status.current_healthy,
                "desired_healthy": pdb.status.desired_healthy,
                "disruptions_allowed": pdb.status.disruptions_allowed,
                "expected_pods": pdb.status.expected_pods,
            })

        return {"success": True, "data": {"pdbs": results, "total": len(results)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_pdb: {e}")
        return await kubectl_fallback(f"kubectl get pdb -n {namespace} -o json")

async def update_configmap(configmap_name: str, namespace: str, key: str, value: str, reason: str, confirmed: bool = False) -> Dict[str, Any]:
    """Update a single key in a ConfigMap. Requires user confirmation before applying."""
    if not confirmed:
        msg = (
            f"The AI wants to update ConfigMap '{configmap_name}' in namespace '{namespace}'.\n\n"
            f"Reason: {reason}\n\n"
            f"Change:\n  {key}: {value}\n\n"
            f"This will update the live ConfigMap. Pods that mount this ConfigMap may need a restart to pick up the new value.\n\n"
            f"Approve or cancel?"
        )
        return _pending_confirmation(
            "update_configmap",
            {"configmap_name": configmap_name, "namespace": namespace, "key": key, "value": value, "reason": reason},
            msg,
            "medium"
        )

    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            return await kubectl_fallback(f"kubectl patch configmap {configmap_name} -n {namespace} --type merge -p '{{\"data\":{{\"{key}\":\"{value}\"}}}}'")
        patch_body = {"data": {key: value}}
        await core_api.patch_namespaced_config_map(configmap_name, namespace, patch_body)
        return {"success": True, "data": f"ConfigMap '{configmap_name}' updated: {key}={value}", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in update_configmap: {e}")
        return await kubectl_fallback(f"kubectl patch configmap {configmap_name} -n {namespace} --type merge -p '{{\"data\":{{\"{key}\":\"{value}\"}}}}'")


# --- WRITE TOOLS (require user confirmation before execution) ---

def _pending_confirmation(tool_name: str, inputs: dict, message: str, risk_level: str) -> Dict[str, Any]:
    """Helper to return a pending confirmation request"""
    return {
        "success": True,
        "data": None,
        "error": None,
        "source": "k8s_client",
        "requires_confirmation": True,
        "pending_operation": {
            "tool_name": tool_name,
            "tool_inputs": inputs,
            "confirmation_message": message,
            "risk_level": risk_level
        }
    }

async def restart_pod(pod_name: str, namespace: str, reason: str, confirmed: bool = False) -> Dict[str, Any]:
    # Hard guard: restarting a pod with a broken image is pointless — it will come back with the same image.
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if core_api:
            pod = await core_api.read_namespaced_pod(pod_name, namespace)
            for cs in (pod.status.container_statuses or []):
                if cs.state.waiting and cs.state.waiting.reason in ("ImagePullBackOff", "ErrImagePull", "InvalidImageName"):
                    bad_image = cs.image or "unknown"
                    return {
                        "success": False,
                        "data": None,
                        "error": (
                            f"REFUSED: Pod '{pod_name}' is in {cs.state.waiting.reason}. Restarting will NOT fix this — "
                            f"the pod will come back with the same broken image ({bad_image}). "
                            f"You MUST call search_container_image('{bad_image}') to find a valid tag, "
                            f"then apply_manifest to patch the deployment image. Do not call restart_pod again."
                        ),
                        "source": "k8s_client",
                    }
    except Exception:
        pass  # If we can't check, fall through to normal flow

    if not confirmed:
        msg = f"The AI wants to restart pod '{pod_name}' in namespace '{namespace}'.\n\nReason: {reason}\n\nKubernetes will delete the pod and its ReplicaSet controller will create a fresh one. This will cause a brief interruption for any traffic this pod is serving.\n\nApprove or cancel?"
        return _pending_confirmation("restart_pod", {"pod_name": pod_name, "namespace": namespace, "reason": reason}, msg, "low")

    try:
        core_api = k8s_service._get_api("CoreV1Api")
        await core_api.delete_namespaced_pod(pod_name, namespace)
        return {"success": True, "data": f"Pod {pod_name} successfully deleted for restart.", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in restart_pod: {e}")
        return await kubectl_fallback(f"kubectl delete pod {pod_name} -n {namespace}")

async def rollback_deployment(deployment_name: str, namespace: str, target_revision: Optional[str], reason: str, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        target = target_revision or 'the previous version'
        msg = f"The AI wants to roll back deployment '{deployment_name}' in namespace '{namespace}' to revision {target}.\n\nReason: {reason}\n\nThis will replace the current pods with the previous image version. Target revision: {target}.\n\nApprove or cancel?"
        return _pending_confirmation("rollback_deployment", {"deployment_name": deployment_name, "namespace": namespace, "target_revision": target_revision, "reason": reason}, msg, "medium")

    try:
         # Kubernetes python client does not have a direct `rollout undo`,
         # normally we patch the annotation `deployment.kubernetes.io/revision` or call kubectl fallback.
         # Since that's complex without the exact RS details, let's use the kubectl fallback directly for rollback as it handles the logic gracefully
         cmd = f"kubectl rollout undo deployment/{deployment_name} -n {namespace}"
         if target_revision:
             cmd += f" --to-revision={target_revision}"
         return await kubectl_fallback(cmd)
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}

async def cordon_node(node_name: str, reason: str, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        msg = f"The AI wants to cordon node '{node_name}'.\n\nReason: {reason}\n\nCordoning marks the node as unschedulable — no new pods will be placed on it, but existing pods continue running. This is a safe, reversible action.\n\nApprove or cancel?"
        return _pending_confirmation("cordon_node", {"node_name": node_name, "reason": reason}, msg, "low")

    try:
        core_api = k8s_service._get_api("CoreV1Api")
        body = {"spec": {"unschedulable": True}}
        await core_api.patch_node(node_name, body)
        return {"success": True, "data": f"Node {node_name} cordoned successfully.", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in cordon_node: {e}")
        return await kubectl_fallback(f"kubectl cordon {node_name}")

async def uncordon_node(node_name: str, reason: str, confirmed: bool = False) -> Dict[str, Any]:
    """Mark a node as schedulable again (reverse of cordon)."""
    if not confirmed:
        msg = f"The AI wants to uncordon node '{node_name}'.\n\nReason: {reason}\n\nUncordoning marks the node as schedulable — new pods can be placed on it again. This is a safe, reversible action.\n\nApprove or cancel?"
        return _pending_confirmation("uncordon_node", {"node_name": node_name, "reason": reason}, msg, "low")

    try:
        core_api = k8s_service._get_api("CoreV1Api")
        body = {"spec": {"unschedulable": None}}
        await core_api.patch_node(node_name, body)
        return {"success": True, "data": f"Node {node_name} uncordoned successfully.", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in uncordon_node: {e}")
        return await kubectl_fallback(f"kubectl uncordon {node_name}")

async def drain_node(node_name: str, reason: str, ignore_daemonsets: bool = True, delete_emptydir_data: bool = False, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        msg = f"The AI wants to DRAIN node '{node_name}'.\n\nReason: {reason}\n\nDraining will evict ALL pods from this node. Pods managed by ReplicaSets and Deployments will be rescheduled on other nodes.\n\n⚠️ WARNING: Pods using emptyDir volumes will lose their local data if delete_emptydir_data is True.\n\n⚠️ This is a significant operation. Other nodes must have sufficient capacity to absorb these pods.\n\nApprove or cancel?"
        return _pending_confirmation("drain_node", {"node_name": node_name, "reason": reason, "ignore_daemonsets": ignore_daemonsets, "delete_emptydir_data": delete_emptydir_data}, msg, "high")

    # Drain node is complex to implement robustly purely in kubernetes-client
    # (cordon + eviction API per pod with timeouts), falling back to kubectl is vastly safer and more standard.
    cmd = f"kubectl drain {node_name}"
    if ignore_daemonsets:
        cmd += " --ignore-daemonsets"
    if delete_emptydir_data:
        cmd += " --delete-emptydir-data"

    return await kubectl_fallback(cmd)

async def patch_deployment_resources(deployment_name: str, namespace: str, container_name: str, reason: str,
                               cpu_request: Optional[str] = None, memory_request: Optional[str] = None,
                               cpu_limit: Optional[str] = None, memory_limit: Optional[str] = None,
                               confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        diff_str = f"cpu_request: {cpu_request}, memory_request: {memory_request}, cpu_limit: {cpu_limit}, memory_limit: {memory_limit}"
        msg = f"The AI wants to update resource limits for '{deployment_name}' container '{container_name}'.\n\nReason: {reason}\n\nChanges:\n{diff_str}\n\nThis will trigger a rolling restart of the deployment.\n\nApprove or cancel?"
        inputs = {"deployment_name": deployment_name, "namespace": namespace, "container_name": container_name, "reason": reason, "cpu_request": cpu_request, "memory_request": memory_request, "cpu_limit": cpu_limit, "memory_limit": memory_limit}
        return _pending_confirmation("patch_deployment_resources", inputs, msg, "medium")
        
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        dep = await apps_api.read_namespaced_deployment(deployment_name, namespace)

        container_found = False
        for i, c in enumerate(dep.spec.template.spec.containers):
            if c.name == container_name:
                container_found = True
                if not c.resources:
                    c.resources = {}
                if not c.resources.requests:
                    c.resources.requests = {}
                if not c.resources.limits:
                    c.resources.limits = {}
                    
                if cpu_request: c.resources.requests["cpu"] = cpu_request
                if memory_request: c.resources.requests["memory"] = memory_request
                if cpu_limit: c.resources.limits["cpu"] = cpu_limit
                if memory_limit: c.resources.limits["memory"] = memory_limit
                
                # Apply patch
                body = {"spec": {"template": {"spec": {"containers": [
                    {
                        "name": container_name,
                        "resources": {
                            "requests": c.resources.requests,
                            "limits": c.resources.limits
                        }
                    }
                ]}}}}
                await apps_api.patch_namespaced_deployment(deployment_name, namespace, body)
                break
                
        if not container_found:
            return {"success": False, "data": None, "error": f"Container {container_name} not found", "source": "k8s_client"}
            
        return {"success": True, "data": f"Deployment {deployment_name} resources patched.", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in patch_deployment_resources: {e}")
        # kubectl patch fallback is annoying to construct properly without full JSON.
        return {"success": False, "data": None, "error": f"Failed to patch resources: {e}", "source": "k8s_client"}

async def scale_deployment(deployment_name: str, namespace: str, replicas: int, reason: str, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        # Don't have exact current_replicas without doing a read, so just pass a placeholder or do a quick read
        try:
            dep_res = await get_deployment_status(deployment_name, namespace)
            curr = dep_res.get("data", {}).get("desired_replicas", "unknown") if dep_res.get("success") else "unknown"
        except:
            curr = "unknown"

        msg = f"The AI wants to scale deployment '{deployment_name}' from {curr} to {replicas} replicas.\n\nReason: {reason}\n\nApprove or cancel?"
        inputs = {"deployment_name": deployment_name, "namespace": namespace, "replicas": replicas, "reason": reason}
        return _pending_confirmation("scale_deployment", inputs, msg, "medium")

    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        body = {"spec": {"replicas": replicas}}
        await apps_api.patch_namespaced_deployment_scale(deployment_name, namespace, body)
        return {"success": True, "data": f"Successfully scaled {deployment_name} to {replicas}.", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in scale_deployment: {e}")
        return await kubectl_fallback(f"kubectl scale deployment {deployment_name} -n {namespace} --replicas={replicas}")


async def create_namespace(namespace: str, reason: str, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        msg = (
            f"The AI wants to create namespace '{namespace}'.\n\n"
            f"Reason: {reason}\n\n"
            f"This will create a new Kubernetes namespace. Approve or cancel?"
        )
        return _pending_confirmation("create_namespace", {"namespace": namespace, "reason": reason}, msg, "low")

    try:
        core_api = k8s_service._get_api("CoreV1Api")
        from kubernetes_asyncio.client import V1Namespace, V1ObjectMeta
        body = V1Namespace(metadata=V1ObjectMeta(name=namespace))
        await core_api.create_namespace(body)
        return {"success": True, "data": f"Namespace '{namespace}' created successfully.", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in create_namespace: {e}")
        return await kubectl_fallback(f"kubectl create namespace {namespace}")


async def deploy_application(
    name: str,
    image: str,
    namespace: str,
    reason: str,
    replicas: int = 1,
    port: int = 80,
    confirmed: bool = False,
) -> Dict[str, Any]:
    if not confirmed:
        msg = (
            f"The AI wants to deploy application '{name}' (image: {image}) "
            f"with {replicas} replica(s) in namespace '{namespace}'.\n\n"
            f"Reason: {reason}\n\n"
            f"This will create a Deployment and a ClusterIP Service. Approve or cancel?"
        )
        return _pending_confirmation(
            "deploy_application",
            {"name": name, "image": image, "namespace": namespace, "replicas": replicas, "port": port, "reason": reason},
            msg,
            "medium",
        )

    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        core_api = k8s_service._get_api("CoreV1Api")
        from kubernetes_asyncio.client import (
            V1Deployment, V1DeploymentSpec, V1LabelSelector,
            V1PodTemplateSpec, V1PodSpec, V1Container, V1ContainerPort,
            V1ObjectMeta, V1Service, V1ServiceSpec, V1ServicePort,
        )

        labels = {"app": name}
        container = V1Container(
            name=name,
            image=image,
            ports=[V1ContainerPort(container_port=port)],
        )
        deployment = V1Deployment(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            spec=V1DeploymentSpec(
                replicas=replicas,
                selector=V1LabelSelector(match_labels=labels),
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(labels=labels),
                    spec=V1PodSpec(containers=[container]),
                ),
            ),
        )
        await apps_api.create_namespaced_deployment(namespace=namespace, body=deployment)

        service = V1Service(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            spec=V1ServiceSpec(
                selector=labels,
                ports=[V1ServicePort(port=port, target_port=port)],
            ),
        )
        await core_api.create_namespaced_service(namespace=namespace, body=service)

        return {
            "success": True,
            "data": f"Deployment '{name}' and Service '{name}' created in namespace '{namespace}'.",
            "error": None,
            "source": "k8s_client",
        }
    except Exception as e:
        logger.error(f"k8s_client error in deploy_application: {e}")
        return await kubectl_fallback(
            f"kubectl create deployment {name} --image={image} --replicas={replicas} -n {namespace}"
        )


async def delete_namespace(namespace: str, reason: str, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        msg = (
            f"The AI wants to PERMANENTLY DELETE namespace '{namespace}' and ALL resources inside it.\n\n"
            f"Reason: {reason}\n\n"
            f"⚠️ This will destroy every Deployment, Pod, Service, ConfigMap, Secret, and PVC in this namespace. This action CANNOT be undone.\n\n"
            f"Approve or cancel?"
        )
        return _pending_confirmation("delete_namespace", {"namespace": namespace, "reason": reason}, msg, "high")

    try:
        core_api = k8s_service._get_api("CoreV1Api")
        await core_api.delete_namespace(namespace)
        return {"success": True, "data": f"Namespace '{namespace}' deleted successfully.", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in delete_namespace: {e}")
        return await kubectl_fallback(f"kubectl delete namespace {namespace}")


async def delete_deployment(deployment_name: str, namespace: str, reason: str, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        msg = (
            f"The AI wants to PERMANENTLY DELETE deployment '{deployment_name}' in namespace '{namespace}'.\n\n"
            f"Reason: {reason}\n\n"
            f"⚠️ This will remove the Deployment and all its managed pods. This action cannot be undone without re-applying the original manifest.\n\n"
            f"Approve or cancel?"
        )
        return _pending_confirmation("delete_deployment", {"deployment_name": deployment_name, "namespace": namespace, "reason": reason}, msg, "high")

    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        await apps_api.delete_namespaced_deployment(deployment_name, namespace)
        return {"success": True, "data": f"Deployment '{deployment_name}' in namespace '{namespace}' deleted successfully.", "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in delete_deployment: {e}")
        return await kubectl_fallback(f"kubectl delete deployment {deployment_name} -n {namespace}")


async def describe_pod(pod_name: str, namespace=None):
    """Get full describe output for a pod — equivalent to kubectl describe pod."""
    try:
        if namespace is None:
            namespace = await _find_pod_namespace(pod_name) or "default"
        data = await k8s_service.get_pod_details(namespace, pod_name)
        return {"success": True, "data": data, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in describe_pod: {e}")
        ns_flag = f" -n {namespace}" if namespace else ""
        return await kubectl_fallback(f"kubectl describe pod {pod_name}{ns_flag}")


async def list_deployments(namespace=None):
    """List all deployments in a namespace (or all namespaces if omitted)."""
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")
        if namespace:
            result = await apps_api.list_namespaced_deployment(namespace)
        else:
            result = await apps_api.list_deployment_for_all_namespaces()
        deployments = [
            {
                "name": d.metadata.name,
                "namespace": d.metadata.namespace,
                "replicas": d.spec.replicas,
                "ready_replicas": d.status.ready_replicas or 0,
                "available_replicas": d.status.available_replicas or 0,
                "updated_replicas": d.status.updated_replicas or 0,
            }
            for d in result.items
        ]
        return {"success": True, "data": {"deployments": deployments, "count": len(deployments)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_deployments: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_resource_yaml(kind: str, name: str, namespace=None):
    """Get the full YAML manifest of any Kubernetes resource."""
    ns_flag = f" -n {namespace}" if namespace else ""
    return await kubectl_fallback(f"kubectl get {kind} {name}{ns_flag} -o yaml")


async def exec_pod(pod_name: str, namespace: str, command: str, container_name=None):
    """Execute a diagnostic command inside a running pod container. Use for live network checks (nslookup, curl), env inspection (env | grep VAR), or file reads."""
    try:
        from kubernetes_asyncio.stream import WsApiClient
        from kubernetes_asyncio import client

        exec_command = ["/bin/sh", "-c", command]
        kwargs = {
            "name": pod_name,
            "namespace": namespace,
            "command": exec_command,
            "stderr": True,
            "stdin": False,
            "stdout": True,
            "tty": False,
        }
        if container_name:
            kwargs["container"] = container_name

        async with WsApiClient() as ws_api:
            v1 = client.CoreV1Api(api_client=ws_api)
            output = await asyncio.wait_for(
                v1.connect_get_namespaced_pod_exec(**kwargs),
                timeout=30,
            )

        return {
            "success": True,
            "data": {"pod": pod_name, "namespace": namespace, "command": command, "output": output},
            "error": None,
            "source": "k8s_client",
        }
    except asyncio.TimeoutError:
        return {"success": False, "data": None, "error": "exec timed out after 30s", "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in exec_pod: {e}")
        return await kubectl_fallback(f"kubectl exec {pod_name} -n {namespace} -- sh -c '{command}'")


_METRICS_GROUP = "metrics.k8s.io"
_METRICS_VERSION = "v1beta1"


async def get_pod_metrics(pod_name: str, namespace: str) -> Dict[str, Any]:
    """Get actual CPU and memory usage for a specific pod from metrics-server."""
    try:
        custom_api = k8s_service._get_api("CustomObjectsApi")
        if not custom_api:
            raise Exception("Kubeconfig not loaded")
        data = await custom_api.get_namespaced_custom_object(
            group=_METRICS_GROUP, version=_METRICS_VERSION,
            namespace=namespace, plural="pods", name=pod_name,
        )
        containers = [
            {"name": c["name"], "cpu": c["usage"]["cpu"], "memory": c["usage"]["memory"]}
            for c in data.get("containers", [])
        ]
        return {
            "success": True,
            "data": {"pod": data["metadata"]["name"], "namespace": data["metadata"]["namespace"], "containers": containers},
            "error": None,
            "source": "k8s_client",
        }
    except ApiException as e:
        if e.status == 404:
            return {"success": False, "data": None, "error": "metrics-server not installed or pod metrics not available yet", "source": "k8s_client"}
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_pod_metrics: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_node_metrics(node_name: str) -> Dict[str, Any]:
    """Get actual CPU and memory usage for a specific node from metrics-server."""
    try:
        custom_api = k8s_service._get_api("CustomObjectsApi")
        if not custom_api:
            raise Exception("Kubeconfig not loaded")
        data = await custom_api.get_cluster_custom_object(
            group=_METRICS_GROUP, version=_METRICS_VERSION,
            plural="nodes", name=node_name,
        )
        return {
            "success": True,
            "data": {"node": data["metadata"]["name"], "cpu": data["usage"]["cpu"], "memory": data["usage"]["memory"]},
            "error": None,
            "source": "k8s_client",
        }
    except ApiException as e:
        if e.status == 404:
            return {"success": False, "data": None, "error": "metrics-server not available or node metrics not found", "source": "k8s_client"}
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_node_metrics: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_top_pods(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List CPU and memory usage for all pods in a namespace (or all namespaces). Equivalent to kubectl top pods."""
    try:
        custom_api = k8s_service._get_api("CustomObjectsApi")
        if not custom_api:
            raise Exception("Kubeconfig not loaded")
        if namespace:
            data = await custom_api.list_namespaced_custom_object(
                group=_METRICS_GROUP, version=_METRICS_VERSION, namespace=namespace, plural="pods",
            )
        else:
            data = await custom_api.list_cluster_custom_object(
                group=_METRICS_GROUP, version=_METRICS_VERSION, plural="pods",
            )
        pods = [
            {
                "name": item["metadata"]["name"],
                "namespace": item["metadata"]["namespace"],
                "containers": [
                    {"name": c["name"], "cpu": c["usage"]["cpu"], "memory": c["usage"]["memory"]}
                    for c in item.get("containers", [])
                ],
            }
            for item in data.get("items", [])
        ]
        return {"success": True, "data": {"pods": pods, "count": len(pods)}, "error": None, "source": "k8s_client"}
    except ApiException as e:
        if e.status == 404:
            return {"success": False, "data": None, "error": "metrics-server not installed", "source": "k8s_client"}
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_top_pods: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def list_pvcs(namespace=None):
    """List PersistentVolumeClaims — shows phase (Bound/Pending/Lost), capacity, and storage class."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")
        if namespace:
            result = await core_api.list_namespaced_persistent_volume_claim(namespace)
        else:
            result = await core_api.list_persistent_volume_claim_for_all_namespaces()
        pvcs = [
            {
                "name": pvc.metadata.name,
                "namespace": pvc.metadata.namespace,
                "phase": pvc.status.phase,
                "capacity": pvc.status.capacity.get("storage") if pvc.status.capacity else None,
                "requested": pvc.spec.resources.requests.get("storage") if pvc.spec.resources else None,
                "storage_class": pvc.spec.storage_class_name,
                "access_modes": pvc.spec.access_modes,
            }
            for pvc in result.items
        ]
        return {"success": True, "data": {"pvcs": pvcs, "count": len(pvcs)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_pvcs: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_pv(pv_name: str):
    """Get details of a PersistentVolume — phase, capacity, reclaim policy, bound claim."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")
        pv = await core_api.read_persistent_volume(pv_name)
        claim = None
        if pv.spec.claim_ref:
            claim = {"name": pv.spec.claim_ref.name, "namespace": pv.spec.claim_ref.namespace}
        return {
            "success": True,
            "data": {
                "name": pv.metadata.name,
                "phase": pv.status.phase,
                "capacity": pv.spec.capacity.get("storage") if pv.spec.capacity else None,
                "access_modes": pv.spec.access_modes,
                "reclaim_policy": pv.spec.persistent_volume_reclaim_policy,
                "storage_class": pv.spec.storage_class_name,
                "bound_claim": claim,
            },
            "error": None,
            "source": "k8s_client",
        }
    except ApiException as e:
        if e.status == 404:
            return {"success": False, "data": None, "error": f"PersistentVolume '{pv_name}' not found", "source": "k8s_client"}
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_pv: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def list_pvs():
    """List all PersistentVolumes in the cluster with their phase and bound claims."""
    try:
        core_api = k8s_service._get_api("CoreV1Api")
        if not core_api:
            raise Exception("Kubeconfig not loaded")
        result = await core_api.list_persistent_volume()
        pvs = [
            {
                "name": pv.metadata.name,
                "phase": pv.status.phase,
                "capacity": pv.spec.capacity.get("storage") if pv.spec.capacity else None,
                "storage_class": pv.spec.storage_class_name,
                "reclaim_policy": pv.spec.persistent_volume_reclaim_policy,
                "bound_to": f"{pv.spec.claim_ref.namespace}/{pv.spec.claim_ref.name}" if pv.spec.claim_ref else None,
            }
            for pv in result.items
        ]
        return {"success": True, "data": {"pvs": pvs, "count": len(pvs)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_pvs: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_storage_class(name: str):
    """Get details of a StorageClass — provisioner, reclaim policy, binding mode."""
    try:
        storage_api = k8s_service._get_api("StorageV1Api")
        if not storage_api:
            raise Exception("Kubeconfig not loaded")
        sc = await storage_api.read_storage_class(name)
        annotations = sc.metadata.annotations or {}
        return {
            "success": True,
            "data": {
                "name": sc.metadata.name,
                "provisioner": sc.provisioner,
                "reclaim_policy": sc.reclaim_policy,
                "volume_binding_mode": sc.volume_binding_mode,
                "is_default": annotations.get("storageclass.kubernetes.io/is-default-class") == "true",
                "allow_volume_expansion": sc.allow_volume_expansion,
            },
            "error": None,
            "source": "k8s_client",
        }
    except ApiException as e:
        if e.status == 404:
            return {"success": False, "data": None, "error": f"StorageClass '{name}' not found", "source": "k8s_client"}
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_storage_class: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def list_storage_classes():
    """List all StorageClasses in the cluster with provisioner and default flag."""
    try:
        storage_api = k8s_service._get_api("StorageV1Api")
        if not storage_api:
            raise Exception("Kubeconfig not loaded")
        result = await storage_api.list_storage_class()
        classes = [
            {
                "name": sc.metadata.name,
                "provisioner": sc.provisioner,
                "reclaim_policy": sc.reclaim_policy,
                "volume_binding_mode": sc.volume_binding_mode,
                "is_default": (sc.metadata.annotations or {}).get("storageclass.kubernetes.io/is-default-class") == "true",
            }
            for sc in result.items
        ]
        return {"success": True, "data": {"storage_classes": classes, "count": len(classes)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in list_storage_classes: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def patch_deployment_env(
    deployment_name: str,
    namespace: str,
    container_name: str,
    env_var: str,
    value: str,
    reason: str,
    confirmed: bool = False,
):
    """Update a single environment variable in a deployment container. Use to fix misconfigured credentials, URLs, or feature flags."""
    if not confirmed:
        msg = (
            f"The AI wants to update env var `{env_var}` in deployment '{deployment_name}' "
            f"(container: {container_name}) in namespace '{namespace}'.\n\n"
            f"Reason: {reason}\n\n"
            f"⚠️ This will trigger a rolling restart of the deployment pods.\n\n"
            f"Approve or cancel?"
        )
        return _pending_confirmation(
            "patch_deployment_env",
            {"deployment_name": deployment_name, "namespace": namespace, "container_name": container_name, "env_var": env_var, "value": "***", "reason": reason},
            msg, "high",
        )
    try:
        apps_api = k8s_service._get_api("AppsV1Api")
        if not apps_api:
            raise Exception("Kubeconfig not loaded")
        deployment = await apps_api.read_namespaced_deployment(deployment_name, namespace)
        container = next(
            (c for c in deployment.spec.template.spec.containers if c.name == container_name), None
        )
        if container is None:
            return {"success": False, "data": None, "error": f"Container '{container_name}' not found in deployment '{deployment_name}'", "source": "k8s_client"}
        env_list = container.env or []
        existing = next((e for e in env_list if e.name == env_var), None)
        if existing:
            existing.value = value
            existing.value_from = None
        else:
            from kubernetes_asyncio.client import V1EnvVar
            env_list.append(V1EnvVar(name=env_var, value=value))
        container.env = env_list
        await apps_api.patch_namespaced_deployment(deployment_name, namespace, deployment)
        return {
            "success": True,
            "data": f"Env var '{env_var}' updated in deployment '{deployment_name}/{container_name}' in namespace '{namespace}'. Rolling restart triggered.",
            "error": None,
            "source": "k8s_client",
        }
    except Exception as e:
        logger.error(f"k8s_client error in patch_deployment_env: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def apply_manifest(manifest_yaml: str, reason: str, confirmed: bool = False):
    """Apply a raw YAML manifest to the cluster — equivalent to kubectl apply -f."""
    if not confirmed:
        preview = manifest_yaml[:500] + ("..." if len(manifest_yaml) > 500 else "")
        msg = (
            f"The AI wants to apply a Kubernetes manifest.\n\n"
            f"Reason: {reason}\n\n"
            f"Manifest preview:\n```yaml\n{preview}\n```\n\n"
            f"⚠️ This will create or update Kubernetes resources. Review carefully before approving.\n\n"
            f"Approve or cancel?"
        )
        return _pending_confirmation("apply_manifest", {"manifest_yaml": manifest_yaml[:200], "reason": reason}, msg, "high")
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(manifest_yaml)
            tmp_path = f.name
        env_override, tmp_kc = _safe_kubectl_env()
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                ["kubectl", "apply", "-f", tmp_path],
                capture_output=True, text=True, timeout=30,
                env=env_override if env_override else None,
            )
            if proc.returncode == 0:
                return {"success": True, "data": proc.stdout.strip(), "error": None, "source": "kubectl"}
            return {"success": False, "data": None, "error": proc.stderr.strip(), "source": "kubectl"}
        finally:
            os.unlink(tmp_path)
            if tmp_kc:
                try:
                    os.unlink(tmp_kc)
                except OSError:
                    pass
    except Exception as e:
        logger.error(f"k8s_client error in apply_manifest: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_roles(namespace: str) -> Dict[str, Any]:
    """List RBAC Roles in a namespace with their rules (resources and verbs)."""
    try:
        rbac_api = k8s_service._get_api("RbacAuthorizationV1Api")
        if not rbac_api:
            raise Exception("Kubeconfig not loaded")
        result = await rbac_api.list_namespaced_role(namespace)
        roles = [
            {
                "name": role.metadata.name,
                "namespace": role.metadata.namespace,
                "rules": [
                    {"api_groups": r.api_groups, "resources": r.resources, "verbs": r.verbs}
                    for r in (role.rules or [])
                ],
            }
            for role in result.items
        ]
        return {"success": True, "data": {"roles": roles, "count": len(roles)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_roles: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_cluster_roles() -> Dict[str, Any]:
    """List ClusterRoles in the cluster. Use to understand cluster-wide permissions."""
    try:
        rbac_api = k8s_service._get_api("RbacAuthorizationV1Api")
        if not rbac_api:
            raise Exception("Kubeconfig not loaded")
        result = await rbac_api.list_cluster_role()
        cluster_roles = [
            {
                "name": cr.metadata.name,
                "rules_count": len(cr.rules) if cr.rules else 0,
                "rules": [
                    {"api_groups": r.api_groups, "resources": r.resources, "verbs": r.verbs}
                    for r in (cr.rules or [])
                ],
            }
            for cr in result.items
        ]
        return {"success": True, "data": {"cluster_roles": cluster_roles, "count": len(cluster_roles)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_cluster_roles: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


async def get_cluster_role_bindings() -> Dict[str, Any]:
    """List ClusterRoleBindings — shows which users/groups/service-accounts have cluster-wide roles."""
    try:
        rbac_api = k8s_service._get_api("RbacAuthorizationV1Api")
        if not rbac_api:
            raise Exception("Kubeconfig not loaded")
        result = await rbac_api.list_cluster_role_binding()
        bindings = [
            {
                "name": crb.metadata.name,
                "role_ref": {"kind": crb.role_ref.kind, "name": crb.role_ref.name},
                "subjects": [
                    {"kind": s.kind, "name": s.name, "namespace": s.namespace}
                    for s in (crb.subjects or [])
                ],
            }
            for crb in result.items
        ]
        return {"success": True, "data": {"cluster_role_bindings": bindings, "count": len(bindings)}, "error": None, "source": "k8s_client"}
    except Exception as e:
        logger.error(f"k8s_client error in get_cluster_role_bindings: {e}")
        return {"success": False, "data": None, "error": str(e), "source": "k8s_client"}


def search_topology_tool(query: str, context: Optional[str] = None) -> Dict[str, Any]:
    """
    Search the pre-built cluster topology graph.
    Returns a subgraph showing the matched resource and everything connected to it
    (2 hops in each direction). Use when you need to understand relationships:
    which pods does a service select, what configmaps does a deployment mount,
    what does this PVC bind to.
    """
    try:
        from app.services.topology_service import topology_service
        from app.services.k8s_service import k8s_service
        ctx = context or k8s_service.default_context
        result = topology_service.search_topology(query=query, context=ctx)
        return {"success": True, "data": result, "error": None, "source": "topology"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "topology"}


def get_blast_radius_tool(kind: str, name: str, namespace: str,
                          context: Optional[str] = None) -> Dict[str, Any]:
    """
    Return all downstream resources that depend on the given resource.
    Use when you want to know 'what breaks if this Service/Deployment/PVC is gone?'
    kind: e.g. 'Service', 'Deployment', 'ConfigMap'
    """
    try:
        from app.services.topology_service import topology_service
        from app.services.k8s_service import k8s_service
        ctx = context or k8s_service.default_context
        result = topology_service.get_blast_radius(kind=kind, name=name, namespace=namespace, context=ctx)
        return {"success": True, "data": result, "error": None, "source": "topology"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "topology"}


async def diagnose_pod_tool(pod_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a full 10-category diagnostic sweep on a pod.
    Checks: container state, probes, networking, config refs, storage,
    resources, scheduling, RBAC, workload health, security context.
    Returns a structured findings report. Use this FIRST for any vague
    troubleshooting query before calling targeted tools.
    """
    try:
        from app.services.diagnostic_service import diagnostic_engine
        result = await diagnostic_engine.diagnose_pod(pod_name=pod_name, namespace=namespace)
        return {"success": True, "data": result, "error": None, "source": "diagnostic_engine"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "diagnostic_engine"}


async def diagnose_service_tool(service_name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a full diagnostic sweep starting from a service name.
    Resolves pods via selector, runs diagnose_pod on each (up to 3),
    then checks service-level issues: endpoint count, ingress backend port.
    Use when the user mentions a service name but not a specific pod.
    """
    try:
        from app.services.diagnostic_service import diagnostic_engine
        result = await diagnostic_engine.diagnose_service(service_name=service_name, namespace=namespace)
        return {"success": True, "data": result, "error": None, "source": "diagnostic_engine"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "diagnostic_engine"}
