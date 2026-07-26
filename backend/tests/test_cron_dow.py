"""Crontab day-of-week must survive the trip into APScheduler.

APScheduler's CronTrigger.from_crontab() passes the day-of-week field straight
into a field where 0 = MONDAY, while a crontab expression means 0 = SUNDAY. It
does not translate, so every schedule fired exactly one day late: picking
Saturday (cron 6) scheduled Sunday.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.patch_service import cron_trigger

# Sunday 2026-07-26 12:00 — the search always looks forward from here.
_FROM = datetime(2026, 7, 26, 12, 0, tzinfo=ZoneInfo("UTC"))


@pytest.mark.parametrize("dow,expected", [
    (0, "Sunday"),
    (1, "Monday"),
    (2, "Tuesday"),
    (3, "Wednesday"),
    (4, "Thursday"),
    (5, "Friday"),
    (6, "Saturday"),
    (7, "Sunday"),   # crontab allows 7 as a second spelling of Sunday
])
def test_numeric_day_of_week_matches_crontab_convention(dow, expected):
    nxt = cron_trigger(f"0 2 * * {dow}", "UTC").get_next_fire_time(None, _FROM)
    assert nxt.strftime("%A") == expected


def test_day_is_correct_in_a_non_utc_timezone():
    # The reported symptom was noticed on Asia/Kolkata; the bug is timezone
    # independent, but the fix must not break a tz with a half-hour offset.
    nxt = cron_trigger("0 2 * * 6", "Asia/Kolkata").get_next_fire_time(
        None, _FROM.astimezone(ZoneInfo("Asia/Kolkata")))
    assert nxt.strftime("%A") == "Saturday"
    assert (nxt.hour, nxt.minute) == (2, 0)


def test_wildcard_and_ranges_are_preserved():
    every_day = cron_trigger("0 2 * * *", "UTC").get_next_fire_time(None, _FROM)
    assert every_day.strftime("%A") == "Monday"          # next 02:00 after Sun noon

    # Mon-Fri: from Sunday noon the next weekday is Monday.
    weekdays = cron_trigger("0 2 * * 1-5", "UTC").get_next_fire_time(None, _FROM)
    assert weekdays.strftime("%A") == "Monday"

    # A comma list must not collapse or shift.
    sat_sun = cron_trigger("0 2 * * 0,6", "UTC").get_next_fire_time(None, _FROM)
    assert sat_sun.strftime("%A") == "Saturday"


def test_named_days_still_work():
    nxt = cron_trigger("0 2 * * sat", "UTC").get_next_fire_time(None, _FROM)
    assert nxt.strftime("%A") == "Saturday"


def test_invalid_expression_still_raises():
    with pytest.raises(ValueError):
        cron_trigger("not a cron", "UTC")
