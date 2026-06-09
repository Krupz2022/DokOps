import pytest
from unittest.mock import MagicMock
from app.services.diagnostic_service import DiagnosticEngine, Finding


def test_format_findings_no_issues():
    engine = DiagnosticEngine()
    result = engine._format_findings("api-pod (Pod/default)", [], ["container_state", "probes"])
    assert "Issues found: 0" in result
    assert "Clean: container_state, probes" in result


def test_format_findings_critical_before_warning():
    engine = DiagnosticEngine()
    findings = [
        Finding("resources", "warning", "cpu_throttling", "CPU over limit", "increase limit"),
        Finding("container_state", "critical", "crashloop", "Crashing", "check logs"),
    ]
    result = engine._format_findings("api-pod (Pod/default)", findings, ["container_state", "resources"])
    assert result.index("[CRITICAL]") < result.index("[WARNING]")


def test_format_findings_clean_excludes_categories_with_findings():
    engine = DiagnosticEngine()
    findings = [Finding("networking", "critical", "port_mismatch", "port wrong", "fix port")]
    result = engine._format_findings("api-pod (Pod/default)", findings, ["networking", "storage"])
    clean_section = result.split("Clean:")[-1]
    assert "networking" not in clean_section
    assert "storage" in clean_section


def test_format_findings_shows_fix_hint():
    engine = DiagnosticEngine()
    findings = [Finding("networking", "critical", "port_mismatch", "port wrong", "kubectl patch svc api-svc")]
    result = engine._format_findings("api-pod (Pod/default)", findings, ["networking"])
    assert "kubectl patch svc api-svc" in result


# ── Task 2: _check_container_state ────────────────────────────────────────────

def _make_pod_with_cs(reason: str, last_reason: str = None, restart_count: int = 0,
                      init_reason: str = None):
    pod = MagicMock()
    pod.metadata.name = "api-abc"
    pod.metadata.namespace = "default"
    cs = MagicMock()
    cs.name = "api"
    cs.restart_count = restart_count
    cs.state.waiting.reason = reason
    cs.state.running = None
    cs.state.terminated = None
    if last_reason:
        cs.last_state.terminated.reason = last_reason
    else:
        cs.last_state.terminated = None
    pod.status.container_statuses = [cs]
    if init_reason:
        ics = MagicMock()
        ics.name = "init-api"
        ics.state.waiting.reason = init_reason
        pod.status.init_container_statuses = [ics]
    else:
        pod.status.init_container_statuses = []
    return pod


def test_check_container_state_crashloop():
    engine = DiagnosticEngine()
    pod = _make_pod_with_cs("CrashLoopBackOff", restart_count=5)
    findings = engine._check_container_state(pod)
    assert len(findings) == 1
    assert findings[0].check == "crashloop"
    assert findings[0].severity == "critical"
    assert "5" in findings[0].message


def test_check_container_state_oomkilled():
    engine = DiagnosticEngine()
    pod = _make_pod_with_cs("CrashLoopBackOff", last_reason="OOMKilled")
    findings = engine._check_container_state(pod)
    assert len(findings) == 1
    assert findings[0].check == "oomkilled"
    assert findings[0].severity == "critical"


def test_check_container_state_image_pull():
    engine = DiagnosticEngine()
    pod = _make_pod_with_cs("ImagePullBackOff")
    findings = engine._check_container_state(pod)
    assert len(findings) == 1
    assert findings[0].check == "image_pull"


def test_check_container_state_err_image_pull():
    engine = DiagnosticEngine()
    pod = _make_pod_with_cs("ErrImagePull")
    findings = engine._check_container_state(pod)
    assert len(findings) == 1
    assert findings[0].check == "image_pull"


def test_check_container_state_init_failing():
    engine = DiagnosticEngine()
    pod = _make_pod_with_cs("Running", init_reason="CrashLoopBackOff")
    findings = engine._check_container_state(pod)
    assert any(f.check == "init_container_failing" for f in findings)


def test_check_container_state_healthy_returns_empty():
    engine = DiagnosticEngine()
    pod = MagicMock()
    cs = MagicMock()
    cs.state.waiting = None
    cs.state.terminated = None
    pod.status.container_statuses = [cs]
    pod.status.init_container_statuses = []
    findings = engine._check_container_state(pod)
    assert findings == []


# ── Task 3: _check_probes ─────────────────────────────────────────────────────

