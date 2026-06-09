"""Regression guards for the kubernetes-asyncio migration."""
import importlib
from pathlib import Path

# Root of repo (tests/ → backend/ → repo root = 2 parents up from this file)
_BACKEND = Path(__file__).parent.parent  # .../backend/
_REPO_ROOT = _BACKEND.parent             # .../scratch/


def test_kubernetes_asyncio_package_is_importable():
    """Fails if kubernetes-asyncio is not installed."""
    mod = importlib.import_module("kubernetes_asyncio")
    assert mod is not None


def test_sync_kubernetes_package_not_imported_in_k8s_service():
    """k8s_service must not import the sync 'kubernetes' package."""
    content = (_BACKEND / "app/services/k8s_service.py").read_text(encoding="utf-8")
    assert "from kubernetes import" not in content
    assert "from kubernetes.client" not in content


def test_sync_kubernetes_package_not_imported_in_k8s_tools():
    """k8s_tools must not import the sync 'kubernetes' package."""
    content = (_BACKEND / "app/tools/k8s_tools.py").read_text(encoding="utf-8")
    assert "from kubernetes import" not in content
    assert "from kubernetes.client" not in content
    assert "from kubernetes.stream" not in content


def test_sync_kubernetes_package_not_imported_in_diagnostic_service():
    """diagnostic_service must not import the sync 'kubernetes' package."""
    content = (_BACKEND / "app/services/diagnostic_service.py").read_text(encoding="utf-8")
    assert "from kubernetes import" not in content
    assert "from kubernetes.client" not in content


import pytest


@pytest.mark.asyncio
async def test_k8s_service_starts_in_mock_mode_without_kubeconfig(monkeypatch):
    """K8sService.__init__ must NOT call any async code; starts in mock_mode=True by default."""
    from app.services.k8s_service import K8sService
    # If __init__ tries to do async work it will raise RuntimeError here
    svc = K8sService()
    assert svc.mock_mode is True
    assert svc.clients == {}


@pytest.mark.asyncio
async def test_k8s_service_initialize_is_awaitable():
    """initialize() must exist and be a coroutine."""
    import inspect
    from app.services.k8s_service import K8sService
    svc = K8sService()
    assert inspect.iscoroutinefunction(svc.initialize)


@pytest.mark.asyncio
async def test_k8s_service_close_is_awaitable():
    """close() must exist and be a coroutine."""
    import inspect
    from app.services.k8s_service import K8sService
    svc = K8sService()
    assert inspect.iscoroutinefunction(svc.close)
    # close() on a mock-mode service must not raise
    await svc.close()


@pytest.mark.asyncio
async def test_close_continues_after_one_client_raises():
    """close() must iterate ALL api_clients even if one .close() raises."""
    from unittest.mock import AsyncMock
    from app.services.k8s_service import K8sService

    svc = K8sService()
    bad_client = AsyncMock()
    bad_client.close.side_effect = RuntimeError("connection reset")
    good_client = AsyncMock()
    svc.api_clients = {"broken-ctx": bad_client, "good-ctx": good_client}
    svc.clients = {"broken-ctx": {}, "good-ctx": {}}

    await svc.close()

    good_client.close.assert_called_once()
    assert svc.api_clients == {}
    assert svc.clients == {}


def test_no_asyncio_to_thread_in_k8s_service():
    """k8s_service.py must contain zero asyncio.to_thread calls after migration."""
    content = (_BACKEND / "app/services/k8s_service.py").read_text(encoding="utf-8")
    assert "asyncio.to_thread" not in content, \
        "Found asyncio.to_thread in k8s_service.py — migration incomplete"


def test_no_asyncio_to_thread_for_k8s_api_in_k8s_tools():
    """
    k8s_tools.py must not wrap kubernetes API calls in asyncio.to_thread.
    subprocess.run calls are allowed to stay (kubectl_fallback, apply_manifest).
    """
    import ast

    content = (_BACKEND / "app/tools/k8s_tools.py").read_text(encoding="utf-8")
    tree = ast.parse(content)
    violations = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not (isinstance(func, ast.Attribute) and func.attr == "to_thread"):
            continue
        # Allow subprocess.run calls only
        if call.args:
            first_arg = call.args[0]
            if (isinstance(first_arg, ast.Attribute) and first_arg.attr == "run"
                    and isinstance(first_arg.value, ast.Name)
                    and first_arg.value.id == "subprocess"):
                continue  # subprocess.run — allowed
        violations.append(ast.get_source_segment(content, node) or f"line {node.lineno}")

    assert violations == [], (
        f"Found {len(violations)} asyncio.to_thread(k8s_api) calls that must be direct awaits:\n"
        + "\n".join(violations[:10])
    )


@pytest.mark.asyncio
async def test_k8s_service_close_clears_clients():
    """close() must clear both clients and api_clients dicts."""
    from app.services.k8s_service import K8sService
    from unittest.mock import AsyncMock, MagicMock

    svc = K8sService()
    mock_api_client = MagicMock()
    mock_api_client.close = AsyncMock()
    svc.api_clients["test-ctx"] = mock_api_client
    svc.clients["test-ctx"] = {"CoreV1Api": MagicMock()}

    await svc.close()

    mock_api_client.close.assert_awaited_once()
    assert svc.api_clients == {}
    assert svc.clients == {}
