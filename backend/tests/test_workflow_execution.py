# backend/tests/test_workflow_execution.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from sqlmodel import Session, create_engine, SQLModel
from app.models.workflow import Workflow, WorkflowRun
from app.services.workflow_service import run_workflow_background, _run_queues


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.asyncio
async def test_execution_creates_run_and_emits_events(db):
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
    db.commit()

    run = WorkflowRun(
        workflow_id=wf.id,
        triggered_by="manual",
        trigger_input={},
        status="pending",
        step_results=[],
    )
    db.add(run)
    db.commit()

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

    db.refresh(run)
    assert run.status == "completed"
    assert run.ai_summary == "Workflow complete."
