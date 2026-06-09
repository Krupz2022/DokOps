# backend/tests/test_topology_service.py
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import networkx as nx
import pytest

from app.services.topology_service import TopologyService, _node_id


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pod(name: str, namespace: str, labels: dict, phase: str = "Running",
              owner_refs=None, volumes=None) -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.labels = labels
    pod.metadata.owner_references = owner_refs or []
    pod.status.phase = phase
    pod.spec.volumes = volumes or []
    pod.spec.containers = []
    return pod


def _make_deployment(name: str, namespace: str, ready: int = 1, desired: int = 1) -> MagicMock:
    dep = MagicMock()
    dep.metadata.name = name
    dep.metadata.namespace = namespace
    dep.metadata.labels = {}
    dep.metadata.owner_references = []
    dep.status.ready_replicas = ready
    dep.spec.replicas = desired
    return dep


def _make_service(name: str, namespace: str, selector: dict,
                  svc_type: str = "ClusterIP") -> MagicMock:
    svc = MagicMock()
    svc.metadata.name = name
    svc.metadata.namespace = namespace
    svc.metadata.labels = {}
    svc.spec.selector = selector
    svc.spec.type = svc_type
    return svc


def _make_list(items: list) -> MagicMock:
    obj = MagicMock()
    obj.items = items
    return obj


def _empty_list() -> MagicMock:
    return _make_list([])


# ── Tests: _node_id ───────────────────────────────────────────────────────────

def test_node_id_format():
    assert _node_id("Pod", "default", "my-pod") == "Pod/default/my-pod"


def test_node_id_cluster_scoped():
    assert _node_id("PV", "", "my-pv") == "PV//my-pv"


# ── Tests: mock mode ──────────────────────────────────────────────────────────

def test_mock_graph_returns_nodes():
    """When mock_mode=True, _build_mock_graph returns a non-empty DiGraph."""
    svc = TopologyService()
    g = svc._build_mock_graph()
    assert isinstance(g, nx.DiGraph)
    assert g.number_of_nodes() > 0


def test_mock_graph_has_deployment_pod_edge():
    """Mock graph must have at least one 'owns' edge."""
    svc = TopologyService()
    g = svc._build_mock_graph()
    relations = [data["relation"] for _, _, data in g.edges(data=True)]
    assert "owns" in relations


# ── Tests: _build_graph_for_context ──────────────────────────────────────────

@pytest.fixture
def minimal_k8s_mock():
    """Returns a mock k8s_service with empty API responses for all resource types."""
    mock = MagicMock()
    mock.mock_mode = False
    core = MagicMock()
    core.list_namespace = AsyncMock(return_value=_empty_list())
    core.list_pod_for_all_namespaces = AsyncMock(return_value=_empty_list())
    core.list_service_for_all_namespaces = AsyncMock(return_value=_empty_list())
    core.list_persistent_volume_claim_for_all_namespaces = AsyncMock(return_value=_empty_list())
    core.list_persistent_volume = AsyncMock(return_value=_empty_list())
    apps = MagicMock()
    apps.list_deployment_for_all_namespaces = AsyncMock(return_value=_empty_list())
    apps.list_stateful_set_for_all_namespaces = AsyncMock(return_value=_empty_list())
    apps.list_daemon_set_for_all_namespaces = AsyncMock(return_value=_empty_list())
    batch = MagicMock()
    batch.list_job_for_all_namespaces = AsyncMock(return_value=_empty_list())
    batch.list_cron_job_for_all_namespaces = AsyncMock(return_value=_empty_list())
    net = MagicMock()
    net.list_ingress_for_all_namespaces = AsyncMock(return_value=_empty_list())
    auto = MagicMock()
    auto.list_horizontal_pod_autoscaler_for_all_namespaces = AsyncMock(return_value=_empty_list())
    storage = MagicMock()
    storage.list_storage_class = AsyncMock(return_value=_empty_list())

    def get_api(api_type, context=None):
        return {
            "CoreV1Api": core,
            "AppsV1Api": apps,
            "BatchV1Api": batch,
            "NetworkingV1Api": net,
            "AutoscalingV2Api": auto,
            "StorageV1Api": storage,
        }[api_type]

    mock._get_api = get_api
    return mock, core, apps, batch, net, auto, storage


