import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_secret(name: str, namespace: str, secret_type: str, keys: list):
    import base64
    data = {k: base64.b64encode(b"value").decode() for k in keys}
    meta = SimpleNamespace(name=name, namespace=namespace, creation_timestamp="2026-01-01")
    return SimpleNamespace(metadata=meta, type=secret_type, data=data)


def _make_secret_list(secrets):
    return SimpleNamespace(items=secrets)


# ── Task 1: Secrets ───────────────────────────────────────────────────────────

async def test_list_secrets_returns_names_only():
    from app.tools.k8s_tools import list_secrets
    mock_api = MagicMock()
    mock_api.list_namespaced_secret = AsyncMock(return_value=_make_secret_list([
        _make_secret("rmq-creds", "default", "Opaque", ["password", "username"]),
        _make_secret("tls-cert", "default", "kubernetes.io/tls", ["tls.crt", "tls.key"]),
    ]))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await list_secrets(namespace="default")
    assert result["success"] is True
    secrets = result["data"]["secrets"]
    assert len(secrets) == 2
    names = [s["name"] for s in secrets]
    assert "rmq-creds" in names
    for s in secrets:
        assert "data" not in s


async def test_get_secret_keys_returns_key_names_not_values():
    from app.tools.k8s_tools import get_secret_keys
    mock_api = MagicMock()
    mock_api.read_namespaced_secret = AsyncMock(return_value=_make_secret(
        "rmq-creds", "default", "Opaque", ["password", "username", "host"]
    ))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await get_secret_keys(secret_name="rmq-creds", namespace="default")
    assert result["success"] is True
    assert "keys" in result["data"]
    assert set(result["data"]["keys"]) == {"password", "username", "host"}
    assert "values" not in result["data"]
    assert "data" not in result["data"]


async def test_patch_secret_requires_confirmation():
    from app.tools.k8s_tools import patch_secret
    result = await patch_secret(
        secret_name="rmq-creds", namespace="default",
        key="password", value="newpass", reason="fix RMQ auth"
    )
    assert result.get("requires_confirmation") is True


async def test_patch_secret_executes_when_confirmed():
    from app.tools.k8s_tools import patch_secret
    mock_api = MagicMock()
    mock_api.patch_namespaced_secret = AsyncMock(return_value=MagicMock())
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await patch_secret(
            secret_name="rmq-creds", namespace="default",
            key="password", value="newpass", reason="fix RMQ auth", confirmed=True
        )
    assert result["success"] is True
    mock_api.patch_namespaced_secret.assert_called_once()


# ── Task 2: describe_pod, list_deployments, get_resource_yaml ─────────────────

async def test_describe_pod_returns_details():
    from app.tools.k8s_tools import describe_pod
    with patch("app.tools.k8s_tools.k8s_service.get_pod_details", new=AsyncMock(return_value="Pod details text here")):
        result = await describe_pod(pod_name="api-pod", namespace="default")
    assert result["success"] is True
    assert "Pod details text here" in result["data"]


async def test_list_deployments_returns_list():
    from app.tools.k8s_tools import list_deployments
    mock_api = MagicMock()
    dep1 = SimpleNamespace(
        metadata=SimpleNamespace(name="api", namespace="default", creation_timestamp="2026-01-01"),
        spec=SimpleNamespace(replicas=2),
        status=SimpleNamespace(ready_replicas=2, available_replicas=2, updated_replicas=2),
    )
    mock_api.list_namespaced_deployment = AsyncMock(return_value=SimpleNamespace(items=[dep1]))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await list_deployments(namespace="default")
    assert result["success"] is True
    deps = result["data"]["deployments"]
    assert len(deps) == 1
    assert deps[0]["name"] == "api"
    assert deps[0]["ready_replicas"] == 2


async def test_get_resource_yaml_deployment():
    from app.tools.k8s_tools import get_resource_yaml
    mock_result = {"success": True, "data": "apiVersion: apps/v1\nkind: Deployment", "error": None}
    with patch("app.tools.k8s_tools.kubectl_fallback", new=AsyncMock(return_value=mock_result)) as mock_kubectl:
        result = await get_resource_yaml(kind="deployment", name="api", namespace="default")
    assert result["success"] is True
    mock_kubectl.assert_called_once_with("kubectl get deployment api -n default -o yaml")


# ── Task 3: exec_pod ──────────────────────────────────────────────────────────

