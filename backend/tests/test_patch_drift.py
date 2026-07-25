"""Unit tests for the drift arithmetic. No database — pure set math."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.services.patch_drift import (
    advisory_key, advisory_meta, applied_keys, as_utc, percent, window_cutoff,
)


def _entry(advisory_id, package_name, severity="none"):
    return {
        "advisory_id": advisory_id, "package_name": package_name,
        "severity": severity, "from_version": "1.0", "to_version": "1.1",
    }


def test_advisory_key_prefers_advisory_id():
    assert advisory_key(_entry("RHSA-2024:1234", "openssl")) == "RHSA-2024:1234"


def test_advisory_key_falls_back_to_package_name_for_apt_and_winget():
    # apt/winget hosts have no advisory id — the package name is the identity.
    assert advisory_key(_entry(None, "openssl")) == "openssl"


def test_advisory_key_empty_when_nothing_identifies_it():
    assert advisory_key({}) == ""


def test_applied_keys_parses_a_result_blob():
    raw = json.dumps([_entry("A-1", "nginx"), _entry(None, "curl")])
    assert applied_keys(raw) == {"A-1", "curl"}


def test_applied_keys_survives_garbage():
    # A malformed blob must not take the whole dashboard down.
    assert applied_keys(None) == set()
    assert applied_keys("") == set()
    assert applied_keys("not json") == set()
    assert applied_keys('{"not": "a list"}') == set()
    assert applied_keys('[null, 3, "x"]') == set()


def test_applied_keys_drops_unidentifiable_entries():
    assert applied_keys(json.dumps([_entry(None, None), _entry("A-1", "nginx")])) == {"A-1"}


def test_advisory_meta_indexes_by_key():
    raw = json.dumps([_entry("A-1", "nginx", "critical")])
    meta = advisory_meta(raw)
    assert meta["A-1"]["package_name"] == "nginx"
    assert meta["A-1"]["severity"] == "critical"
    assert meta["A-1"]["advisory_id"] == "A-1"


def test_percent_is_share_of_reference_covered():
    assert percent({"a", "b", "c", "d"}, {"a", "b"}) == 50


def test_percent_is_none_when_there_is_no_reference():
    # Nothing to catch up with is NOT the same as being caught up. Returning
    # 100 here would tell an operator prod is fine when dev has never run.
    assert percent(set(), {"a"}) is None


def test_percent_ignores_extras_the_stage_has_beyond_the_reference():
    assert percent({"a"}, {"a", "b", "c"}) == 100


def test_percent_rounds_to_whole_number():
    assert percent({"a", "b", "c"}, {"a"}) == 33


def test_window_cutoff_none_for_latest_and_all():
    assert window_cutoff("latest") is None
    assert window_cutoff("all") is None


def test_window_cutoff_is_in_the_past_for_day_windows():
    now = datetime.now(timezone.utc)
    assert timedelta(days=29) < now - window_cutoff("30d") < timedelta(days=31)
    assert timedelta(days=89) < now - window_cutoff("90d") < timedelta(days=91)


def test_as_utc_stamps_naive_datetimes():
    # SQLite hands back naive datetimes even for timezone=True columns, and
    # comparing those to an aware cutoff raises TypeError at runtime.
    naive = datetime(2026, 7, 1, 12, 0, 0)
    assert as_utc(naive).tzinfo is timezone.utc


def test_as_utc_leaves_aware_datetimes_and_none_alone():
    aware = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert as_utc(aware) is aware
    assert as_utc(None) is None


# ── Integration tests: aggregation over a seeded pipeline ────────────────────
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from unittest.mock import patch as mock_patch

from app.models.patch import (
    Organisation, MinionGroup, MinionGroupMember, PatchPipeline, PipelineStage,
    PatchPromotion, PatchPromotionResult, PatchSchedule,
)
from app.models.minion import Minion
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

    god_user = User(username="admin", email="admin@test.com", hashed_password="x", role="god")
    app.dependency_overrides[get_async_db] = override_async_db
    app.dependency_overrides[get_current_user] = lambda: god_user
    app.dependency_overrides[require_god_mode] = lambda: god_user

    with mock_patch("app.core.db.engine", engine):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
    asyncio.run(_async_engine.dispose())


def _adv(advisory_id, package_name, severity="none"):
    return {
        "advisory_id": advisory_id, "package_name": package_name,
        "severity": severity, "from_version": "1.0", "to_version": "1.1",
    }


def _seed(engine, *, stage_names=("dev", "qa"), devices_per_stage=1):
    """Build a pipeline with one group per stage and N devices per group.

    Returns (pipeline_id, {stage_name: stage_id}, {stage_name: [minion_id,...]}).
    """
    with Session(engine) as db:
        org = Organisation(name="T", slug="t-drift"); db.add(org); db.flush()
        pipeline = PatchPipeline(org_id=org.id, name="linux-monthly"); db.add(pipeline); db.flush()
        stage_ids, minion_ids = {}, {}
        for order, name in enumerate(stage_names):
            grp = MinionGroup(org_id=org.id, name=f"{name}-grp"); db.add(grp); db.flush()
            st = PipelineStage(pipeline_id=pipeline.id, group_id=grp.id, order=order, name=name)
            db.add(st); db.flush()
            stage_ids[name] = st.id
            minion_ids[name] = []
            for i in range(devices_per_stage):
                mid = f"{name}-m{i}"
                db.add(Minion(id=mid, hostname=f"{name}-host-{i}", status="active", grains='{"os":"Ubuntu"}'))
                db.add(MinionGroupMember(group_id=grp.id, minion_id=mid))
                minion_ids[name].append(mid)
        db.commit()
        return pipeline.id, stage_ids, minion_ids


def _run(engine, pipeline_id, stage_id, per_minion, *, completed_at=None,
         promo_status="done", result_status="done"):
    """Record a completed promotion into a stage.

    per_minion: {minion_id: [advisory dicts]}
    """
    with Session(engine) as db:
        promo = PatchPromotion(
            pipeline_id=pipeline_id, to_stage_id=stage_id, patch_scope="all",
            triggered_by="test", status=promo_status,
            completed_at=completed_at or datetime.now(timezone.utc),
        )
        db.add(promo); db.flush()
        for mid, advs in per_minion.items():
            db.add(PatchPromotionResult(
                promotion_id=promo.id, minion_id=mid, status=result_status,
                exit_code=0, applied_advisories=json.dumps(advs), packages_count=len(advs),
            ))
        db.commit()
        return promo.id


def _stage(payload, name):
    return next(s for s in payload["stages"] if s["name"] == name)


def test_qa_that_took_half_of_dev_reads_fifty_percent(client, engine):
    pid, stages, minions = _seed(engine)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [
        _adv("A-1", "nginx"), _adv("A-2", "curl"), _adv("A-3", "bash"), _adv("A-4", "zlib")]})
    _run(engine, pid, stages["qa"], {minions["qa"][0]: [_adv("A-1", "nginx"), _adv("A-2", "curl")]})

    r = client.get(f"/api/v1/patches/pipelines/{pid}/drift")
    assert r.status_code == 200
    qa = _stage(r.json(), "qa")
    assert qa["percent"] == 50
    assert qa["ref_total"] == 4
    assert qa["matched"] == 2
    assert qa["reference_stage_name"] == "dev"


def test_first_stage_is_baseline_not_zero(client, engine):
    pid, stages, minions = _seed(engine)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [_adv("A-1", "nginx")]})

    dev = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift").json(), "dev")
    assert dev["percent"] is None
    assert dev["reference_stage_id"] is None
    assert dev["devices_covered"] is None


def test_reference_that_never_ran_gives_none_not_a_hundred(client, engine):
    pid, stages, minions = _seed(engine)
    _run(engine, pid, stages["qa"], {minions["qa"][0]: [_adv("A-1", "nginx")]})

    qa = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift").json(), "qa")
    assert qa["percent"] is None
    assert qa["ref_total"] == 0


def test_latest_window_ignores_the_older_reference_run_that_all_includes(client, engine):
    pid, stages, minions = _seed(engine)
    old = datetime.now(timezone.utc) - timedelta(days=200)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [_adv("OLD-1", "openssl")]}, completed_at=old)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [_adv("NEW-1", "nginx")]})
    _run(engine, pid, stages["qa"], {minions["qa"][0]: [_adv("NEW-1", "nginx")]})

    latest = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift?window=latest").json(), "qa")
    assert latest["ref_total"] == 1 and latest["percent"] == 100

    everything = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift?window=all").json(), "qa")
    assert everything["ref_total"] == 2 and everything["percent"] == 50

    ninety = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift?window=90d").json(), "qa")
    assert ninety["ref_total"] == 1


def test_stage_run_outside_the_window_still_counts_toward_the_numerator(client, engine):
    # The asymmetry: the window bounds what qa is measured AGAINST, never what
    # qa has done. A qa run from 200 days ago still credits qa today.
    pid, stages, minions = _seed(engine)
    old = datetime.now(timezone.utc) - timedelta(days=200)
    _run(engine, pid, stages["qa"], {minions["qa"][0]: [_adv("A-1", "nginx")]}, completed_at=old)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [_adv("A-1", "nginx")]})

    qa = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift?window=latest").json(), "qa")
    assert qa["percent"] == 100


def test_failed_result_inside_a_partial_promotion_is_not_credited(client, engine):
    pid, stages, minions = _seed(engine)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [_adv("A-1", "nginx")]})
    _run(engine, pid, stages["qa"], {minions["qa"][0]: [_adv("A-1", "nginx")]},
         promo_status="partial", result_status="failed")

    qa = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift").json(), "qa")
    assert qa["percent"] == 0
    assert qa["devices_covered"] == 0


def test_apt_hosts_without_advisory_ids_match_by_package_name(client, engine):
    pid, stages, minions = _seed(engine)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [_adv(None, "openssl")]})
    _run(engine, pid, stages["qa"], {minions["qa"][0]: [_adv(None, "openssl")]})

    assert _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift").json(), "qa")["percent"] == 100


def test_never_patched_device_counts_in_total_but_not_covered(client, engine):
    pid, stages, minions = _seed(engine, devices_per_stage=2)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [_adv("A-1", "nginx")]})
    _run(engine, pid, stages["qa"], {minions["qa"][0]: [_adv("A-1", "nginx")]})

    qa = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift").json(), "qa")
    assert qa["devices_total"] == 2
    assert qa["devices_covered"] == 1
    behind = next(d for d in qa["devices"] if d["minion_id"] == minions["qa"][1])
    assert behind["percent"] == 0 and behind["last_patched"] is None


def test_missing_lists_advisories_some_devices_lack_with_the_devices_named(client, engine):
    pid, stages, minions = _seed(engine, devices_per_stage=2)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [
        _adv("A-1", "nginx", "critical"), _adv("A-2", "kernel", "high")]})
    # One qa box got both, the other only A-1.
    _run(engine, pid, stages["qa"], {
        minions["qa"][0]: [_adv("A-1", "nginx"), _adv("A-2", "kernel")],
        minions["qa"][1]: [_adv("A-1", "nginx")],
    })

    qa = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift").json(), "qa")
    # Union covers both, so the stage reads 100 — but a box is still behind.
    assert qa["percent"] == 100
    assert qa["devices_covered"] == 1
    assert [m["key"] for m in qa["missing"]] == ["A-2"]
    assert qa["missing"][0]["affected_minion_ids"] == [minions["qa"][1]]
    assert qa["missing"][0]["severity"] == "high"


def test_devices_are_sorted_worst_first(client, engine):
    pid, stages, minions = _seed(engine, devices_per_stage=3)
    _run(engine, pid, stages["dev"], {minions["dev"][0]: [_adv("A-1", "a"), _adv("A-2", "b")]})
    _run(engine, pid, stages["qa"], {
        minions["qa"][0]: [_adv("A-1", "a"), _adv("A-2", "b")],   # 100
        minions["qa"][1]: [_adv("A-1", "a")],                      # 50
    })                                                              # qa-m2: 0

    qa = _stage(client.get(f"/api/v1/patches/pipelines/{pid}/drift").json(), "qa")
    assert [d["percent"] for d in qa["devices"]] == [0, 50, 100]


def test_live_schedule_is_attached_and_superseded_ones_ignored(client, engine):
    pid, stages, _ = _seed(engine)
    with Session(engine) as db:
        db.add(PatchSchedule(
            pipeline_id=pid, stage_id=stages["qa"], cron_expr="0 9 * * 1",
            timezone="UTC", patch_scope="all", created_by="old",
            superseded_at=datetime.now(timezone.utc)))
        db.add(PatchSchedule(
            pipeline_id=pid, stage_id=stages["qa"], cron_expr="0 2 * * 6",
            timezone="Europe/London", patch_scope="all", created_by="t"))
        db.commit()

    payload = client.get(f"/api/v1/patches/pipelines/{pid}/drift").json()
    assert _stage(payload, "qa")["schedule"]["cron_expr"] == "0 2 * * 6"
    assert _stage(payload, "qa")["schedule"]["timezone"] == "Europe/London"
    assert _stage(payload, "dev")["schedule"] is None


def test_empty_pipeline_and_bad_input(client, engine):
    pid, _, _ = _seed(engine, stage_names=())
    assert client.get(f"/api/v1/patches/pipelines/{pid}/drift").json()["stages"] == []
    assert client.get("/api/v1/patches/pipelines/does-not-exist/drift").status_code == 404
    assert client.get(f"/api/v1/patches/pipelines/{pid}/drift?window=nonsense").status_code == 400