def test_empty_cluster_builds_empty_graph(minimal_k8s_mock):
    mock_k8s, *_ = minimal_k8s_mock
    svc = TopologyService()
    with patch("app.services.topology_service.k8s_service", mock_k8s):
        g = svc._build_graph_for_context_sync("test-ctx")
    assert isinstance(g, nx.DiGraph)
    assert g.number_of_nodes() == 0


def test_pod_owner_ref_creates_deployment_pod_edge(minimal_k8s_mock):
    """A pod with ownerReference to a Deployment gets an 'owns' edge from Deployment→Pod."""
    mock_k8s, core, apps, *_ = minimal_k8s_mock

    owner_ref = MagicMock()
    owner_ref.kind = "Deployment"
    owner_ref.name = "api"

    pod = _make_pod("api-abc123", "default", {"app": "api"}, owner_refs=[owner_ref])
    core.list_pod_for_all_namespaces.return_value = _make_list([pod])
    apps.list_deployment_for_all_namespaces.return_value = _make_list([
        _make_deployment("api", "default")
    ])

    svc = TopologyService()
    with patch("app.services.topology_service.k8s_service", mock_k8s):
        g = svc._build_graph_for_context_sync("test-ctx")

    dep_id = _node_id("Deployment", "default", "api")
    pod_id = _node_id("Pod", "default", "api-abc123")
    assert g.has_edge(dep_id, pod_id)
    assert g.edges[dep_id, pod_id]["relation"] == "owns"


def test_service_selects_pod_by_labels(minimal_k8s_mock):
    """Service with selector {app: api} selects pods whose labels are a superset."""
    mock_k8s, core, *_ = minimal_k8s_mock

    pod = _make_pod("api-abc123", "default", {"app": "api", "version": "v1"})
    svc_obj = _make_service("api-svc", "default", {"app": "api"})
    core.list_pod_for_all_namespaces.return_value = _make_list([pod])
    core.list_service_for_all_namespaces.return_value = _make_list([svc_obj])

    svc = TopologyService()
    with patch("app.services.topology_service.k8s_service", mock_k8s):
        g = svc._build_graph_for_context_sync("test-ctx")

    svc_id = _node_id("Service", "default", "api-svc")
    pod_id = _node_id("Pod", "default", "api-abc123")
    assert g.has_edge(svc_id, pod_id)
    assert g.edges[svc_id, pod_id]["relation"] == "selects"


def test_service_does_not_select_pod_wrong_namespace(minimal_k8s_mock):
    """Service in namespace A must not select pods in namespace B."""
    mock_k8s, core, *_ = minimal_k8s_mock

    pod = _make_pod("api-abc123", "other-ns", {"app": "api"})
    svc_obj = _make_service("api-svc", "default", {"app": "api"})
    core.list_pod_for_all_namespaces.return_value = _make_list([pod])
    core.list_service_for_all_namespaces.return_value = _make_list([svc_obj])

    svc = TopologyService()
    with patch("app.services.topology_service.k8s_service", mock_k8s):
        g = svc._build_graph_for_context_sync("test-ctx")

    svc_id = _node_id("Service", "default", "api-svc")
    pod_id = _node_id("Pod", "other-ns", "api-abc123")
    assert not g.has_edge(svc_id, pod_id)


def test_pod_configmap_volume_creates_mounts_edge(minimal_k8s_mock):
    """Pod with a ConfigMap volume gets a mounts edge Pod→ConfigMap."""
    mock_k8s, core, *_ = minimal_k8s_mock

    vol = MagicMock()
    vol.config_map = MagicMock()
    vol.config_map.name = "app-config"
    vol.secret = None
    vol.persistent_volume_claim = None

    pod = _make_pod("api-abc123", "default", {"app": "api"}, volumes=[vol])
    core.list_pod_for_all_namespaces.return_value = _make_list([pod])

    svc = TopologyService()
    with patch("app.services.topology_service.k8s_service", mock_k8s):
        g = svc._build_graph_for_context_sync("test-ctx")

    pod_id = _node_id("Pod", "default", "api-abc123")
    cm_id = _node_id("ConfigMap", "default", "app-config")
    assert g.has_edge(pod_id, cm_id)
    assert g.edges[pod_id, cm_id]["relation"] == "mounts"


