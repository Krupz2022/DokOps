import pytest
from unittest.mock import AsyncMock, patch
from sqlmodel import Session, create_engine, SQLModel

# Import all models so SQLModel.metadata is fully populated before create_all.
import app.models.workflow  # noqa: F401 – registers Workflow + WorkflowRun tables
import app.models.user      # noqa: F401 – registers User table


@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


def test_agent_tool_catalog_has_required_fields():
    from app.services.agent_executor_service import AGENT_TOOL_CATALOG
    for tool in AGENT_TOOL_CATALOG:
        assert "name" in tool
        assert "description" in tool
        assert "is_destructive" in tool
        assert isinstance(tool["is_destructive"], bool)


def test_agent_tool_catalog_has_destructive_tools():
    from app.services.agent_executor_service import AGENT_TOOL_CATALOG
    names = [t["name"] for t in AGENT_TOOL_CATALOG]
    assert "restart_pod" in names
    assert "scale_deployment" in names
    restart = next(t for t in AGENT_TOOL_CATALOG if t["name"] == "restart_pod")
    assert restart["is_destructive"] is True


@pytest.mark.asyncio
async def test_discover_tools_from_goal():
    from app.services.agent_executor_service import discover_tools_for_goal
    mock_response = [
        {"name": "get_pod_logs", "is_destructive": False, "pre_approved": False},
        {"name": "restart_pod", "is_destructive": True, "pre_approved": False},
    ]
    with patch("app.services.agent_executor_service._ask_ai_for_tools", new=AsyncMock(return_value=mock_response)):
        result = await discover_tools_for_goal("check payment pod for errors and restart if needed")
    assert len(result) == 2
    assert any(t["name"] == "restart_pod" for t in result)


