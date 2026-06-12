# backend/tests/test_workflow_execution.py
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.workflow import Workflow, WorkflowRun
from app.services.workflow_service import run_workflow_background, _run_queues


async def _make_async_session():
    """Create an in-memory async session for a single test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


@pytest.mark.asyncio
async def test_execution_creates_run_and_emits_events():
    engine, session_factory = await _make_async_session()
    async with session_factory() as db:
        wf = Workflow(
            name="Test Workflow",
            trigger_type="manual",
            steps=[{
                "id": "s1",
                "name": "HTTP Call",
                "connector_type": "http",
                "config": {"url": "http://example.com", "method": "GET"},
                "on_failure": "stop",
                "output_var": "http_result",
            }],
            created_by="admin",
        )
        db.add(wf)
        await db.commit()
        await db.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            triggered_by="manual",
            trigger_input={},
            status="pending",
            step_results=[],
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        mock_loop_events = [
            {"type": "step", "message": "http_result..."},
            {"type": "result", "message": "Workflow complete."},
        ]

        async def fake_loop(*args, **kwargs):
            for e in mock_loop_events:
                yield e

        _run_queues[run.id] = asyncio.Queue()

        with patch("app.services.workflow_service.ai_service") as mock_ai:
            mock_ai.run_global_agentic_loop = fake_loop
            with patch(
                "app.services.connectors.http_connector.HttpConnector.execute",
                new=AsyncMock(return_value={"success": True, "data": {}}),
            ):
                await run_workflow_background(run.id, wf.id, {}, db)

        await db.refresh(run)
        assert run.status == "completed"
        assert run.ai_summary == "Workflow complete."

    await engine.dispose()
