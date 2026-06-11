# backend/tests/test_dashboard_parallel.py
import asyncio
import time
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_stats_runs_namespaces_and_nodes_concurrently():
    from app.api.v1 import dashboard

    async def slow_namespaces(context=None):
        await asyncio.sleep(0.1)
        return ["default", "kube-system"]

    async def slow_nodes(context=None):
        await asyncio.sleep(0.1)
        return [{"name": "node-1", "status": "Ready"}]

    with patch.object(dashboard.k8s_service, "list_namespaces", side_effect=slow_namespaces):
        with patch.object(dashboard.k8s_service, "get_nodes", side_effect=slow_nodes):
            start = time.perf_counter()
            result = await dashboard.get_dashboard_stats(
                current_user=object(), cluster_context=None
            )
            elapsed = time.perf_counter() - start

    assert result["namespaces_count"] == 2
    assert result["nodes_count"] == 1
    assert result["status"] == "Healthy"
    assert elapsed < 0.15, f"calls ran serially ({elapsed:.2f}s) — expected concurrent (<0.15s)"