@pytest.mark.asyncio
async def test_happy_path_agent_run(engine):
    from app.services.agent_executor_service import run_agent_background
    from app.services import workflow_service as wf_svc
    from app.models.workflow import Workflow, WorkflowRun
    import asyncio

    with Session(engine) as db:
        wf = Workflow(
            name="patrol",
            workflow_type="agent",
            agent_goal="Check payment pod and post result to Teams",
            agent_approved_tools=[
                {"name": "get_pod_logs", "is_destructive": False, "pre_approved": False},
                {"name": "post_teams", "is_destructive": False, "pre_approved": False},
            ],
            agent_cluster_ids=[],
            agent_minion_ids=[],
            agent_max_retries=3,
            agent_timeout_seconds=30,
            agent_approval_timeout_seconds=10,
            created_by="admin",
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            triggered_by="manual",
            trigger_input={},
            status="pending",
            step_results=[],
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        wf_svc._run_queues[run.id] = asyncio.Queue()
        wf_id = wf.id
        run_id = run.id

    mock_events = [
        {"type": "step", "message": "Fetching pod logs..."},
        {"type": "step", "message": "Logs retrieved. Pod is healthy."},
        {"type": "result", "message": "Payment pod is running normally. Posted to Teams."},
    ]

    async def mock_loop(**kwargs):
        for e in mock_events:
            yield e

    with patch("app.services.ai_service.ai_service.run_global_agentic_loop", side_effect=mock_loop):
        with patch("app.services.agent_executor_service._post_final_report", new=AsyncMock()):
            with Session(engine) as db:
                await run_agent_background(run_id, wf_id, db)

    with Session(engine) as db:
        updated_run = db.get(WorkflowRun, run_id)
        assert updated_run.status == "completed"
        assert updated_run.ai_summary == "Payment pod is running normally. Posted to Teams."


def test_approval_approve_resumes_run():
    from app.services.agent_executor_service import (
        _approval_events, _approval_decisions, resolve_approval
    )
    import asyncio

    run_id = 9999
    event = asyncio.Event()
    _approval_events[run_id] = event
    _approval_decisions[run_id] = "skip"

    resolve_approval(run_id, "approve")

    assert event.is_set()
    assert _approval_decisions[run_id] == "approve"
    # cleanup
    _approval_events.pop(run_id, None)
    _approval_decisions.pop(run_id, None)


def test_approval_skip_resumes_run():
    from app.services.agent_executor_service import (
        _approval_events, _approval_decisions, resolve_approval
    )
    import asyncio

    run_id = 9998
    event = asyncio.Event()
    _approval_events[run_id] = event
    _approval_decisions[run_id] = "approve"

    resolve_approval(run_id, "skip")

    assert event.is_set()
    assert _approval_decisions[run_id] == "skip"
    # cleanup
    _approval_events.pop(run_id, None)
    _approval_decisions.pop(run_id, None)


@pytest.mark.asyncio
async def test_approval_timeout_defaults_to_skip(engine):
    from app.services import agent_executor_service as svc
    from app.models.workflow import Workflow, WorkflowRun

    with Session(engine) as db:
        wf = Workflow(
            name="timeout-test",
            workflow_type="agent",
            agent_goal="test",
            agent_approved_tools=[],
            agent_cluster_ids=[],
            agent_minion_ids=[],
            agent_max_retries=1,
            agent_timeout_seconds=30,
            agent_approval_timeout_seconds=1,  # 1 second — will expire quickly
            created_by="admin",
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id, triggered_by="manual",
            trigger_input={}, status="running", step_results=[],
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        decision = await svc._pause_for_approval(run, "restart_pod", wf, db)

    assert decision == "skip"


@pytest.mark.asyncio
async def test_timeout_stops_run(engine):
    from app.services.agent_executor_service import run_agent_background
    from app.services import workflow_service as wf_svc
    from app.models.workflow import Workflow, WorkflowRun
    import asyncio

    with Session(engine) as db:
        wf = Workflow(
            name="timeout-run",
            workflow_type="agent",
            agent_goal="Do something that hangs",
            agent_approved_tools=[],
            agent_cluster_ids=[],
            agent_minion_ids=[],
            agent_max_retries=3,
            agent_timeout_seconds=1,  # 1 second timeout
            agent_approval_timeout_seconds=5,
            created_by="admin",
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            triggered_by="manual",
            trigger_input={},
            status="pending",
            step_results=[],
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        wf_svc._run_queues[run.id] = asyncio.Queue()
        wf_id = wf.id
        run_id = run.id

    async def slow_loop(**kwargs):
        await asyncio.sleep(10)  # longer than timeout
        yield {"type": "result", "message": "never reached"}

    with patch("app.services.ai_service.ai_service.run_global_agentic_loop", side_effect=slow_loop):
        with patch("app.services.agent_executor_service._post_final_report", new=AsyncMock()):
            with Session(engine) as db:
                await run_agent_background(run_id, wf_id, db)

    with Session(engine) as db:
        updated = db.get(WorkflowRun, run_id)
        assert updated.status == "failed"
        assert "TIMED OUT" in updated.ai_summary


@pytest.mark.asyncio
async def test_multi_cluster_runs_loop_per_cluster(engine):
    from app.services import agent_executor_service as svc
    from app.models.workflow import Workflow, WorkflowRun
    from app.services import workflow_service as wf_svc
    from unittest.mock import patch, AsyncMock
    import asyncio

    cluster_ids_seen = []

    async def mock_run_loop(run, wf, cluster_id, db):
        cluster_ids_seen.append(cluster_id)
        return f"summary for cluster {cluster_id}"

    with patch.object(svc, "_run_loop_for_cluster", side_effect=mock_run_loop):
        with patch.object(svc, "_post_final_report", new=AsyncMock()):
            with Session(engine) as db:
                wf = Workflow(
                    name="multi-cluster",
                    workflow_type="agent",
                    agent_goal="check pods",
                    agent_approved_tools=[],
                    agent_cluster_ids=[1, 2, 3],
                    agent_minion_ids=[],
                    agent_max_retries=3,
                    agent_timeout_seconds=30,
                    agent_approval_timeout_seconds=5,
                    created_by="admin",
                )
                db.add(wf)
                db.commit()
                db.refresh(wf)

                run = WorkflowRun(
                    workflow_id=wf.id, triggered_by="manual",
                    trigger_input={}, status="pending", step_results=[],
                )
                db.add(run)
                db.commit()
                db.refresh(run)
                wf_svc._run_queues[run.id] = asyncio.Queue()

                await svc.run_agent_background(run.id, wf.id, db)

    assert cluster_ids_seen == [1, 2, 3]