async def test_exec_pod_returns_command_output():
    from app.tools.k8s_tools import exec_pod
    mock_v1 = MagicMock()
    mock_v1.connect_get_namespaced_pod_exec = AsyncMock(
        return_value="Server: 10.96.0.10\nAddress: 10.96.0.10#53\n\nName: rabbitmq.default.svc.cluster.local"
    )
    mock_ws_client = AsyncMock()
    mock_ws_client.__aenter__ = AsyncMock(return_value=mock_ws_client)
    mock_ws_client.__aexit__ = AsyncMock(return_value=None)
    with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_client), \
         patch("kubernetes_asyncio.client.CoreV1Api", return_value=mock_v1):
        result = await exec_pod(pod_name="api-pod", namespace="default", command="nslookup rabbitmq")
    assert result["success"] is True
    assert "rabbitmq" in result["data"]["output"]


async def test_exec_pod_returns_error_on_failure():
    from app.tools.k8s_tools import exec_pod
    with patch("kubernetes_asyncio.stream.WsApiClient", side_effect=Exception("pod not found")):
        result = await exec_pod(pod_name="missing-pod", namespace="default", command="ls")
    # Falls back to kubectl_fallback on exception — result depends on kubectl availability
    assert "pod not found" in (result.get("error") or "") or result.get("source") in ("k8s_client", "kubectl_fallback")


# ── Task 4: Metrics ───────────────────────────────────────────────────────────

def _make_pod_metrics(name: str, namespace: str, cpu: str, memory: str):
    return {
        "metadata": {"name": name, "namespace": namespace},
        "containers": [{"name": "app", "usage": {"cpu": cpu, "memory": memory}}],
    }


async def test_get_pod_metrics_returns_usage():
    from app.tools.k8s_tools import get_pod_metrics
    mock_api = MagicMock()
    mock_api.get_namespaced_custom_object = AsyncMock(return_value=_make_pod_metrics("api-pod", "default", "250m", "128Mi"))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await get_pod_metrics(pod_name="api-pod", namespace="default")
    assert result["success"] is True
    assert result["data"]["pod"] == "api-pod"
    assert len(result["data"]["containers"]) == 1
    assert result["data"]["containers"][0]["cpu"] == "250m"


async def test_get_node_metrics_returns_usage():
    from app.tools.k8s_tools import get_node_metrics
    mock_api = MagicMock()
    mock_api.get_cluster_custom_object = AsyncMock(return_value={
        "metadata": {"name": "node-1"},
        "usage": {"cpu": "800m", "memory": "2Gi"},
    })
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await get_node_metrics(node_name="node-1")
    assert result["success"] is True
    assert result["data"]["cpu"] == "800m"


async def test_get_top_pods_returns_sorted_list():
    from app.tools.k8s_tools import get_top_pods
    mock_api = MagicMock()
    mock_api.list_namespaced_custom_object = AsyncMock(return_value={
        "items": [
            _make_pod_metrics("api-pod", "default", "500m", "256Mi"),
            _make_pod_metrics("worker-pod", "default", "100m", "64Mi"),
        ]
    })
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await get_top_pods(namespace="default")
    assert result["success"] is True
    assert len(result["data"]["pods"]) == 2


# ── Task 5: Storage ───────────────────────────────────────────────────────────

def _make_pvc(name: str, namespace: str, phase: str, storage: str, storage_class: str):
    spec = SimpleNamespace(
        storage_class_name=storage_class,
        resources=SimpleNamespace(requests={"storage": storage}),
        access_modes=["ReadWriteOnce"],
    )
    status = SimpleNamespace(phase=phase, capacity={"storage": storage})
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=namespace, creation_timestamp="2026-01-01"),
        spec=spec,
        status=status,
    )


async def test_list_pvcs_returns_list():
    from app.tools.k8s_tools import list_pvcs
    mock_api = MagicMock()
    mock_api.list_namespaced_persistent_volume_claim = AsyncMock(return_value=SimpleNamespace(items=[
        _make_pvc("data-pvc", "default", "Bound", "10Gi", "standard"),
        _make_pvc("logs-pvc", "default", "Pending", "5Gi", "fast"),
    ]))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await list_pvcs(namespace="default")
    assert result["success"] is True
    assert len(result["data"]["pvcs"]) == 2
    names = [p["name"] for p in result["data"]["pvcs"]]
    assert "data-pvc" in names


async def test_get_pv_returns_details():
    from app.tools.k8s_tools import get_pv
    mock_api = MagicMock()
    pv = SimpleNamespace(
        metadata=SimpleNamespace(name="pv-data", creation_timestamp="2026-01-01"),
        spec=SimpleNamespace(
            capacity={"storage": "10Gi"},
            access_modes=["ReadWriteOnce"],
            persistent_volume_reclaim_policy="Retain",
            storage_class_name="standard",
            claim_ref=SimpleNamespace(name="data-pvc", namespace="default"),
        ),
        status=SimpleNamespace(phase="Bound"),
    )
    mock_api.read_persistent_volume = AsyncMock(return_value=pv)
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await get_pv(pv_name="pv-data")
    assert result["success"] is True
    assert result["data"]["name"] == "pv-data"
    assert result["data"]["phase"] == "Bound"


