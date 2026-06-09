import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_mock_pod(name, namespace, phase, node_name, labels):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.spec.node_name = node_name
    pod.metadata.labels = labels
    pod.status.phase = phase
    pod.status.pod_ip = "10.0.0.1"
    pod.status.container_statuses = None
    return pod


def make_mock_service(name, namespace, selector):
    svc = MagicMock()
    svc.metadata.name = name
    svc.metadata.namespace = namespace
    svc.spec.selector = selector
    return svc


async def test_list_pods_includes_node_name_and_labels():
    from app.services.k8s_service import K8sService
    svc = K8sService.__new__(K8sService)
    svc.mock_mode = False
    svc.default_context = "default"

    mock_core = MagicMock()
    mock_pod = make_mock_pod("web-abc", "default", "Running", "node-1", {"app": "web"})
    mock_result = MagicMock()
    mock_result.items = [mock_pod]
    mock_core.list_namespaced_pod = AsyncMock(return_value=mock_result)
    svc.clients = {"default": {"CoreV1Api": mock_core}}

    result = await svc.list_pods("default")
    assert result[0]["node_name"] == "node-1"
    assert result[0]["labels"] == {"app": "web"}


async def test_list_services_returns_selector():
    from app.services.k8s_service import K8sService
    svc = K8sService.__new__(K8sService)
    svc.mock_mode = False
    svc.default_context = "default"

    mock_core = MagicMock()
    mock_svc = make_mock_service("web-svc", "default", {"app": "web"})
    mock_result = MagicMock()
    mock_result.items = [mock_svc]
    mock_core.list_namespaced_service = AsyncMock(return_value=mock_result)
    svc.clients = {"default": {"CoreV1Api": mock_core}}

    result = await svc.list_services("default")
    assert result[0]["name"] == "web-svc"
    assert result[0]["selector"] == {"app": "web"}


async def test_build_topology_snapshot_physical_edges():
    """Physical view: pods are linked to their node via 'hosts' edges."""
    import app.api.v1.topology as topo_module

    mock_nodes = [{"name": "node-1", "status": "Ready"}]
    mock_namespaces = ["default"]
    mock_pods = [{
        "name": "web-abc", "status": "Running",
        "node_name": "node-1", "labels": {"app": "web"},
        "namespace": "default", "ip": "10.0.0.1"
    }]
    mock_services = [{"name": "web-svc", "namespace": "default", "selector": {"app": "web"}}]

    with patch.object(topo_module.k8s_service, "mock_mode", False), \
         patch.object(topo_module.k8s_service, "get_nodes", new=AsyncMock(return_value=mock_nodes)), \
         patch.object(topo_module.k8s_service, "list_namespaces", new=AsyncMock(return_value=mock_namespaces)), \
         patch.object(topo_module.k8s_service, "list_pods", new=AsyncMock(return_value=mock_pods)), \
         patch.object(topo_module.k8s_service, "list_services", new=AsyncMock(return_value=mock_services)):

        snapshot = await topo_module.build_topology_snapshot()

    node_ids = {n.id for n in snapshot.nodes}
    assert "node/node-1" in node_ids
    assert "pod/default/web-abc" in node_ids
    assert "svc/default/web-svc" in node_ids

    edge_pairs = {(e.source, e.target) for e in snapshot.edges}
    assert ("node/node-1", "pod/default/web-abc") in edge_pairs   # physical host edge
    assert ("svc/default/web-svc", "pod/default/web-abc") in edge_pairs  # logical route edge


async def test_build_topology_snapshot_mock_mode():
    """Mock mode returns a non-empty snapshot with mock=True."""
    import app.api.v1.topology as topo_module

    with patch.object(topo_module.k8s_service, "mock_mode", True):
        snapshot = await topo_module.build_topology_snapshot()

    assert snapshot.mock is True
    assert len(snapshot.nodes) > 0
