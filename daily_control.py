"""Read-only daily-control audit logic.

Pure functions operating on already-fetched FUB API data. Kept separate from
server.py / fub_client.py so the control-gap logic can be unit tested without
mocking HTTP or the MCP transport.

Every finding carries the evidence it was derived from. Where the API's
silence cannot prove an absence (e.g. no notes, no events), the finding says
so explicitly rather than asserting "no interaction occurred."
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _task_due(task: dict[str, Any]) -> datetime | None:
    return _parse_dt(task.get("dueDateTime")) or _parse_dt(task.get("dueDate"))


def _task_evidence(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "type": t.get("type"),
            "dueDate": t.get("dueDate"),
            "dueDateTime": t.get("dueDateTime"),
            "assignedUserId": t.get("assignedUserId"),
        }
        for t in tasks
    ]


def _duplicate_task_groups(open_tasks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for t in open_tasks:
        key = (
            str(t.get("name") or "").strip().casefold(),
            str(t.get("type") or "").strip().casefold(),
            str(t.get("dueDate") or t.get("dueDateTime") or ""),
        )
        buckets.setdefault(key, []).append(t)
    return [group for group in buckets.values() if len(group) > 1]


def _same_day_conflicts(
    open_tasks: list[dict[str, Any]], duplicate_groups: list[list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    duplicate_ids = {t.get("id") for group in duplicate_groups for t in group}
    non_duplicates = [t for t in open_tasks if t.get("id") not in duplicate_ids]
    by_day: dict[str, list[dict[str, Any]]] = {}
    for t in non_duplicates:
        due = _task_due(t)
        if due is None:
            continue
        by_day.setdefault(due.date().isoformat(), []).append(t)
    conflicts: list[dict[str, Any]] = []
    for tasks in by_day.values():
        if len(tasks) > 1:
            conflicts.extend(_task_evidence(tasks))
    return conflicts


def _latest_note(notes: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, int]:
    """Return (most recent dateable note, count of notes with no usable date).

    The undateable count is returned separately so a contact whose notes exist
    but cannot be dated is never reported as having no notes at all.
    """
    best: dict[str, Any] | None = None
    best_dt: datetime | None = None
    undateable = 0
    for n in notes:
        dt = _parse_dt(n.get("created")) or _parse_dt(n.get("updated")) or _parse_dt(n.get("date"))
        if dt is None:
            undateable += 1
            continue
        if best_dt is None or dt > best_dt:
            best_dt = dt
            best = {**n, "_parsed_created": dt}
    return best, undateable


# The stale-note threshold is an ENGINEERING DEFAULT chosen for this connector.
# It is not drawn from FUB 05, which defines no note-staleness interval (its
# only numeric review interval is "Qualify leads older than seven days", a
# different rule about a different object). Findings derived from it are
# advisory prompts for human review, never a policy determination.
STALE_NOTE_THRESHOLD_BASIS = "implementation_default"
STALE_NOTE_ADVISORY = (
    "Advisory only. The staleness threshold is an implementation default for this "
    "connector, not established Follow Up Boss business policy and not a rule "
    "defined by FUB 05. Adjust stale_note_days per call to match the actual "
    "operating rhythm for this relationship."
)


def find_gaps(
    *,
    person: dict[str, Any],
    open_tasks: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    expected_assigned_user_id: int | None = None,
    stale_note_days: int = 21,
) -> list[dict[str, Any]]:
    """Evaluate evidence-supported control gaps for one contact.

    `events` is accepted for completeness (future evidence use) but is
    deliberately NOT used to conclude "no interaction occurred" — an FUB
    events feed returning nothing does not prove nothing happened.
    """
    now = now or datetime.now(UTC)
    findings: list[dict[str, Any]] = []

    due_dates = [(t, _task_due(t)) for t in open_tasks]
    future_tasks = [t for t, due in due_dates if due is None or due >= now]
    overdue_tasks = [t for t, due in due_dates if due is not None and due < now]

    if not open_tasks:
        findings.append(
            {
                "gap_type": "no_future_task",
                "summary": "No open task exists for this contact.",
                "evidence": {"open_task_count": 0},
            }
        )
    elif not future_tasks:
        findings.append(
            {
                "gap_type": "no_future_task",
                "summary": "Every open task is overdue; none is scheduled in the future.",
                "evidence": {"open_tasks": _task_evidence(open_tasks)},
            }
        )

    if overdue_tasks:
        findings.append(
            {
                "gap_type": "overdue_tasks",
                "summary": f"{len(overdue_tasks)} open task(s) past their due date.",
                "evidence": {"overdue_tasks": _task_evidence(overdue_tasks)},
            }
        )

    duplicate_groups = _duplicate_task_groups(open_tasks)
    if duplicate_groups:
        findings.append(
            {
                "gap_type": "exact_duplicate_open_tasks",
                "summary": f"{len(duplicate_groups)} group(s) of exact-duplicate open tasks "
                "(same name, type, and due date).",
                "evidence": {"groups": [_task_evidence(g) for g in duplicate_groups]},
            }
        )

    same_day = _same_day_conflicts(open_tasks, duplicate_groups)
    if same_day:
        findings.append(
            {
                "gap_type": "conflicting_next_actions",
                "summary": "Multiple non-duplicate open tasks are due the same day; unclear "
                "which is the intended next action.",
                "evidence": {"tasks": same_day},
                "caveat": "Heuristic (same-day, differently named/typed open tasks). "
                "Confirm an actual conflict before acting.",
            }
        )

    latest_note, undateable_notes = _latest_note(notes)
    if latest_note is None:
        if notes:
            summary = (
                f"{len(notes)} note(s) were returned but none could be dated, so note recency cannot be evaluated."
            )
            caveat = (
                "This is a data-quality limitation, not evidence of missing interaction. "
                "The notes exist; their timestamps could not be parsed at read time."
            )
        else:
            summary = "The Notes API returned no notes for this contact."
            caveat = (
                "Absence of API-visible notes does not prove no interaction occurred — "
                "it means the Notes endpoint returned nothing at read time."
            )
        findings.append(
            {
                "gap_type": "no_recent_interaction_note",
                "summary": summary,
                "evidence": {
                    "notes_checked": len(notes),
                    "notes_with_unusable_dates": undateable_notes,
                    "stale_note_days_threshold": stale_note_days,
                },
                "threshold_basis": STALE_NOTE_THRESHOLD_BASIS,
                "caveat": caveat,
                "advisory": STALE_NOTE_ADVISORY,
            }
        )
    else:
        # Fractional days: a truncating day count would silently let anything
        # under threshold+1 days pass, making the effective boundary a day
        # later than the stated threshold.
        age_days = (now - latest_note["_parsed_created"]).total_seconds() / 86400.0
        if age_days > stale_note_days:
            findings.append(
                {
                    "gap_type": "no_recent_interaction_note",
                    "summary": f"Most recent API-visible note is {age_days:.1f} day(s) old, "
                    f"beyond the {stale_note_days}-day advisory threshold.",
                    "evidence": {
                        "latest_note_id": latest_note.get("id"),
                        "latest_note_date": latest_note["_parsed_created"].isoformat(),
                        "latest_note_age_days": round(age_days, 2),
                        "stale_note_days_threshold": stale_note_days,
                        "notes_checked": len(notes),
                        "notes_with_unusable_dates": undateable_notes,
                    },
                    "threshold_basis": STALE_NOTE_THRESHOLD_BASIS,
                    "caveat": "Based only on notes visible via the Notes API at read time; "
                    "not proof no other interaction occurred.",
                    "advisory": STALE_NOTE_ADVISORY,
                }
            )

    if expected_assigned_user_id is not None:
        actual = person.get("assignedUserId")
        if actual is None:
            # An unassigned contact must not pass an ownership check silently:
            # "nobody owns this" is a stronger control gap than "the wrong
            # person owns this," not an absence of one.
            findings.append(
                {
                    "gap_type": "ownership_mismatch",
                    "summary": f"Contact has no assigned user; expected user {expected_assigned_user_id}.",
                    "evidence": {
                        "assignedUserId": None,
                        "expected_assigned_user_id": expected_assigned_user_id,
                    },
                }
            )
        elif int(actual) != int(expected_assigned_user_id):
            findings.append(
                {
                    "gap_type": "ownership_mismatch",
                    "summary": f"Contact is assigned to user {actual}, expected {expected_assigned_user_id}.",
                    "evidence": {
                        "assignedUserId": actual,
                        "expected_assigned_user_id": expected_assigned_user_id,
                    },
                }
            )

    return findings