def _make_pod_with_probe(probe_port: int, container_port: int, probe_type: str = "http"):
    pod = MagicMock()
    pod.metadata.name = "api-abc"
    pod.metadata.namespace = "default"
    pod.status.container_statuses = []
    pod.status.init_container_statuses = []

    container = MagicMock()
    container.name = "api"
    p = MagicMock()
    p.container_port = container_port
    container.ports = [p]

    probe = MagicMock()
    if probe_type == "http":
        probe.http_get.port = probe_port
        probe.tcp_socket = None
    else:
        probe.http_get = None
        probe.tcp_socket.port = probe_port
    probe.exec = None

    container.readiness_probe = probe
    container.liveness_probe = None
    pod.spec.containers = [container]
    return pod


def test_check_probes_readiness_port_mismatch():
    engine = DiagnosticEngine()
    pod = _make_pod_with_probe(probe_port=9090, container_port=8080)
    findings = engine._check_probes(pod)
    assert len(findings) == 1
    assert findings[0].check == "readiness_probe_port_mismatch"
    assert findings[0].severity == "critical"
    assert "9090" in findings[0].message
    assert "8080" in findings[0].message


def test_check_probes_tcp_port_mismatch():
    engine = DiagnosticEngine()
    pod = _make_pod_with_probe(probe_port=9090, container_port=8080, probe_type="tcp")
    findings = engine._check_probes(pod)
    assert len(findings) == 1
    assert findings[0].check == "readiness_probe_port_mismatch"


def test_check_probes_matching_port_returns_empty():
    engine = DiagnosticEngine()
    pod = _make_pod_with_probe(probe_port=8080, container_port=8080)
    findings = engine._check_probes(pod)
    assert findings == []


def test_check_probes_no_ports_declared_returns_empty():
    engine = DiagnosticEngine()
    pod = MagicMock()
    container = MagicMock()
    container.ports = []
    container.readiness_probe = None
    container.liveness_probe = None
    pod.spec.containers = [container]
    findings = engine._check_probes(pod)
    assert findings == []


# ── Task 4: _check_networking ─────────────────────────────────────────────────
from unittest.mock import patch


def _make_networking_pod(container_port: int = 8080):
    pod = MagicMock()
    pod.metadata.name = "api-abc"
    pod.metadata.namespace = "default"
    pod.metadata.labels = {"app": "api"}
    c = MagicMock()
    c.name = "api"
    p = MagicMock()
    p.container_port = container_port
    c.ports = [p]
    pod.spec.containers = [c]
    return pod


def _make_mock_core_api(svc_target_port: int = 8080, endpoints_ready: int = 1,
                        endpoints_not_ready: int = 0):
    core_api = MagicMock()
    svc = MagicMock()
    svc.metadata.name = "api-svc"
    svc.spec.selector = {"app": "api"}
    port = MagicMock()
    port.port = 80
    port.target_port = svc_target_port
    svc.spec.ports = [port]
    core_api.list_namespaced_service.return_value.items = [svc]

    ep = MagicMock()
    subset = MagicMock()
    subset.addresses = [MagicMock()] * endpoints_ready
    subset.not_ready_addresses = [MagicMock()] * endpoints_not_ready
    ep.subsets = [subset]
    core_api.read_namespaced_endpoints.return_value = ep
    return core_api


def _make_mock_k8s(core_api, net_api=None):
    mock = MagicMock()
    def get_api(api_type, context=None):
        if api_type == "CoreV1Api":
            return core_api
        if api_type == "NetworkingV1Api":
            return net_api
        return MagicMock()
    mock._get_api = get_api
    return mock


def test_check_networking_port_mismatch():
    engine = DiagnosticEngine()
    pod = _make_networking_pod(container_port=8080)
    core_api = _make_mock_core_api(svc_target_port=9090)
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_networking(pod)
    port_findings = [f for f in findings if f.check == "port_mismatch"]
    assert len(port_findings) == 1
    assert "9090" in port_findings[0].message
    assert "8080" in port_findings[0].message


def test_check_networking_endpoints_not_ready():
    engine = DiagnosticEngine()
    pod = _make_networking_pod(container_port=8080)
    core_api = _make_mock_core_api(svc_target_port=8080, endpoints_ready=0, endpoints_not_ready=1)
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_networking(pod)
    assert any(f.check == "endpoints_not_ready" for f in findings)


def test_check_networking_no_service_returns_empty():
    engine = DiagnosticEngine()
    pod = _make_networking_pod()
    core_api = MagicMock()
    core_api.list_namespaced_service.return_value.items = []
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_networking(pod)
    assert findings == []


