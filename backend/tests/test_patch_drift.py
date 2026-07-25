"""Unit tests for the drift arithmetic. No database — pure set math."""
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