def test_pvc_pv_bound_edge(minimal_k8s_mock):
    """PVC with spec.volume_name gets a bound-to edge PVC→PV."""
    mock_k8s, core, *_ = minimal_k8s_mock

    pvc = MagicMock()
    pvc.metadata.name = "data-pvc"
    pvc.metadata.namespace = "default"
    pvc.metadata.labels = {}
    pvc.status.phase = "Bound"
    pvc.spec.volume_name = "data-pv"
    pvc.spec.storage_class_name = None

    core.list_persistent_volume_claim_for_all_namespaces.return_value = _make_list([pvc])
    core.list_persistent_volume.return_value = _empty_list()

    svc = TopologyService()
    with patch("app.services.topology_service.k8s_service", mock_k8s):
        g = svc._build_graph_for_context_sync("test-ctx")

    pvc_id = _node_id("PVC", "default", "data-pvc")
    pv_id = _node_id("PV", "", "data-pv")
    assert g.has_edge(pvc_id, pv_id)
    assert g.edges[pvc_id, pv_id]["relation"] == "bound-to"


def test_api_failure_for_one_type_does_not_abort_graph(minimal_k8s_mock):
    """If Ingress API raises, the rest of the graph still builds."""
    mock_k8s, core, apps, batch, net, auto, storage = minimal_k8s_mock

    net.list_ingress_for_all_namespaces.side_effect = Exception("NetworkingV1 unavailable")
    core.list_pod_for_all_namespaces.return_value = _make_list([
        _make_pod("api-abc123", "default", {"app": "api"})
    ])

    svc = TopologyService()
    with patch("app.services.topology_service.k8s_service", mock_k8s):
        g = svc._build_graph_for_context_sync("test-ctx")

    # Pod node should exist even though Ingress failed
    pod_id = _node_id("Pod", "default", "api-abc123")
    assert g.has_node(pod_id)


# ── Tests: get_cluster_overview ───────────────────────────────────────────────

from datetime import datetime, timezone


def _make_svc_with_graph() -> TopologyService:
    """Returns a TopologyService pre-loaded with a small test graph."""
    svc = TopologyService()
    g = nx.DiGraph()
    g.add_node(_node_id("Namespace", "", "default"),
               kind="Namespace", name="default", namespace="", labels={}, status="Active")
    g.add_node(_node_id("Deployment", "default", "api"),
               kind="Deployment", name="api", namespace="default", labels={}, status="2/2")
    g.add_node(_node_id("Deployment", "default", "worker"),
               kind="Deployment", name="worker", namespace="default", labels={}, status="1/1")
    g.add_node(_node_id("Pod", "default", "api-abc"),
               kind="Pod", name="api-abc", namespace="default", labels={}, status="Running")
    g.add_node(_node_id("Pod", "default", "bad-pod"),
               kind="Pod", name="bad-pod", namespace="default", labels={}, status="CrashLoopBackOff")
    g.add_node(_node_id("Service", "default", "api-svc"),
               kind="Service", name="api-svc", namespace="default", labels={}, status="ClusterIP")
    svc._graphs["test-ctx"] = g
    svc._last_built["test-ctx"] = datetime.now(timezone.utc)
    return svc


def test_overview_cold_start():
    svc = TopologyService()
    result = svc.get_cluster_overview("missing-ctx")
    assert "not yet available" in result


def test_overview_contains_namespace():
    svc = _make_svc_with_graph()
    result = svc.get_cluster_overview("test-ctx")
    assert "default" in result


def test_overview_contains_deployment_status():
    svc = _make_svc_with_graph()
    result = svc.get_cluster_overview("test-ctx")
    assert "api[2/2]" in result


