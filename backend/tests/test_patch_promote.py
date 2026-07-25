"""Promote carries the source stage's frozen package list downstream.

Regression cover for a silent no-op: `apply_to_stage` only stores
`custom_packages` for an explicit Custom run, so promoting after a Security or
All-updates apply used to dispatch an EMPTY package list — `apt-get install -y`
with no arguments (no-op) and `dnf` exit 2 (failure) — while still recording the
promotion as done.
"""
import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, patch as mock_patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.ext.asyncio.session import AsyncSession

# KeyBlueprint FKs to Blueprint, but nothing in this file's import graph loads
# app.models.blueprint. Without this, create_all() raises NoReferencedTableError
# when the file runs standalone (repo-wide gap; same fix as test_patch_drift.py).
import app.main  # noqa: F401 — registers every SQLModel table before create_all

from app.models.minion import Minion
from app.models.patch import (
    MinionGroup, MinionGroupMember, Organisation, PatchPipeline, PatchPromotion,
    PatchPromotionResult, PipelineStage,
)
from app.models.user import User


@pytest.fixture(name="engine")
def engine_fixture():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(name="client")
def client_fixture(engine):
    from app.main import app
    from app.api.deps import get_async_db, get_current_user, require_god_mode

    async_url = str(engine.url).replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_async_db():
        async with _AsyncSessionLocal() as session:
            yield session

    god = User(username="admin", email="a@t.com", hashed_password="x", role="god")
    app.dependency_overrides[get_async_db] = override_async_db
    app.dependency_overrides[get_current_user] = lambda: god
    app.dependency_overrides[require_god_mode] = lambda: god

    with mock_patch("app.services.patch_service.AsyncSessionLocal", _AsyncSessionLocal), \
         mock_patch("app.core.db.engine", engine):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
    asyncio.run(_async_engine.dispose())


def _seed(engine, *, applied: list[dict] | None, result_status: str = "done"):
    """dev+qa pipeline where dev has one completed all-scope run.

    `applied` is the advisory snapshot recorded for dev's host — the thing the
    promote path must reconstruct the package list from. None means the run
    recorded nothing.
    """
    with Session(engine) as db:
        org = Organisation(name="T", slug="t-promote"); db.add(org); db.flush()
        pipe = PatchPipeline(org_id=org.id, name="p"); db.add(pipe); db.flush()
        stages = {}
        for order, name in enumerate(("dev", "qa")):
            grp = MinionGroup(org_id=org.id, name=f"{name}-grp"); db.add(grp); db.flush()
            st = PipelineStage(pipeline_id=pipe.id, group_id=grp.id, order=order, name=name)
            db.add(st); db.flush()
            stages[name] = st.id
            mid = f"{name}-host"
            db.add(Minion(id=mid, hostname=mid, status="active", grains='{"os":"Ubuntu"}'))
            db.add(MinionGroupMember(group_id=grp.id, minion_id=mid))
        # dev's completed run: scope "all", so custom_packages stays None.
        promo = PatchPromotion(
            pipeline_id=pipe.id, to_stage_id=stages["dev"], patch_scope="all",
            custom_packages=None, triggered_by="t", status="done",
        )
        db.add(promo); db.flush()
        db.add(PatchPromotionResult(
            promotion_id=promo.id, minion_id="dev-host", status=result_status,
            exit_code=0, applied_advisories=json.dumps(applied or []),
            packages_count=len(applied or []),
        ))
        db.commit()
        return pipe.id, stages


def _adv(advisory_id, package_name):
    return {"advisory_id": advisory_id, "package_name": package_name,
            "severity": "high", "from_version": "1.0", "to_version": "1.1"}


def test_promote_after_all_scope_apply_carries_the_applied_packages(client, engine):
    pid, stages = _seed(engine, applied=[_adv("A-2", "openssl"), _adv("A-1", "nginx")])

    with mock_patch("app.services.minion_service.manager") as mgr:
        mgr.dispatch_job = AsyncMock(return_value={"exit_code": 0, "output": ""})
        mgr._connections = {}
        r = client.post(f"/api/v1/patches/pipelines/{pid}/stages/{stages['dev']}/promote")

    assert r.status_code == 200, r.text
    with Session(engine) as db:
        promo = db.exec(select(PatchPromotion).where(
            PatchPromotion.to_stage_id == stages["qa"])).first()
        # Sorted + de-duplicated package names, NOT an empty list.
        assert json.loads(promo.custom_packages) == ["nginx", "openssl"]


def test_promote_refuses_when_the_source_run_applied_nothing(client, engine):
    # Previously this dispatched `apt-get install -y` with no packages and
    # recorded a successful promotion.
    pid, stages = _seed(engine, applied=[])

    r = client.post(f"/api/v1/patches/pipelines/{pid}/stages/{stages['dev']}/promote")

    assert r.status_code == 400
    assert "nothing to promote" in r.json()["detail"]
    with Session(engine) as db:
        assert db.exec(select(PatchPromotion).where(
            PatchPromotion.to_stage_id == stages["qa"])).first() is None


def test_promote_ignores_packages_from_hosts_that_failed(client, engine):
    # A host that errored did not receive the packages, so its snapshot must not
    # become part of the frozen list promoted downstream.
    pid, stages = _seed(engine, applied=[_adv("A-1", "nginx")], result_status="failed")

    r = client.post(f"/api/v1/patches/pipelines/{pid}/stages/{stages['dev']}/promote")

    assert r.status_code == 400