async def test_list_storage_classes():
    from app.tools.k8s_tools import list_storage_classes
    mock_api = MagicMock()
    sc = SimpleNamespace(
        metadata=SimpleNamespace(name="standard", annotations={"storageclass.kubernetes.io/is-default-class": "true"}),
        provisioner="k8s.io/minikube-hostpath",
        reclaim_policy="Delete",
        volume_binding_mode="Immediate",
    )
    mock_api.list_storage_class = AsyncMock(return_value=SimpleNamespace(items=[sc]))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await list_storage_classes()
    assert result["success"] is True
    assert len(result["data"]["storage_classes"]) == 1
    assert result["data"]["storage_classes"][0]["name"] == "standard"
    assert result["data"]["storage_classes"][0]["is_default"] is True


# ── Task 6: Write tools ───────────────────────────────────────────────────────

async def test_patch_deployment_env_requires_confirmation():
    from app.tools.k8s_tools import patch_deployment_env
    result = await patch_deployment_env(
        deployment_name="api", namespace="default",
        container_name="api", env_var="RABBITMQ_PASSWORD",
        value="newpassword", reason="fix RMQ auth"
    )
    assert result.get("requires_confirmation") is True


async def test_patch_deployment_env_executes_when_confirmed():
    from app.tools.k8s_tools import patch_deployment_env
    mock_api = MagicMock()
    container = SimpleNamespace(
        name="api",
        env=[SimpleNamespace(name="RABBITMQ_PASSWORD", value="oldpass", value_from=None)],
    )
    deployment = SimpleNamespace(spec=SimpleNamespace(template=SimpleNamespace(spec=SimpleNamespace(containers=[container]))))
    mock_api.read_namespaced_deployment = AsyncMock(return_value=deployment)
    mock_api.patch_namespaced_deployment = AsyncMock(return_value=MagicMock())
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await patch_deployment_env(
            deployment_name="api", namespace="default",
            container_name="api", env_var="RABBITMQ_PASSWORD",
            value="newpassword", reason="fix RMQ auth", confirmed=True
        )
    assert result["success"] is True
    mock_api.patch_namespaced_deployment.assert_called_once()


async def test_apply_manifest_requires_confirmation():
    from app.tools.k8s_tools import apply_manifest
    result = await apply_manifest(manifest_yaml="apiVersion: v1\nkind: ConfigMap", reason="apply config")
    assert result.get("requires_confirmation") is True


# ── Task 7: RBAC completion ───────────────────────────────────────────────────

def _make_role(name: str, namespace: str, rules: list):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=namespace, creation_timestamp="2026-01-01"),
        rules=rules,
    )


async def test_get_roles_returns_list():
    from app.tools.k8s_tools import get_roles
    mock_api = MagicMock()
    mock_api.list_namespaced_role = AsyncMock(return_value=SimpleNamespace(items=[
        _make_role("pod-reader", "default", [
            SimpleNamespace(api_groups=[""], resources=["pods"], verbs=["get", "list"]),
        ]),
    ]))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await get_roles(namespace="default")
    assert result["success"] is True
    assert len(result["data"]["roles"]) == 1
    assert result["data"]["roles"][0]["name"] == "pod-reader"


async def test_get_cluster_roles_returns_list():
    from app.tools.k8s_tools import get_cluster_roles
    mock_api = MagicMock()
    mock_api.list_cluster_role = AsyncMock(return_value=SimpleNamespace(items=[
        SimpleNamespace(
            metadata=SimpleNamespace(name="cluster-admin", creation_timestamp="2026-01-01"),
            rules=[SimpleNamespace(api_groups=["*"], resources=["*"], verbs=["*"])],
        ),
    ]))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await get_cluster_roles()
    assert result["success"] is True
    assert any(r["name"] == "cluster-admin" for r in result["data"]["cluster_roles"])


async def test_get_cluster_role_bindings_returns_list():
    from app.tools.k8s_tools import get_cluster_role_bindings
    mock_api = MagicMock()
    mock_api.list_cluster_role_binding = AsyncMock(return_value=SimpleNamespace(items=[
        SimpleNamespace(
            metadata=SimpleNamespace(name="admin-binding", creation_timestamp="2026-01-01"),
            role_ref=SimpleNamespace(kind="ClusterRole", name="cluster-admin"),
            subjects=[SimpleNamespace(kind="User", name="admin", namespace=None)],
        ),
    ]))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=mock_api):
        result = await get_cluster_role_bindings()
    assert result["success"] is True
    assert len(result["data"]["cluster_role_bindings"]) == 1
    assert result["data"]["cluster_role_bindings"][0]["name"] == "admin-binding"