def test_overview_lists_unhealthy_pods():
    svc = _make_svc_with_graph()
    result = svc.get_cluster_overview("test-ctx")
    assert "bad-pod" in result
    assert "CrashLoopBackOff" in result


def test_overview_contains_service():
    svc = _make_svc_with_graph()
    result = svc.get_cluster_overview("test-ctx")
    assert "api-svc" in result


def test_overview_staleness_warning():
    from datetime import timedelta
    svc = _make_svc_with_graph()
    svc._last_built["test-ctx"] = (
        datetime.now(timezone.utc) - timedelta(seconds=120)
    )
    result = svc.get_cluster_overview("test-ctx")
    assert "stale" in result.lower()


# ── Tests: search_topology ────────────────────────────────────────────────────

def _make_svc_with_connected_graph() -> TopologyService:
    svc = TopologyService()
    g = nx.DiGraph()
    dep_id = _node_id("Deployment", "default", "rabbitmq")
    pod_id = _node_id("Pod", "default", "rabbitmq-0")
    svc_id = _node_id("Service", "default", "rabbitmq-svc")
    cm_id = _node_id("ConfigMap", "default", "rabbitmq-config")
    g.add_node(dep_id, kind="Deployment", name="rabbitmq",
               namespace="default", labels={}, status="1/1")
    g.add_node(pod_id, kind="Pod", name="rabbitmq-0",
               namespace="default", labels={"app": "rabbitmq"}, status="Running")
    g.add_node(svc_id, kind="Service", name="rabbitmq-svc",
               namespace="default", labels={}, status="ClusterIP")
    g.add_node(cm_id, kind="ConfigMap", name="rabbitmq-config",
               namespace="default", labels={}, status="")
    g.add_edge(dep_id, pod_id, relation="owns")
    g.add_edge(svc_id, pod_id, relation="selects")
    g.add_edge(pod_id, cm_id, relation="mounts")
    svc._graphs["test-ctx"] = g
    svc._last_built["test-ctx"] = datetime.now(timezone.utc)
    return svc


def test_search_topology_no_context():
    svc = TopologyService()
    result = svc.search_topology("rabbitmq", "missing-ctx")
    assert "No topology data" in result


def test_search_topology_no_match():
    svc = _make_svc_with_connected_graph()
    result = svc.search_topology("nonexistent-xyz", "test-ctx")
    assert "No topology matches" in result


def test_search_topology_finds_by_name():
    svc = _make_svc_with_connected_graph()
    result = svc.search_topology("rabbitmq-svc", "test-ctx")
    assert "TOPOLOGY: rabbitmq-svc" in result


def test_search_topology_shows_descendants():
    svc = _make_svc_with_connected_graph()
    result = svc.search_topology("rabbitmq-svc", "test-ctx")
    assert "rabbitmq-0" in result


def test_search_topology_shows_ancestors():
    svc = _make_svc_with_connected_graph()
    result = svc.search_topology("rabbitmq-0", "test-ctx")
    assert "rabbitmq" in result


# ── Tests: get_blast_radius ───────────────────────────────────────────────────

def test_blast_radius_no_context():
    svc = TopologyService()
    result = svc.get_blast_radius("Service", "api-svc", "default", "missing-ctx")
    assert "No topology data" in result


def test_blast_radius_resource_not_found():
    svc = _make_svc_with_connected_graph()
    result = svc.get_blast_radius("Service", "nonexistent", "default", "test-ctx")
    assert "not found" in result


def test_blast_radius_shows_downstream():
    svc = _make_svc_with_connected_graph()
    result = svc.get_blast_radius("Service", "rabbitmq-svc", "default", "test-ctx")
    assert "BLAST RADIUS" in result
    assert "rabbitmq-0" in result


def test_blast_radius_no_downstream():
    svc = _make_svc_with_connected_graph()
    result = svc.get_blast_radius("ConfigMap", "rabbitmq-config", "default", "test-ctx")
    assert "No downstream" in result
