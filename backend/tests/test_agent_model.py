import pytest
from sqlmodel import Session, create_engine, SQLModel, select
from app.models.workflow import Workflow, WorkflowRun

@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)

def test_agent_workflow_fields(engine):
    with Session(engine) as db:
        wf = Workflow(
            name="test-agent",
            workflow_type="agent",
            agent_goal="Check payment pod for errors",
            agent_approved_tools=[{"name": "get_pod_logs", "is_destructive": False, "pre_approved": False}],
            agent_cluster_ids=[1, 2],
            agent_minion_ids=["node-1"],
            agent_max_retries=3,
            agent_timeout_seconds=900,
            agent_approval_timeout_seconds=600,
            created_by="admin",
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        assert wf.id is not None
        assert wf.workflow_type == "agent"
        assert wf.agent_cluster_ids == [1, 2]
        assert wf.agent_max_retries == 3
        assert wf.agent_approved_tools[0]["name"] == "get_pod_logs"

def test_scripted_workflow_defaults_unaffected(engine):
    with Session(engine) as db:
        wf = Workflow(name="scripted", created_by="admin")
        db.add(wf)
        db.commit()
        db.refresh(wf)
        assert wf.workflow_type == "scripted"
        assert wf.agent_goal is None
        assert wf.agent_cluster_ids == []
