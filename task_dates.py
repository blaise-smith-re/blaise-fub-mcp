"""Deterministic, timezone-safe due-date parsing and filtering for FUB tasks.

FUB's own `due=<keyword>` server-side filter is independently verified
unreliable — FUB 06 v1.6 (Aug 30, 2026): `due=today` missed a real
due-today task, and `due=tomorrow` / specific-date inputs could be silently
ignored rather than correctly filtering. This module never relies on that
filter for correctness. Callers retrieve the complete matching task set
(`fub_client.FUBClient.search_tasks_all`) and filter here, client-side,
against each task's raw `dueDate`/`dueDateTime` field.

Filtering is by CALENDAR DATE, not instant. A FUB task's `dueDate` (e.g.
"2026-08-30") is a bare calendar date with no time-of-day or timezone
component. Treating it as a UTC instant and comparing across a timezone
boundary produces exactly the kind of off-by-one-day bug this module exists
to prevent — a task due "2026-08-30" would already read as past-due in
America/Chicago hours before midnight UTC. `dueDateTime` (an explicit
instant, when a task carries one) is converted into the target timezone and
reduced to a calendar date the same way, so "due today" means the same
thing regardless of which field a task happens to use.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_timezone(name: str) -> ZoneInfo:
    """Resolve an IANA timezone name, raising a clear error for an invalid one."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Unknown due_timezone {name!r}. Use an IANA zone name, e.g. 'America/Chicago' or 'UTC'."
        ) from exc


def parse_calendar_date(value: str, *, field_label: str) -> date:
    """Strictly parse a YYYY-MM-DD calendar date.

    Never silently ignores bad input: unsupported syntax ("tomorrow",
    "08/30/2026", "next week", an empty string, a bare year) raises
    ValueError immediately with a message naming the offending field.
    """
    text = value.strip()
    if len(text) != 10:
        raise ValueError(
            f"{field_label} {value!r} is not a valid date. Use exact ISO "
            "calendar-date syntax YYYY-MM-DD (e.g. '2026-08-30')."
        )
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"{field_label} {value!r} is not a valid date. Use exact ISO "
            "calendar-date syntax YYYY-MM-DD (e.g. '2026-08-30')."
        ) from exc


def task_due_local_date(task: dict[str, Any], tz: ZoneInfo) -> date | None:
    """The calendar date a task is due, in `tz`, or None if it has no usable due date."""
    due_datetime = task.get("dueDateTime")
    if due_datetime:
        try:
            parsed = datetime.fromisoformat(str(due_datetime).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            # An instant field with no explicit offset is ambiguous/unsupported
            # syntax from the API, not something to guess a timezone for.
            return None
        return parsed.astimezone(tz).date()

    due_date = task.get("dueDate")
    if due_date:
        try:
            # dueDate is a bare calendar date already; take it as-is, no
            # timezone conversion, so it never shifts across a day boundary.
            return date.fromisoformat(str(due_date)[:10])
        except ValueError:
            return None

    return None


def filter_tasks_by_due_date(
    tasks: list[dict[str, Any]],
    *,
    due_on: date | None,
    due_from: date | None,
    due_to: date | None,
    tz: ZoneInfo,
) -> tuple[list[dict[str, Any]], int]:
    """Return (matching tasks, count excluded for having no usable due date).

    A task with no parseable due date never matches an exact-date or bounded
    filter. It is excluded and counted separately, rather than silently
    treated the same as a task that was checked and simply didn't match, so
    the caller can tell "zero due today" apart from "some tasks couldn't be
    evaluated."
    """
    if due_on is None and due_from is None and due_to is None:
        return list(tasks), 0
    matched: list[dict[str, Any]] = []
    unusable = 0
    for task in tasks:
        local_date = task_due_local_date(task, tz)
        if local_date is None:
            unusable += 1
            continue
        if due_on is not None and local_date != due_on:
            continue
        if due_from is not None and local_date < due_from:
            continue
        if due_to is not None and local_date > due_to:
            continue
        matched.append(task)
    return matched, unusable