def test_check_networking_ingress_port_mismatch():
    engine = DiagnosticEngine()
    pod = _make_networking_pod(container_port=8080)
    core_api = _make_mock_core_api(svc_target_port=8080)

    net_api = MagicMock()
    ing = MagicMock()
    ing.metadata.name = "api-ing"
    rule = MagicMock()
    path = MagicMock()
    path.backend.service.name = "api-svc"
    path.backend.service.port.number = 9999  # wrong — service exposes 80
    rule.http.paths = [path]
    ing.spec.rules = [rule]
    net_api.list_namespaced_ingress.return_value.items = [ing]

    mock_k8s = _make_mock_k8s(core_api, net_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_networking(pod)
    assert any(f.check == "ingress_port_mismatch" for f in findings)


def test_check_networking_api_unavailable_returns_empty():
    engine = DiagnosticEngine()
    pod = _make_networking_pod()
    mock_k8s = MagicMock()
    mock_k8s._get_api.return_value = None
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_networking(pod)
    assert findings == []


# ── Task 5: _check_config_refs ────────────────────────────────────────────────
from kubernetes_asyncio.client.rest import ApiException as K8sApiException


def _api_404():
    e = K8sApiException(status=404)
    e.status = 404
    return e


def _make_pod_with_envfrom(cm_name: str = None, secret_name: str = None):
    pod = MagicMock()
    pod.metadata.namespace = "default"
    container = MagicMock()
    container.name = "api"
    envfrom = MagicMock()
    if cm_name:
        envfrom.config_map_ref.name = cm_name
        envfrom.secret_ref = None
    else:
        envfrom.config_map_ref = None
        envfrom.secret_ref.name = secret_name
    container.env_from = [envfrom]
    container.env = []
    pod.spec.containers = [container]
    pod.spec.volumes = []
    return pod


def test_check_config_refs_missing_configmap():
    engine = DiagnosticEngine()
    pod = _make_pod_with_envfrom(cm_name="app-config")
    core_api = MagicMock()
    core_api.read_namespaced_config_map.side_effect = _api_404()
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_config_refs(pod)
    assert len(findings) == 1
    assert findings[0].check == "missing_configmap"
    assert "app-config" in findings[0].message


def test_check_config_refs_missing_secret():
    engine = DiagnosticEngine()
    pod = _make_pod_with_envfrom(secret_name="app-secret")
    core_api = MagicMock()
    core_api.read_namespaced_secret.side_effect = _api_404()
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_config_refs(pod)
    assert len(findings) == 1
    assert findings[0].check == "missing_secret"


def test_check_config_refs_missing_configmap_key():
    engine = DiagnosticEngine()
    pod = MagicMock()
    pod.metadata.namespace = "default"
    container = MagicMock()
    container.name = "api"
    container.env_from = []
    env_var = MagicMock()
    env_var.name = "DB_HOST"
    env_var.value_from.config_map_key_ref.name = "app-config"
    env_var.value_from.config_map_key_ref.key = "DB_HOST"
    env_var.value_from.secret_key_ref = None
    container.env = [env_var]
    pod.spec.containers = [container]
    pod.spec.volumes = []

    core_api = MagicMock()
    cm = MagicMock()
    cm.data = {"OTHER_KEY": "value"}  # DB_HOST not present
    core_api.read_namespaced_config_map.return_value = cm
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_config_refs(pod)
    assert len(findings) == 1
    assert findings[0].check == "missing_configmap_key"
    assert "DB_HOST" in findings[0].message


def test_check_config_refs_all_present_returns_empty():
    engine = DiagnosticEngine()
    pod = _make_pod_with_envfrom(cm_name="app-config")
    core_api = MagicMock()
    core_api.read_namespaced_config_map.return_value = MagicMock()
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_config_refs(pod)
    assert findings == []


# ── Task 6: _check_storage ────────────────────────────────────────────────────

def _make_pod_with_pvc(claim_name: str):
    pod = MagicMock()
    pod.metadata.namespace = "default"
    pod.spec.containers = []
    vol = MagicMock()
    vol.name = "data"
    vol.persistent_volume_claim.claim_name = claim_name
    vol.config_map = None
    vol.secret = None
    pod.spec.volumes = [vol]
    return pod


def _make_pvc(name: str, phase: str, storage_class: str = None, terminating: bool = False):
    pvc = MagicMock()
    pvc.metadata.name = name
    pvc.metadata.finalizers = ["kubernetes.io/pvc-protection"] if terminating else []
    pvc.metadata.deletion_timestamp = MagicMock() if terminating else None
    pvc.status.phase = phase
    pvc.spec.storage_class_name = storage_class
    pvc.spec.volume_name = None
    return pvc


def test_check_storage_pvc_pending():
    engine = DiagnosticEngine()
    pod = _make_pod_with_pvc("data-pvc")
    core_api = MagicMock()
    storage_api = MagicMock()
    core_api.read_namespaced_persistent_volume_claim.return_value = _make_pvc("data-pvc", "Pending")
    storage_api.read_storage_class.return_value = MagicMock()
    mock_k8s = MagicMock()
    mock_k8s._get_api.side_effect = lambda t, ctx=None: (
        core_api if t == "CoreV1Api" else storage_api if t == "StorageV1Api" else MagicMock()
    )
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_storage(pod)
    assert any(f.check == "pvc_pending" for f in findings)


def test_check_storage_pvc_stuck_terminating():
    engine = DiagnosticEngine()
    pod = _make_pod_with_pvc("data-pvc")
    core_api = MagicMock()
    core_api.read_namespaced_persistent_volume_claim.return_value = _make_pvc(
        "data-pvc", "Bound", terminating=True
    )
    mock_k8s = MagicMock()
    mock_k8s._get_api.side_effect = lambda t, ctx=None: core_api if t == "CoreV1Api" else MagicMock()
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_storage(pod)
    assert any(f.check == "pvc_stuck_terminating" for f in findings)


def test_check_storage_missing_storage_class():
    engine = DiagnosticEngine()
    pod = _make_pod_with_pvc("data-pvc")
    core_api = MagicMock()
    storage_api = MagicMock()
    core_api.read_namespaced_persistent_volume_claim.return_value = _make_pvc(
        "data-pvc", "Pending", storage_class="fast-ssd"
    )
    storage_api.read_storage_class.side_effect = _api_404()
    mock_k8s = MagicMock()
    mock_k8s._get_api.side_effect = lambda t, ctx=None: (
        core_api if t == "CoreV1Api" else storage_api if t == "StorageV1Api" else MagicMock()
    )
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_storage(pod)
    assert any(f.check == "missing_storage_class" for f in findings)


def test_check_storage_no_pvc_volumes_returns_empty():
    engine = DiagnosticEngine()
    pod = MagicMock()
    pod.metadata.namespace = "default"
    pod.spec.containers = []
    pod.spec.volumes = []
    mock_k8s = MagicMock()
    mock_k8s._get_api.return_value = MagicMock()
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_storage(pod)
    assert findings == []


# ── Task 7: _check_resources ──────────────────────────────────────────────────

def _make_pod_with_resources(mem_limit: str = None, mem_request: str = None,
                              phase: str = "Running", schedule_msg: str = None):
    pod = MagicMock()
    pod.metadata.namespace = "default"
    pod.metadata.name = "api-abc"
    pod.status.phase = phase
    container = MagicMock()
    container.name = "api"
    container.resources.limits = {}
    container.resources.requests = {}
    if mem_limit:
        container.resources.limits["memory"] = mem_limit
    if mem_request:
        container.resources.requests["memory"] = mem_request
    pod.spec.containers = [container]
    if schedule_msg:
        cond = MagicMock()
        cond.type = "PodScheduled"
        cond.status = "False"
        cond.message = schedule_msg
        pod.status.conditions = [cond]
    else:
        pod.status.conditions = []
    return pod


def test_check_resources_memory_limit_below_request():
    engine = DiagnosticEngine()
    pod = _make_pod_with_resources(mem_limit="128Mi", mem_request="256Mi")
    core_api = MagicMock()
    core_api.list_namespaced_resource_quota.return_value.items = []
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_resources(pod)
    assert any(f.check == "memory_limit_below_request" for f in findings)
    assert any(f.severity == "critical" for f in findings)


def test_check_resources_pending_insufficient():
    engine = DiagnosticEngine()
    pod = _make_pod_with_resources(phase="Pending", schedule_msg="Insufficient memory")
    core_api = MagicMock()
    core_api.list_namespaced_resource_quota.return_value.items = []
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_resources(pod)
    assert any(f.check == "insufficient_node_resources" for f in findings)


def test_check_resources_quota_exhausted():
    engine = DiagnosticEngine()
    pod = _make_pod_with_resources()
    core_api = MagicMock()
    quota = MagicMock()
    quota.metadata.name = "ns-quota"
    quota.spec.hard = {"pods": "10"}
    quota.status.used = {"pods": "10"}
    core_api.list_namespaced_resource_quota.return_value.items = [quota]
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_resources(pod)
    assert any(f.check == "quota_exhausted" for f in findings)


def test_check_resources_healthy_returns_empty():
    engine = DiagnosticEngine()
    pod = _make_pod_with_resources(mem_limit="512Mi", mem_request="256Mi")
    core_api = MagicMock()
    core_api.list_namespaced_resource_quota.return_value.items = []
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_resources(pod)
    assert findings == []


# ── Task 8: _check_scheduling ─────────────────────────────────────────────────

def _make_pending_pod(node_selector: dict = None, tolerations=None, finalizers=None,
                      deletion_ts=False):
    pod = MagicMock()
    pod.metadata.name = "api-abc"
    pod.metadata.namespace = "default"
    pod.metadata.finalizers = finalizers or []
    pod.metadata.deletion_timestamp = MagicMock() if deletion_ts else None
    pod.status.phase = "Pending"
    pod.spec.node_selector = node_selector or {}
    pod.spec.tolerations = tolerations or []
    pod.status.conditions = []
    return pod


def _make_node(labels: dict, taints=None):
    node = MagicMock()
    node.metadata.labels = labels
    node.spec.taints = taints or []
    return node


def test_check_scheduling_node_selector_no_match():
    engine = DiagnosticEngine()
    pod = _make_pending_pod(node_selector={"gpu": "true"})
    core_api = MagicMock()
    core_api.list_node.return_value.items = [_make_node({"zone": "us-east"})]
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_scheduling(pod)
    assert any(f.check == "node_selector_no_match" for f in findings)


def test_check_scheduling_taint_no_toleration():
    engine = DiagnosticEngine()
    pod = _make_pending_pod()
    taint = MagicMock()
    taint.key = "dedicated"
    taint.effect = "NoSchedule"
    core_api = MagicMock()
    core_api.list_node.return_value.items = [_make_node({}, taints=[taint])]
    mock_k8s = _make_mock_k8s(core_api)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_scheduling(pod)
    assert any(f.check == "taint_no_toleration" for f in findings)


def test_check_scheduling_stuck_terminating():
    engine = DiagnosticEngine()
    pod = _make_pending_pod(finalizers=["some-finalizer"], deletion_ts=True)
    mock_k8s = _make_mock_k8s(MagicMock())
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_scheduling(pod)
    assert any(f.check == "stuck_terminating" for f in findings)


def test_check_scheduling_running_pod_returns_empty():
    engine = DiagnosticEngine()
    pod = MagicMock()
    pod.metadata.deletion_timestamp = None
    pod.metadata.finalizers = []
    pod.status.phase = "Running"
    pod.spec.node_selector = {}
    mock_k8s = _make_mock_k8s(MagicMock())
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_scheduling(pod)
    assert findings == []


# ── Task 9: _check_rbac ───────────────────────────────────────────────────────

def _make_pod_with_sa(sa_name: str):
    pod = MagicMock()
    pod.metadata.namespace = "default"
    pod.spec.service_account_name = sa_name
    return pod


def _make_mock_k8s_rbac(sa_exists: bool = True, has_binding: bool = True):
    core_api = MagicMock()
    rbac_api = MagicMock()
    if not sa_exists:
        core_api.read_namespaced_service_account.side_effect = _api_404()
    else:
        core_api.read_namespaced_service_account.return_value = MagicMock()

    if has_binding:
        binding = MagicMock()
        subj = MagicMock()
        subj.name = "my-sa"
        subj.namespace = "default"
        subj.kind = "ServiceAccount"
        binding.subjects = [subj]
        rbac_api.list_namespaced_role_binding.return_value.items = [binding]
    else:
        rbac_api.list_namespaced_role_binding.return_value.items = []
    rbac_api.list_cluster_role_binding.return_value.items = []

    mock_k8s = MagicMock()
    mock_k8s._get_api.side_effect = lambda t, ctx=None: (
        core_api if t == "CoreV1Api"
        else rbac_api if t == "RbacAuthorizationV1Api"
        else MagicMock()
    )
    return mock_k8s


def test_check_rbac_missing_service_account():
    engine = DiagnosticEngine()
    pod = _make_pod_with_sa("my-sa")
    mock_k8s = _make_mock_k8s_rbac(sa_exists=False)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_rbac(pod)
    assert len(findings) == 1
    assert findings[0].check == "missing_service_account"


def test_check_rbac_no_role_binding():
    engine = DiagnosticEngine()
    pod = _make_pod_with_sa("my-sa")
    mock_k8s = _make_mock_k8s_rbac(sa_exists=True, has_binding=False)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_rbac(pod)
    assert any(f.check == "no_role_binding" for f in findings)


def test_check_rbac_default_sa_no_binding_warning_skipped():
    engine = DiagnosticEngine()
    pod = _make_pod_with_sa("default")
    mock_k8s = _make_mock_k8s_rbac(sa_exists=True, has_binding=False)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_rbac(pod)
    assert not any(f.check == "no_role_binding" for f in findings)


def test_check_rbac_sa_exists_with_binding_returns_empty():
    engine = DiagnosticEngine()
    pod = _make_pod_with_sa("my-sa")
    mock_k8s = _make_mock_k8s_rbac(sa_exists=True, has_binding=True)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_rbac(pod)
    assert findings == []


# ── Task 10: _check_workload_health ───────────────────────────────────────────

def _make_pod_with_owner(kind: str, owner_name: str):
    pod = MagicMock()
    pod.metadata.name = "api-abc"
    pod.metadata.namespace = "default"
    ref = MagicMock()
    ref.kind = kind
    ref.name = owner_name
    pod.metadata.owner_references = [ref]
    return pod


def _make_mock_k8s_workload(rs_name: str, dep_name: str,
                             dep_ready: int, dep_desired: int,
                             hpa_conditions=None):
    apps_api = MagicMock()
    auto_api = MagicMock()

    rs = MagicMock()
    rs_ref = MagicMock()
    rs_ref.kind = "Deployment"
    rs_ref.name = dep_name
    rs.metadata.owner_references = [rs_ref]
    apps_api.read_namespaced_replica_set.return_value = rs

    dep = MagicMock()
    dep.status.ready_replicas = dep_ready
    dep.spec.replicas = dep_desired
    apps_api.read_namespaced_deployment.return_value = dep

    if hpa_conditions:
        hpa = MagicMock()
        hpa.metadata.name = "api-hpa"
        ref = MagicMock()
        ref.kind = "Deployment"
        ref.name = dep_name
        hpa.spec.scale_target_ref = ref
        hpa.status.conditions = hpa_conditions
        auto_api.list_namespaced_horizontal_pod_autoscaler.return_value.items = [hpa]
    else:
        auto_api.list_namespaced_horizontal_pod_autoscaler.return_value.items = []

    mock_k8s = MagicMock()
    mock_k8s._get_api.side_effect = lambda t, ctx=None: (
        apps_api if t == "AppsV1Api"
        else auto_api if t == "AutoscalingV2Api"
        else MagicMock()
    )
    return mock_k8s


def test_check_workload_health_deployment_not_ready():
    engine = DiagnosticEngine()
    pod = _make_pod_with_owner("ReplicaSet", "api-rs-abc")
    mock_k8s = _make_mock_k8s_workload("api-rs-abc", "api", dep_ready=1, dep_desired=3)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_workload_health(pod)
    assert any(f.check == "deployment_not_ready" for f in findings)
    assert "1/3" in next(f.message for f in findings if f.check == "deployment_not_ready")


def test_check_workload_health_hpa_cannot_scale():
    engine = DiagnosticEngine()
    pod = _make_pod_with_owner("ReplicaSet", "api-rs-abc")
    cond = MagicMock()
    cond.type = "AbleToScale"
    cond.status = "False"
    cond.message = "metrics unavailable"
    mock_k8s = _make_mock_k8s_workload("api-rs-abc", "api", dep_ready=2, dep_desired=2,
                                        hpa_conditions=[cond])
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_workload_health(pod)
    assert any(f.check == "hpa_cannot_scale" for f in findings)


def test_check_workload_health_no_owner_returns_empty():
    engine = DiagnosticEngine()
    pod = MagicMock()
    pod.metadata.namespace = "default"
    pod.metadata.owner_references = []
    mock_k8s = MagicMock()
    mock_k8s._get_api.return_value = MagicMock()
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_workload_health(pod)
    assert findings == []


def test_check_workload_health_healthy_deployment_returns_empty():
    engine = DiagnosticEngine()
    pod = _make_pod_with_owner("ReplicaSet", "api-rs-abc")
    mock_k8s = _make_mock_k8s_workload("api-rs-abc", "api", dep_ready=3, dep_desired=3)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_workload_health(pod)
    assert findings == []


# ── Task 11: _check_security_context ─────────────────────────────────────────

def _make_pod_with_security(run_as_user: int = None, run_as_non_root: bool = None,
                             privileged: bool = False, allow_priv_escalation: bool = False):
    pod = MagicMock()
    pod.metadata.namespace = "default"
    pod.spec.security_context.run_as_non_root = run_as_non_root
    container = MagicMock()
    container.name = "api"
    container.security_context.run_as_non_root = run_as_non_root
    container.security_context.run_as_user = run_as_user
    container.security_context.privileged = privileged
    container.security_context.allow_privilege_escalation = allow_priv_escalation
    pod.spec.containers = [container]
    return pod


def _make_mock_k8s_security(enforce_level: str):
    core_api = MagicMock()
    ns_obj = MagicMock()
    ns_obj.metadata.labels = (
        {"pod-security.kubernetes.io/enforce": enforce_level} if enforce_level else {}
    )
    core_api.read_namespace.return_value = ns_obj
    mock_k8s = _make_mock_k8s(core_api)
    return mock_k8s


def test_check_security_context_run_as_root_restricted():
    engine = DiagnosticEngine()
    pod = _make_pod_with_security(run_as_user=0)
    mock_k8s = _make_mock_k8s_security("restricted")
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_security_context(pod)
    assert any(f.check == "run_as_root_restricted" for f in findings)


def test_check_security_context_privileged_restricted():
    engine = DiagnosticEngine()
    pod = _make_pod_with_security(privileged=True)
    mock_k8s = _make_mock_k8s_security("restricted")
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_security_context(pod)
    assert any(f.check == "privileged_restricted" for f in findings)


def test_check_security_context_baseline_namespace_no_findings():
    engine = DiagnosticEngine()
    pod = _make_pod_with_security(run_as_user=0)
    mock_k8s = _make_mock_k8s_security("baseline")
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_security_context(pod)
    assert findings == []


def test_check_security_context_no_label_returns_empty():
    engine = DiagnosticEngine()
    pod = _make_pod_with_security(run_as_user=0)
    mock_k8s = _make_mock_k8s_security("")
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        findings = engine._check_security_context(pod)
    assert findings == []


# ── Task 12: diagnose_pod and diagnose_service ────────────────────────────────

def _make_full_mock_k8s(pod):
    core_api = MagicMock()
    core_api.read_namespaced_pod.return_value = pod
    core_api.list_namespaced_service.return_value.items = []
    core_api.list_namespaced_resource_quota.return_value.items = []
    core_api.list_node.return_value.items = []
    core_api.read_namespace.return_value.metadata.labels = {}

    mock_k8s = MagicMock()
    mock_k8s._get_api.side_effect = lambda t, ctx=None: core_api if t == "CoreV1Api" else MagicMock()
    return mock_k8s


def _make_healthy_pod(name: str = "api-abc", namespace: str = "default"):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.labels = {"app": "api"}
    pod.metadata.owner_references = []
    pod.metadata.deletion_timestamp = None
    pod.metadata.finalizers = []
    pod.status.phase = "Running"
    pod.status.container_statuses = []
    pod.status.init_container_statuses = []
    pod.status.conditions = []
    pod.spec.containers = []
    pod.spec.volumes = []
    pod.spec.node_selector = {}
    pod.spec.tolerations = []
    pod.spec.service_account_name = "default"
    pod.spec.security_context = MagicMock()
    pod.spec.security_context.run_as_non_root = True
    return pod


def test_diagnose_pod_returns_diagnosis_header():
    engine = DiagnosticEngine()
    pod = _make_healthy_pod()
    mock_k8s = _make_full_mock_k8s(pod)
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        result = engine.diagnose_pod("api-abc", "default")
    assert "DIAGNOSIS: api-abc" in result
    assert "Checked: 10 categories" in result


def test_diagnose_pod_not_found():
    engine = DiagnosticEngine()
    core_api = MagicMock()
    e = K8sApiException(status=404)
    e.status = 404
    core_api.read_namespaced_pod.side_effect = e
    mock_k8s = MagicMock()
    mock_k8s._get_api.return_value = core_api
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        result = engine.diagnose_pod("missing-pod", "default")
    assert "not found" in result


def test_diagnose_pod_one_check_exception_does_not_abort():
    engine = DiagnosticEngine()
    pod = _make_healthy_pod()
    mock_k8s = _make_full_mock_k8s(pod)
    def bad_networking(p):
        raise RuntimeError("simulated failure")
    engine._check_networking = bad_networking
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        result = engine.diagnose_pod("api-abc", "default")
    assert "Checked: 10 categories" in result


def test_diagnose_service_not_found():
    engine = DiagnosticEngine()
    core_api = MagicMock()
    e = K8sApiException(status=404)
    e.status = 404
    core_api.read_namespaced_service.side_effect = e
    mock_k8s = MagicMock()
    mock_k8s._get_api.return_value = core_api
    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        result = engine.diagnose_service("missing-svc", "default")
    assert "not found" in result


# ── Task 14: Integration tests ────────────────────────────────────────────────

def _make_pod_with_three_issues():
    """Pod with: CrashLoopBackOff + port mismatch + missing ConfigMap."""
    pod = MagicMock()
    pod.metadata.name = "broken-pod"
    pod.metadata.namespace = "default"
    pod.metadata.labels = {"app": "broken"}
    pod.metadata.owner_references = []
    pod.metadata.deletion_timestamp = None
    pod.metadata.finalizers = []
    pod.status.phase = "Running"
    pod.status.conditions = []

    cs = MagicMock()
    cs.name = "app"
    cs.restart_count = 8
    cs.state.waiting.reason = "CrashLoopBackOff"
    cs.state.running = None
    cs.state.terminated = None
    cs.last_state.terminated = None
    pod.status.container_statuses = [cs]
    pod.status.init_container_statuses = []

    c = MagicMock()
    c.name = "app"
    cp = MagicMock()
    cp.container_port = 8080
    c.ports = [cp]
    c.readiness_probe = None
    c.liveness_probe = None
    c.env_from = []

    env_var = MagicMock()
    env_var.name = "DB_URL"
    env_var.value_from.config_map_key_ref.name = "db-config"
    env_var.value_from.config_map_key_ref.key = "url"
    env_var.value_from.secret_key_ref = None
    c.env = [env_var]
    c.resources.limits = {}
    c.resources.requests = {}
    pod.spec.containers = [c]
    pod.spec.volumes = []
    pod.spec.node_selector = {}
    pod.spec.tolerations = []
    pod.spec.service_account_name = "default"
    pod.spec.security_context.run_as_non_root = True
    return pod


def test_integration_diagnose_pod_three_simultaneous_issues():
    engine = DiagnosticEngine()
    pod = _make_pod_with_three_issues()

    core_api = MagicMock()
    core_api.read_namespaced_pod.return_value = pod

    svc = MagicMock()
    svc.metadata.name = "broken-svc"
    svc.spec.selector = {"app": "broken"}
    port = MagicMock()
    port.port = 80
    port.target_port = 9090
    svc.spec.ports = [port]
    core_api.list_namespaced_service.return_value.items = [svc]

    ep = MagicMock()
    ep.subsets = []
    core_api.read_namespaced_endpoints.return_value = ep

    e = K8sApiException(status=404)
    e.status = 404
    core_api.read_namespaced_config_map.side_effect = e

    core_api.list_namespaced_resource_quota.return_value.items = []
    core_api.list_node.return_value.items = []
    core_api.read_namespace.return_value.metadata.labels = {}

    mock_k8s = MagicMock()
    mock_k8s._get_api.side_effect = lambda t, ctx=None: (
        core_api if t == "CoreV1Api" else MagicMock()
    )

    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        result = engine.diagnose_pod("broken-pod", "default")

    assert "crashloop" in result
    assert "port_mismatch" in result
    assert "missing_configmap" in result
    assert "Issues found: 3" in result


def test_integration_diagnose_service_checks_multiple_pods():
    engine = DiagnosticEngine()

    pod1 = _make_healthy_pod("api-pod-1")
    pod2 = _make_healthy_pod("api-pod-2")

    core_api = MagicMock()
    svc = MagicMock()
    svc.metadata.name = "api-svc"
    svc.metadata.namespace = "default"
    svc.spec.selector = {"app": "api"}
    svc.spec.ports = []
    core_api.read_namespaced_service.return_value = svc

    ep = MagicMock()
    subset = MagicMock()
    subset.addresses = [MagicMock(), MagicMock()]
    subset.not_ready_addresses = []
    ep.subsets = [subset]
    core_api.read_namespaced_endpoints.return_value = ep

    pod1.metadata.labels = {"app": "api"}
    pod2.metadata.labels = {"app": "api"}
    core_api.list_namespaced_pod.return_value.items = [pod1, pod2]
    core_api.list_namespaced_service.return_value.items = []
    core_api.list_namespaced_resource_quota.return_value.items = []
    core_api.list_node.return_value.items = []
    core_api.read_namespace.return_value.metadata.labels = {}

    mock_k8s = MagicMock()
    mock_k8s._get_api.side_effect = lambda t, ctx=None: (
        core_api if t == "CoreV1Api" else MagicMock()
    )

    with patch("app.services.diagnostic_service.k8s_service", mock_k8s):
        result = engine.diagnose_service("api-svc", "default")

    assert "api-pod-1" in result
    assert "api-pod-2" in result
