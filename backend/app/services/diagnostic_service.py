from dataclasses import dataclass
from typing import List, Optional
import logging

from app.services.k8s_service import k8s_service
from kubernetes_asyncio.client.rest import ApiException

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    category: str
    severity: str   # "critical" | "warning" | "info"
    check: str
    message: str
    fix_hint: str


def _parse_k8s_memory(value: str) -> Optional[int]:
    import re
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
             "K": 1000, "M": 1000**2, "G": 1000**3}
    match = re.match(r'^(\d+(?:\.\d+)?)(.*)', str(value))
    if not match:
        return None
    num, unit = match.groups()
    return int(float(num) * units.get(unit.strip(), 1))


def _parse_quantity(value: str) -> float:
    value = str(value).strip()
    if value.endswith("m"):
        return float(value[:-1]) / 1000
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3,
             "K": 1000, "M": 1000**2, "G": 1000**3}
    for unit, mult in units.items():
        if value.endswith(unit):
            return float(value[:-len(unit)]) * mult
    try:
        return float(value)
    except ValueError:
        return 0.0


class DiagnosticEngine:

    CATEGORIES = [
        "container_state", "probes", "networking", "config_refs",
        "storage", "resources", "scheduling", "rbac",
        "workload_health", "security_context",
    ]

    def _format_findings(
        self, resource_label: str, findings: List[Finding], categories_checked: List[str]
    ) -> str:
        lines = [
            f"DIAGNOSIS: {resource_label}",
            f"Checked: {len(categories_checked)} categories | Issues found: {len(findings)}",
        ]
        if findings:
            lines.append("")
            order = {"critical": 0, "warning": 1, "info": 2}
            for f in sorted(findings, key=lambda x: order.get(x.severity, 9)):
                lines.append(f"[{f.severity.upper()}] {f.category} / {f.check}")
                lines.append(f"  {f.message}")
                lines.append(f"  Fix: {f.fix_hint}")
                lines.append("")
        clean = [c for c in categories_checked if not any(fi.category == c for fi in findings)]
        if clean:
            lines.append(f"Clean: {', '.join(clean)}")
        return "\n".join(lines).strip()

    def _check_container_state(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            for cs in (pod.status.container_statuses or []):
                state = cs.state
                if not state or not state.waiting:
                    continue
                reason = state.waiting.reason or ""
                msg = state.waiting.message or ""
                if reason in ("ImagePullBackOff", "ErrImagePull"):
                    findings.append(Finding(
                        category="container_state", severity="critical", check="image_pull_failure",
                        message=f"Container '{cs.name}' cannot pull image '{cs.image}': {msg or reason}",
                        fix_hint=(
                            f"Verify image '{cs.image}' exists and is accessible. "
                            "Check imagePullSecrets if it's a private registry."
                        ),
                    ))
                elif reason == "CrashLoopBackOff":
                    restarts = cs.restart_count or 0
                    findings.append(Finding(
                        category="container_state", severity="critical", check="crash_loop",
                        message=f"Container '{cs.name}' is in CrashLoopBackOff ({restarts} restarts)",
                        fix_hint="Call get_pod_logs to see the crash reason",
                    ))
                elif reason == "OOMKilled":
                    findings.append(Finding(
                        category="container_state", severity="critical", check="oom_killed",
                        message=f"Container '{cs.name}' was OOMKilled — memory limit too low",
                        fix_hint="Increase memory limit via patch_deployment_resources",
                    ))
                elif reason in ("ContainerCreating", "PodInitializing"):
                    pass
                elif reason:
                    findings.append(Finding(
                        category="container_state", severity="warning", check="waiting",
                        message=f"Container '{cs.name}' waiting: {reason} — {msg}",
                        fix_hint="Call get_pod_events for more details",
                    ))
            for cs in (pod.status.init_container_statuses or []):
                state = cs.state
                if not state or not state.waiting:
                    continue
                reason = state.waiting.reason or ""
                msg = state.waiting.message or ""
                if reason in ("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff"):
                    findings.append(Finding(
                        category="container_state", severity="critical",
                        check="init_container_failure",
                        message=f"Init container '{cs.name}' failing: {reason} — {msg}",
                        fix_hint="Init containers must complete successfully before main containers start",
                    ))
        except Exception as e:
            logger.warning(f"container_state check failed: {e}")
        return findings

    def _check_probes(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            for cs in (pod.status.container_statuses or []):
                if not cs.ready and (pod.status.phase == "Running"):
                    container_spec = next(
                        (c for c in (pod.spec.containers or []) if c.name == cs.name), None
                    )
                    if container_spec and not container_spec.readiness_probe:
                        findings.append(Finding(
                            category="probes", severity="info", check="no_readiness_probe",
                            message=f"Container '{cs.name}' is not ready but has no readiness probe",
                            fix_hint="Add a readiness probe to detect when the app is ready",
                        ))
        except Exception as e:
            logger.warning(f"probes check failed: {e}")
        return findings

    async def _check_networking(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            net_api = k8s_service._get_api("NetworkingV1Api")
            if not core_api:
                return []
            ns = pod.metadata.namespace
            pod_labels = pod.metadata.labels or {}
            container_ports: dict = {}
            for container in (pod.spec.containers or []):
                for p in (container.ports or []):
                    container_ports[p.container_port] = container.name

            try:
                svc_list = await core_api.list_namespaced_service(ns)
                services = svc_list.items
            except Exception:
                return findings

            for svc in services:
                selector = svc.spec.selector or {}
                if not selector:
                    continue
                if not all(pod_labels.get(k) == v for k, v in selector.items()):
                    continue
                svc_name = svc.metadata.name

                for port in (svc.spec.ports or []):
                    target = port.target_port
                    try:
                        target_int = int(str(target))
                    except (ValueError, TypeError):
                        continue
                    if container_ports and target_int not in container_ports:
                        findings.append(Finding(
                            category="networking", severity="critical", check="port_mismatch",
                            message=(
                                f"Service '{svc_name}' targetPort={target_int} but pod "
                                f"containerPorts are {list(container_ports.keys())}"
                            ),
                            fix_hint=(
                                f"kubectl patch svc {svc_name} -n {ns} -p "
                                f"'{{\"spec\":{{\"ports\":[{{\"port\":{port.port},"
                                f"\"targetPort\":{list(container_ports.keys())[0]}}}]}}}}'"
                            ),
                        ))

                try:
                    ep = await core_api.read_namespaced_endpoints(svc_name, ns)
                    total_ready = sum(len(s.addresses or []) for s in (ep.subsets or []))
                    total_not_ready = sum(len(s.not_ready_addresses or []) for s in (ep.subsets or []))
                    if total_ready == 0 and total_not_ready > 0:
                        findings.append(Finding(
                            category="networking", severity="critical", check="endpoints_not_ready",
                            message=(
                                f"Service '{svc_name}' has {total_not_ready} pods in "
                                f"not_ready_addresses — all traffic will fail"
                            ),
                            fix_hint="Check readiness probe configuration and pod logs",
                        ))
                except Exception:
                    pass

                if net_api:
                    try:
                        ing_list = await net_api.list_namespaced_ingress(ns)
                        svc_ports = [p.port for p in (svc.spec.ports or [])]
                        for ing in ing_list.items:
                            for rule in (ing.spec.rules or []):
                                for path in (rule.http.paths if rule.http else []):
                                    backend = path.backend
                                    if not (backend and backend.service
                                            and backend.service.name == svc_name):
                                        continue
                                    ing_port = (backend.service.port.number
                                                if backend.service.port else None)
                                    if ing_port and svc_ports and ing_port not in svc_ports:
                                        findings.append(Finding(
                                            category="networking", severity="critical",
                                            check="ingress_port_mismatch",
                                            message=(
                                                f"Ingress '{ing.metadata.name}' routes to "
                                                f"{svc_name}:{ing_port} but service exposes "
                                                f"ports {svc_ports}"
                                            ),
                                            fix_hint=f"Update ingress backend port to one of {svc_ports}",
                                        ))
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"networking check failed: {e}")
        return findings

    async def _check_config_refs(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            if not core_api:
                return []
            ns = pod.metadata.namespace

            for container in (pod.spec.containers or []):
                for env_from in (container.env_from or []):
                    if env_from.config_map_ref:
                        name = env_from.config_map_ref.name
                        try:
                            await core_api.read_namespaced_config_map(name, ns)
                        except ApiException as e:
                            if e.status == 404:
                                findings.append(Finding(
                                    category="config_refs", severity="critical",
                                    check="missing_configmap",
                                    message=(f"Container '{container.name}' envFrom references "
                                             f"ConfigMap '{name}' which does not exist in namespace '{ns}'"),
                                    fix_hint=f"kubectl create configmap {name} -n {ns} --from-literal=key=value",
                                ))
                    if env_from.secret_ref:
                        name = env_from.secret_ref.name
                        try:
                            await core_api.read_namespaced_secret(name, ns)
                        except ApiException as e:
                            if e.status == 404:
                                findings.append(Finding(
                                    category="config_refs", severity="critical",
                                    check="missing_secret",
                                    message=(f"Container '{container.name}' envFrom references "
                                             f"Secret '{name}' which does not exist in namespace '{ns}'"),
                                    fix_hint=f"kubectl create secret generic {name} -n {ns} --from-literal=key=value",
                                ))

                for env_var in (container.env or []):
                    if not env_var.value_from:
                        continue
                    if env_var.value_from.config_map_key_ref:
                        ref = env_var.value_from.config_map_key_ref
                        try:
                            cm = await core_api.read_namespaced_config_map(ref.name, ns)
                            if ref.key not in (cm.data or {}):
                                findings.append(Finding(
                                    category="config_refs", severity="critical",
                                    check="missing_configmap_key",
                                    message=(f"Container '{container.name}' env '{env_var.name}' "
                                             f"references key '{ref.key}' in ConfigMap '{ref.name}' "
                                             f"but that key does not exist"),
                                    fix_hint=f"Add key '{ref.key}' to ConfigMap '{ref.name}'",
                                ))
                        except ApiException as e:
                            if e.status == 404:
                                findings.append(Finding(
                                    category="config_refs", severity="critical",
                                    check="missing_configmap",
                                    message=(f"Container '{container.name}' env '{env_var.name}' "
                                             f"references ConfigMap '{ref.name}' which does not exist"),
                                    fix_hint=f"Create ConfigMap '{ref.name}' in namespace '{ns}'",
                                ))
                    if env_var.value_from.secret_key_ref:
                        ref = env_var.value_from.secret_key_ref
                        try:
                            secret = await core_api.read_namespaced_secret(ref.name, ns)
                            if ref.key not in (secret.data or {}):
                                findings.append(Finding(
                                    category="config_refs", severity="critical",
                                    check="missing_secret_key",
                                    message=(f"Container '{container.name}' env '{env_var.name}' "
                                             f"references key '{ref.key}' in Secret '{ref.name}' "
                                             f"but that key does not exist"),
                                    fix_hint=f"Add key '{ref.key}' to Secret '{ref.name}'",
                                ))
                        except ApiException as e:
                            if e.status == 404:
                                findings.append(Finding(
                                    category="config_refs", severity="critical",
                                    check="missing_secret",
                                    message=(f"Container '{container.name}' env '{env_var.name}' "
                                             f"references Secret '{ref.name}' which does not exist"),
                                    fix_hint=f"Create Secret '{ref.name}' in namespace '{ns}'",
                                ))

            for vol in (pod.spec.volumes or []):
                if vol.config_map:
                    name = vol.config_map.name
                    try:
                        await core_api.read_namespaced_config_map(name, ns)
                    except ApiException as e:
                        if e.status == 404:
                            findings.append(Finding(
                                category="config_refs", severity="critical",
                                check="missing_configmap",
                                message=f"Volume '{vol.name}' references ConfigMap '{name}' which does not exist",
                                fix_hint=f"Create ConfigMap '{name}' in namespace '{ns}'",
                            ))
                if vol.secret:
                    name = vol.secret.secret_name
                    try:
                        await core_api.read_namespaced_secret(name, ns)
                    except ApiException as e:
                        if e.status == 404:
                            findings.append(Finding(
                                category="config_refs", severity="critical",
                                check="missing_secret",
                                message=f"Volume '{vol.name}' references Secret '{name}' which does not exist",
                                fix_hint=f"Create Secret '{name}' in namespace '{ns}'",
                            ))
        except Exception as e:
            logger.warning(f"config_refs check failed: {e}")
        return findings

    async def _check_storage(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            storage_api = k8s_service._get_api("StorageV1Api")
            if not core_api:
                return []
            ns = pod.metadata.namespace

            for vol in (pod.spec.volumes or []):
                if not vol.persistent_volume_claim:
                    continue
                claim_name = vol.persistent_volume_claim.claim_name
                try:
                    pvc = await core_api.read_namespaced_persistent_volume_claim(claim_name, ns)
                except ApiException as e:
                    if e.status == 404:
                        findings.append(Finding(
                            category="storage", severity="critical", check="missing_pvc",
                            message=f"Volume '{vol.name}' references PVC '{claim_name}' which does not exist",
                            fix_hint=f"Create PVC '{claim_name}' in namespace '{ns}'",
                        ))
                    continue

                deletion_ts = pvc.metadata.deletion_timestamp
                finalizers = pvc.metadata.finalizers or []
                phase = pvc.status.phase or ""

                if deletion_ts and finalizers:
                    findings.append(Finding(
                        category="storage", severity="critical", check="pvc_stuck_terminating",
                        message=f"PVC '{claim_name}' is stuck in Terminating (finalizers: {finalizers})",
                        fix_hint=(f"kubectl patch pvc {claim_name} -n {ns} "
                                   f"-p '{{\"metadata\":{{\"finalizers\":null}}}}'"),
                    ))
                elif phase == "Pending":
                    sc_name = pvc.spec.storage_class_name
                    if sc_name and storage_api:
                        try:
                            await storage_api.read_storage_class(sc_name)
                        except ApiException as e:
                            if e.status == 404:
                                findings.append(Finding(
                                    category="storage", severity="critical",
                                    check="missing_storage_class",
                                    message=(f"PVC '{claim_name}' requests StorageClass '{sc_name}' "
                                             f"which does not exist"),
                                    fix_hint=f"Install the storage provisioner or create StorageClass '{sc_name}'",
                                ))
                                continue
                    findings.append(Finding(
                        category="storage", severity="critical", check="pvc_pending",
                        message=f"PVC '{claim_name}' is Pending — no PersistentVolume available",
                        fix_hint="Check available PVs with list_pvs or verify StorageClass provisioner is running",
                    ))
        except Exception as e:
            logger.warning(f"storage check failed: {e}")
        return findings

    async def _check_resources(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            if not core_api:
                return []
            ns = pod.metadata.namespace

            for container in (pod.spec.containers or []):
                resources = container.resources
                if not resources:
                    continue
                limits = resources.limits or {}
                requests = resources.requests or {}
                mem_limit = limits.get("memory")
                mem_request = requests.get("memory")
                if mem_limit and mem_request:
                    limit_bytes = _parse_k8s_memory(mem_limit)
                    request_bytes = _parse_k8s_memory(mem_request)
                    if limit_bytes and request_bytes and limit_bytes < request_bytes:
                        findings.append(Finding(
                            category="resources", severity="critical",
                            check="memory_limit_below_request",
                            message=(f"Container '{container.name}' memory limit ({mem_limit}) "
                                     f"< request ({mem_request}) — pod will never schedule"),
                            fix_hint="Set memory limit >= request via patch_deployment_resources",
                        ))

            try:
                quota_list = await core_api.list_namespaced_resource_quota(ns)
                for quota in quota_list.items:
                    hard = quota.spec.hard or {}
                    used = quota.status.used or {}
                    for resource, hard_val in hard.items():
                        used_val = used.get(resource)
                        if used_val and _parse_quantity(used_val) >= _parse_quantity(hard_val):
                            findings.append(Finding(
                                category="resources", severity="warning", check="quota_exhausted",
                                message=(f"ResourceQuota '{quota.metadata.name}': "
                                         f"{resource} used={used_val} >= hard={hard_val}"),
                                fix_hint=(f"Increase ResourceQuota limit for '{resource}' "
                                          f"or free up resources in namespace '{ns}'"),
                            ))
            except Exception:
                pass

            if pod.status.phase == "Pending":
                for condition in (pod.status.conditions or []):
                    if condition.type == "PodScheduled" and condition.status == "False":
                        msg = condition.message or ""
                        if "Insufficient" in msg:
                            findings.append(Finding(
                                category="resources", severity="critical",
                                check="insufficient_node_resources",
                                message=f"Pod cannot schedule: {msg}",
                                fix_hint="Scale up nodes or reduce requests via patch_deployment_resources",
                            ))
        except Exception as e:
            logger.warning(f"resources check failed: {e}")
        return findings

    async def _check_scheduling(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            if not core_api:
                return []

            deletion_ts = pod.metadata.deletion_timestamp
            finalizers = pod.metadata.finalizers or []
            if deletion_ts and finalizers:
                findings.append(Finding(
                    category="scheduling", severity="warning", check="stuck_terminating",
                    message=(f"Pod '{pod.metadata.name}' is stuck in Terminating "
                             f"with finalizers: {finalizers}"),
                    fix_hint=(f"kubectl patch pod {pod.metadata.name} "
                               f"-n {pod.metadata.namespace} "
                               f"-p '{{\"metadata\":{{\"finalizers\":null}}}}'"),
                ))
                return findings

            if pod.status.phase != "Pending":
                return findings

            node_selector = pod.spec.node_selector or {}
            if node_selector:
                try:
                    node_list = await core_api.list_node()
                    matching = [
                        n for n in node_list.items
                        if all((n.metadata.labels or {}).get(k) == v
                               for k, v in node_selector.items())
                    ]
                    if not matching:
                        findings.append(Finding(
                            category="scheduling", severity="critical",
                            check="node_selector_no_match",
                            message=f"Pod nodeSelector {node_selector} matches no nodes in the cluster",
                            fix_hint="Update nodeSelector to match existing node labels (use get_node_status)",
                        ))
                except Exception:
                    pass

            try:
                toleration_keys = {(t.key, t.effect) for t in (pod.spec.tolerations or [])}
                node_list = await core_api.list_node()
                schedulable = []
                for node in node_list.items:
                    taints = node.spec.taints or []
                    unmatched = [
                        t for t in taints
                        if t.effect != "PreferNoSchedule"
                        and (t.key, t.effect) not in toleration_keys
                        and (t.key, None) not in toleration_keys
                    ]
                    if not unmatched:
                        schedulable.append(node)
                if not schedulable and node_list.items:
                    findings.append(Finding(
                        category="scheduling", severity="critical",
                        check="taint_no_toleration",
                        message="Pod has no toleration for any node's taints — cannot schedule",
                        fix_hint="Add tolerations to the pod spec matching node taints",
                    ))
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"scheduling check failed: {e}")
        return findings

    async def _check_rbac(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            rbac_api = k8s_service._get_api("RbacAuthorizationV1Api")
            if not core_api:
                return []
            ns = pod.metadata.namespace
            sa_name = pod.spec.service_account_name or "default"

            try:
                await core_api.read_namespaced_service_account(sa_name, ns)
            except ApiException as e:
                if e.status == 404:
                    findings.append(Finding(
                        category="rbac", severity="critical", check="missing_service_account",
                        message=(f"Pod references ServiceAccount '{sa_name}' which does not "
                                 f"exist in namespace '{ns}'"),
                        fix_hint=f"kubectl create serviceaccount {sa_name} -n {ns}",
                    ))
                    return findings

            if rbac_api and sa_name != "default":
                try:
                    rb_list = await rbac_api.list_namespaced_role_binding(ns)
                    crb_list = await rbac_api.list_cluster_role_binding()
                    all_bindings = rb_list.items + crb_list.items
                    sa_has_binding = any(
                        any(s.name == sa_name and s.namespace == ns and s.kind == "ServiceAccount"
                            for s in (b.subjects or []))
                        for b in all_bindings
                    )
                    if not sa_has_binding:
                        findings.append(Finding(
                            category="rbac", severity="warning", check="no_role_binding",
                            message=(f"ServiceAccount '{sa_name}' has no RoleBinding or "
                                     f"ClusterRoleBinding — app may lack K8s API permissions"),
                            fix_hint=(f"Create a RoleBinding for ServiceAccount '{sa_name}' "
                                      f"or verify app does not need K8s API access"),
                        ))
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"rbac check failed: {e}")
        return findings

    async def _check_workload_health(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            apps_api = k8s_service._get_api("AppsV1Api")
            auto_api = k8s_service._get_api("AutoscalingV2Api")
            if not apps_api:
                return []
            ns = pod.metadata.namespace

            for ref in (pod.metadata.owner_references or []):
                if ref.kind == "ReplicaSet":
                    try:
                        rs = await apps_api.read_namespaced_replica_set(ref.name, ns)
                        for rs_ref in (rs.metadata.owner_references or []):
                            if rs_ref.kind != "Deployment":
                                continue
                            try:
                                dep = await apps_api.read_namespaced_deployment(rs_ref.name, ns)
                                ready = dep.status.ready_replicas or 0
                                desired = dep.spec.replicas or 0
                                if desired > 0 and ready < desired:
                                    findings.append(Finding(
                                        category="workload_health", severity="warning",
                                        check="deployment_not_ready",
                                        message=(f"Deployment '{rs_ref.name}' has "
                                                 f"{ready}/{desired} ready replicas"),
                                        fix_hint=(f"Call get_pod_events for "
                                                  f"'{pod.metadata.name}' to see why pods are not ready"),
                                    ))
                                if auto_api:
                                    try:
                                        hpa_list = await auto_api.list_namespaced_horizontal_pod_autoscaler(ns)
                                        for hpa in hpa_list.items:
                                            tref = hpa.spec.scale_target_ref
                                            if not (tref and tref.kind == "Deployment"
                                                    and tref.name == rs_ref.name):
                                                continue
                                            for cond in (hpa.status.conditions or []):
                                                if cond.type == "ScalingLimited" and cond.status == "True":
                                                    findings.append(Finding(
                                                        category="workload_health", severity="warning",
                                                        check="hpa_scaling_limited",
                                                        message=(f"HPA '{hpa.metadata.name}' is "
                                                                 f"scaling-limited: {cond.message}"),
                                                        fix_hint="Check HPA min/maxReplicas or metric availability",
                                                    ))
                                                if cond.type == "AbleToScale" and cond.status == "False":
                                                    findings.append(Finding(
                                                        category="workload_health", severity="critical",
                                                        check="hpa_cannot_scale",
                                                        message=(f"HPA '{hpa.metadata.name}' cannot "
                                                                 f"scale: {cond.message}"),
                                                        fix_hint="Verify metrics-server is running: get_cluster_health",
                                                    ))
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    except Exception:
                        pass

                elif ref.kind == "StatefulSet":
                    try:
                        ss = await apps_api.read_namespaced_stateful_set(ref.name, ns)
                        ready = ss.status.ready_replicas or 0
                        desired = ss.spec.replicas or 0
                        if desired > 0 and ready < desired:
                            findings.append(Finding(
                                category="workload_health", severity="warning",
                                check="statefulset_not_ready",
                                message=f"StatefulSet '{ref.name}' has {ready}/{desired} ready replicas",
                                fix_hint="Check PVC provisioning for StatefulSet ordinals with list_pvcs",
                            ))
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"workload_health check failed: {e}")
        return findings

    async def _check_security_context(self, pod) -> List[Finding]:
        findings: List[Finding] = []
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            if not core_api:
                return []
            ns = pod.metadata.namespace

            try:
                ns_obj = await core_api.read_namespace(ns)
                ns_labels = ns_obj.metadata.labels or {}
            except Exception:
                return findings

            enforce_level = ns_labels.get("pod-security.kubernetes.io/enforce", "")
            if enforce_level != "restricted":
                return findings

            pod_sc = pod.spec.security_context
            for container in (pod.spec.containers or []):
                csc = container.security_context

                run_as_root = False
                if pod_sc and pod_sc.run_as_non_root is False:
                    run_as_root = True
                if csc and csc.run_as_non_root is False:
                    run_as_root = True
                if csc and csc.run_as_user == 0:
                    run_as_root = True

                if run_as_root:
                    findings.append(Finding(
                        category="security_context", severity="critical",
                        check="run_as_root_restricted",
                        message=(f"Container '{container.name}' runs as root but namespace "
                                 f"'{ns}' enforces 'restricted' PodSecurity policy"),
                        fix_hint="Set securityContext.runAsNonRoot=true and runAsUser to non-zero UID",
                    ))

                if csc and csc.privileged:
                    findings.append(Finding(
                        category="security_context", severity="critical",
                        check="privileged_restricted",
                        message=(f"Container '{container.name}' is privileged but namespace "
                                 f"'{ns}' enforces 'restricted' PodSecurity policy"),
                        fix_hint="Remove securityContext.privileged=true from the container spec",
                    ))

                if csc and csc.allow_privilege_escalation:
                    findings.append(Finding(
                        category="security_context", severity="warning",
                        check="privilege_escalation_restricted",
                        message=(f"Container '{container.name}' allows privilege escalation "
                                 f"but namespace '{ns}' enforces 'restricted' PodSecurity policy"),
                        fix_hint="Set securityContext.allowPrivilegeEscalation=false",
                    ))
        except Exception as e:
            logger.warning(f"security_context check failed: {e}")
        return findings

    async def diagnose_pod(self, pod_name: str, namespace: Optional[str] = None) -> str:
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            if not core_api:
                return f"DIAGNOSIS: {pod_name} — K8s API unavailable"

            pod = None
            if namespace:
                try:
                    pod = await core_api.read_namespaced_pod(pod_name, namespace)
                except ApiException as e:
                    if e.status == 404:
                        return f"DIAGNOSIS: {pod_name} — Pod not found in namespace '{namespace}'"
                    raise
            else:
                try:
                    pod_list = await core_api.list_pod_for_all_namespaces()
                    for p in pod_list.items:
                        if p.metadata.name == pod_name:
                            pod = p
                            break
                except Exception:
                    pass

            if not pod:
                return f"DIAGNOSIS: {pod_name} — Pod not found"

            ns = pod.metadata.namespace
            all_findings: List[Finding] = []
            async_checks = [
                self._check_networking, self._check_config_refs, self._check_storage,
                self._check_resources, self._check_scheduling, self._check_rbac,
                self._check_workload_health, self._check_security_context,
            ]
            sync_checks = [self._check_container_state, self._check_probes]

            for check_fn in sync_checks:
                try:
                    all_findings.extend(check_fn(pod))
                except Exception as e:
                    logger.warning(f"{check_fn.__name__} raised unexpectedly: {e}")

            for check_fn in async_checks:
                try:
                    all_findings.extend(await check_fn(pod))
                except Exception as e:
                    logger.warning(f"{check_fn.__name__} raised unexpectedly: {e}")

            return self._format_findings(f"{pod_name} (Pod/{ns})", all_findings, self.CATEGORIES)
        except Exception as e:
            logger.error(f"diagnose_pod failed: {e}")
            return f"DIAGNOSIS: {pod_name} — Error during diagnosis: {e}"

    async def diagnose_service(self, service_name: str, namespace: Optional[str] = None) -> str:
        try:
            core_api = k8s_service._get_api("CoreV1Api")
            if not core_api:
                return f"DIAGNOSIS: service/{service_name} — K8s API unavailable"

            svc = None
            if namespace:
                try:
                    svc = await core_api.read_namespaced_service(service_name, namespace)
                except ApiException as e:
                    if e.status == 404:
                        return (f"DIAGNOSIS: service/{service_name} — "
                                f"Service not found in namespace '{namespace}'")
                    raise
            else:
                try:
                    svc_list = await core_api.list_service_for_all_namespaces()
                    for s in svc_list.items:
                        if s.metadata.name == service_name:
                            svc = s
                            break
                except Exception:
                    pass

            if not svc:
                return f"DIAGNOSIS: service/{service_name} — Service not found"

            ns = svc.metadata.namespace
            selector = svc.spec.selector or {}
            sections: List[str] = []

            svc_findings: List[Finding] = []
            try:
                ep = await core_api.read_namespaced_endpoints(service_name, ns)
                total_ready = sum(len(s.addresses or []) for s in (ep.subsets or []))
                if total_ready == 0:
                    svc_findings.append(Finding(
                        category="networking", severity="critical",
                        check="no_ready_endpoints",
                        message=f"Service '{service_name}' has 0 ready endpoints — all traffic will fail",
                        fix_hint="Check pod readiness and service selector",
                    ))
            except Exception:
                pass

            if svc_findings:
                sections.append(
                    self._format_findings(f"{service_name} (Service/{ns})", svc_findings, ["networking"])
                )

            if selector:
                try:
                    pod_list = await core_api.list_namespaced_pod(ns)
                    matching = [
                        p for p in pod_list.items
                        if all((p.metadata.labels or {}).get(k) == v for k, v in selector.items())
                    ][:3]
                    async_checks = [
                        self._check_networking, self._check_config_refs, self._check_storage,
                        self._check_resources, self._check_scheduling, self._check_rbac,
                        self._check_workload_health, self._check_security_context,
                    ]
                    sync_checks = [self._check_container_state, self._check_probes]
                    for pod in matching:
                        pod_findings: List[Finding] = []
                        for check_fn in sync_checks:
                            try:
                                pod_findings.extend(check_fn(pod))
                            except Exception as e:
                                logger.warning(f"{check_fn.__name__} raised: {e}")
                        for check_fn in async_checks:
                            try:
                                pod_findings.extend(await check_fn(pod))
                            except Exception as e:
                                logger.warning(f"{check_fn.__name__} raised: {e}")
                        sections.append(
                            self._format_findings(
                                f"{pod.metadata.name} (Pod/{ns})", pod_findings, self.CATEGORIES
                            )
                        )
                except Exception:
                    pass

            if not sections:
                return f"DIAGNOSIS: service/{service_name} — No pods found matching selector {selector}"

            return "\n\n---\n\n".join(sections)
        except Exception as e:
            logger.error(f"diagnose_service failed: {e}")
            return f"DIAGNOSIS: service/{service_name} — Error during diagnosis: {e}"


diagnostic_engine = DiagnosticEngine()
