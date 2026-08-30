"""Unit tests for task_dates.py: strict date-syntax validation and
timezone-safe due-date classification (task-retrieval hardening).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from task_dates import (
    filter_tasks_by_due_date,
    parse_calendar_date,
    resolve_timezone,
    task_due_local_date,
)

CHICAGO = resolve_timezone("America/Chicago")
UTC = resolve_timezone("UTC")


# ---------- resolve_timezone ----------


def test_resolve_timezone_accepts_valid_iana_name():
    assert resolve_timezone("America/Chicago") is not None
    assert resolve_timezone("UTC") is not None


@pytest.mark.parametrize("bad", ["Mars/Colony", "not-a-timezone", "CST", "", "America/Nowhere"])
def test_resolve_timezone_rejects_invalid_name_with_clear_error(bad):
    with pytest.raises(ValueError, match="[Uu]nknown|[Tt]imezone"):
        resolve_timezone(bad)


# ---------- parse_calendar_date: invalid date syntax ----------


@pytest.mark.parametrize(
    "bad",
    [
        "tomorrow",
        "next week",
        "today",
        "08/30/2026",
        "2026/08/30",
        "",
        "   ",
        "2026-13-45",
        "2026-02-30",  # not a real calendar date
        "2026-08-30T00:00:00Z",  # a full datetime is not an exact calendar date
        "20260830",
        "Aug 30 2026",
        "2026-8-30",  # not zero-padded — not exact ISO syntax
    ],
)
def test_parse_calendar_date_rejects_unsupported_syntax(bad):
    with pytest.raises(ValueError, match="due_on"):
        parse_calendar_date(bad, field_label="due_on")


def test_parse_calendar_date_accepts_exact_iso_date():
    assert parse_calendar_date("2026-08-30", field_label="due_on") == date(2026, 8, 30)


def test_parse_calendar_date_error_names_the_field():
    with pytest.raises(ValueError, match="due_from"):
        parse_calendar_date("garbage", field_label="due_from")


# ---------- task_due_local_date: no due date ----------


def test_no_due_date_returns_none():
    assert task_due_local_date({"id": 1}, CHICAGO) is None
    assert task_due_local_date({"id": 1, "dueDate": None, "dueDateTime": None}, CHICAGO) is None


def test_unparseable_due_date_returns_none_not_a_crash():
    assert task_due_local_date({"dueDate": "not-a-date"}, CHICAGO) is None
    assert task_due_local_date({"dueDateTime": "garbage"}, CHICAGO) is None


def test_instant_without_explicit_offset_is_treated_as_unusable():
    """A naive dueDateTime (no Z, no offset) is ambiguous — never guess a timezone for it."""
    assert task_due_local_date({"dueDateTime": "2026-08-30T10:00:00"}, CHICAGO) is None


# ---------- task_due_local_date: bare dueDate is a calendar date, not an instant ----------


def test_bare_due_date_is_taken_as_is_regardless_of_timezone():
    task = {"dueDate": "2026-08-30"}
    assert task_due_local_date(task, CHICAGO) == date(2026, 8, 30)
    assert task_due_local_date(task, UTC) == date(2026, 8, 30)
    assert task_due_local_date(task, resolve_timezone("Pacific/Kiritimati")) == date(2026, 8, 30)


# ---------- America/Chicago day-boundary correctness (dueDateTime) ----------


def test_chicago_boundary_late_evening_task_is_still_todays_date_in_chicago():
    """10:30pm Chicago time on Aug 30 is 04:30 UTC on Aug 31 (CDT, UTC-5).

    Naively treating the UTC instant as the due date would misclassify this
    as due Aug 31. The correct classification depends on which timezone the
    caller asks about, and must use calendar-date semantics in that zone —
    not a UTC-instant comparison.
    """
    task = {"dueDateTime": "2026-08-31T04:30:00Z"}
    assert task_due_local_date(task, CHICAGO) == date(2026, 8, 30)
    assert task_due_local_date(task, UTC) == date(2026, 8, 31)


def test_chicago_boundary_opposite_direction_early_utc_hour_is_still_yesterday_in_chicago():
    """02:15 UTC on Aug 30 is 9:15pm CDT on Aug 29 (UTC-5) — a task that has already
    rolled into "today" by UTC clock time is still due "yesterday" by Chicago wall
    clock. Both directions of the boundary must classify correctly, independently.
    """
    task = {"dueDateTime": "2026-08-30T02:15:00Z"}
    assert task_due_local_date(task, UTC) == date(2026, 8, 30)
    assert task_due_local_date(task, CHICAGO) == date(2026, 8, 29)


def test_due_today_classification_matches_across_dueDate_and_dueDateTime_forms():
    """'Due today' must mean the same thing whichever field a task happens to carry."""
    bare_date_task = {"dueDate": "2026-08-30"}
    instant_task = {"dueDateTime": "2026-08-30T15:00:00-05:00"}  # 3pm Chicago on Aug 30
    assert task_due_local_date(bare_date_task, CHICAGO) == date(2026, 8, 30)
    assert task_due_local_date(instant_task, CHICAGO) == date(2026, 8, 30)


# ---------- filter_tasks_by_due_date: due today / overdue / future / no due date ----------


TODAY = date(2026, 8, 30)
YESTERDAY = date(2026, 8, 29)
TOMORROW = date(2026, 8, 31)

DUE_TODAY: dict[str, Any] = {"id": 1, "dueDate": "2026-08-30"}
DUE_YESTERDAY: dict[str, Any] = {"id": 2, "dueDate": "2026-08-29"}
DUE_TOMORROW: dict[str, Any] = {"id": 3, "dueDate": "2026-08-31"}
DUE_LAST_WEEK: dict[str, Any] = {"id": 4, "dueDate": "2026-08-23"}
DUE_NEXT_WEEK: dict[str, Any] = {"id": 5, "dueDate": "2026-09-06"}
NO_DUE_DATE: dict[str, Any] = {"id": 6}

ALL_TASKS: list[dict[str, Any]] = [DUE_TODAY, DUE_YESTERDAY, DUE_TOMORROW, DUE_LAST_WEEK, DUE_NEXT_WEEK, NO_DUE_DATE]


def test_due_today_filter():
    matched, unusable = filter_tasks_by_due_date(ALL_TASKS, due_on=TODAY, due_from=None, due_to=None, tz=CHICAGO)
    assert [t["id"] for t in matched] == [1]
    assert unusable == 1  # NO_DUE_DATE


def test_overdue_filter_uses_due_to_yesterday():
    matched, _ = filter_tasks_by_due_date(ALL_TASKS, due_on=None, due_from=None, due_to=YESTERDAY, tz=CHICAGO)
    assert {t["id"] for t in matched} == {2, 4}


def test_future_due_filter_uses_due_from_tomorrow():
    matched, _ = filter_tasks_by_due_date(ALL_TASKS, due_on=None, due_from=TOMORROW, due_to=None, tz=CHICAGO)
    assert {t["id"] for t in matched} == {3, 5}


def test_bounded_range_filter():
    matched, _ = filter_tasks_by_due_date(ALL_TASKS, due_on=None, due_from=YESTERDAY, due_to=TOMORROW, tz=CHICAGO)
    assert {t["id"] for t in matched} == {1, 2, 3}


def test_no_due_date_task_never_matches_any_filter_and_is_counted_separately():
    matched, unusable = filter_tasks_by_due_date([NO_DUE_DATE], due_on=TODAY, due_from=None, due_to=None, tz=CHICAGO)
    assert matched == []
    assert unusable == 1


def test_no_filters_at_all_returns_everything_unfiltered_and_zero_unusable():
    matched, unusable = filter_tasks_by_due_date(ALL_TASKS, due_on=None, due_from=None, due_to=None, tz=CHICAGO)
    assert matched == ALL_TASKS
    assert unusable == 0


def test_chicago_boundary_task_correctly_bucketed_by_due_today_filter():
    """The core boundary regression: a task 'due today' in Chicago must be found by
    a due_on=today(Chicago) filter even though its raw instant is already tomorrow
    in UTC."""
    boundary_task = {"id": 99, "dueDateTime": "2026-08-31T04:30:00Z"}
    matched_chicago, _ = filter_tasks_by_due_date(
        [boundary_task], due_on=date(2026, 8, 30), due_from=None, due_to=None, tz=CHICAGO
    )
    assert [t["id"] for t in matched_chicago] == [99]

    matched_utc, _ = filter_tasks_by_due_date(
        [boundary_task], due_on=date(2026, 8, 30), due_from=None, due_to=None, tz=UTC
    )
    assert matched_utc == []  # in UTC this task is due the 31st, not the 30th
