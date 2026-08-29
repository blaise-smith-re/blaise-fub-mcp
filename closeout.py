"""Pure helper logic for the safe interaction-closeout workflow.

Kept separate from server.py so duplicate/conflict detection and before/after
diffing can be unit tested without mocking HTTP or the MCP transport.
"""

from __future__ import annotations

from typing import Any

# Fields that legitimately change on their own (server-side touch timestamps,
# activity rollups) and must not be reported as "unintended" changes caused
# by a note/task write. Anything NOT in this set that differs before vs.
# after is flagged for human review.
PERSON_IGNORED_DIFF_FIELDS: frozenset[str] = frozenset(
    {
        "updated",
        "lastActivity",
        "lastCommunication",
        "touchedAt",
        "created",  # never expected to change, but excluded defensively
    }
)


def find_exact_duplicate_task(
    open_tasks: list[dict[str, Any]],
    *,
    name: str,
    task_type: str,
    due_date: str | None,
    due_date_time: str | None,
) -> dict[str, Any] | None:
    """Return the existing open task that is an exact match, if any."""
    target_name = name.strip().casefold()
    target_type = task_type.strip().casefold()
    target_due = due_date or due_date_time
    for task in open_tasks:
        if str(task.get("name") or "").strip().casefold() != target_name:
            continue
        if str(task.get("type") or "").strip().casefold() != target_type:
            continue
        existing_due = task.get("dueDate") or task.get("dueDateTime")
        if existing_due == target_due:
            return task
    return None


def find_duplicate_note(notes: list[dict[str, Any]], *, subject: str, body: str) -> dict[str, Any] | None:
    """Return an existing note with the exact same subject+body, if any."""
    target_subject = subject.strip().casefold()
    target_body = body.strip().casefold()
    for note in notes:
        if (
            str(note.get("subject") or "").strip().casefold() == target_subject
            and str(note.get("body") or "").strip().casefold() == target_body
        ):
            return note
    return None


def diff_person_snapshot(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    ignored_fields: frozenset[str] = PERSON_IGNORED_DIFF_FIELDS,
) -> dict[str, dict[str, Any]]:
    """Return the set of person fields that changed between two snapshots."""
    changed: dict[str, dict[str, Any]] = {}
    for key in set(before.keys()) | set(after.keys()):
        if key in ignored_fields:
            continue
        if before.get(key) != after.get(key):
            changed[key] = {"before": before.get(key), "after": after.get(key)}
    return changed


# Task names that carry no actual commitment content — just the channel or a
# generic gesture. Operating-style intent: every next action should read like
# a real commitment ("Call to confirm inspection date"), not a placeholder.
# This is a narrow, exact-match blocklist so it never rejects a legitimately
# short but specific task name.
_VAGUE_TASK_NAMES: frozenset[str] = frozenset(
    {
        "follow up",
        "followup",
        "follow-up",
        "touch base",
        "touch-base",
        "check in",
        "check-in",
        "checkin",
        "reach out",
        "reach-out",
        "call",
        "text",
        "email",
        "contact",
        "connect",
    }
)


def is_vague_task_name(name: str) -> bool:
    """True if a task name is a bare placeholder with no commitment content."""
    normalized = " ".join(name.strip().casefold().split())
    return normalized in _VAGUE_TASK_NAMES


def summarize_recent_notes(notes: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    """Small, review-friendly summary of the most recent notes for relationship context.

    Used only to surface context to the human/caller before a write; never
    written back to FUB.
    """

    def _sort_key(note: dict[str, Any]) -> str:
        return str(note.get("created") or note.get("updated") or note.get("date") or "")

    ordered = sorted(notes, key=_sort_key, reverse=True)
    return [{"id": n.get("id"), "subject": n.get("subject"), "date": _sort_key(n)} for n in ordered[:limit]]


def find_unexpected_task_changes(
    before_tasks: list[dict[str, Any]],
    after_tasks: list[dict[str, Any]],
    *,
    allowed_new_task_ids: frozenset[Any] = frozenset(),
) -> list[dict[str, Any]]:
    """Confirm no pre-existing open task was altered or disappeared unexpectedly.

    A task id present before is expected to still be present, unchanged,
    after. Any new task id that isn't in `allowed_new_task_ids` is also
    flagged, since the closeout workflow should create at most one task.
    """
    before_by_id = {t.get("id"): t for t in before_tasks if t.get("id") is not None}
    after_by_id = {t.get("id"): t for t in after_tasks if t.get("id") is not None}
    problems: list[dict[str, Any]] = []

    for task_id, before_task in before_by_id.items():
        after_task = after_by_id.get(task_id)
        if after_task is None:
            problems.append({"taskId": task_id, "problem": "disappeared", "before": before_task})
            continue
        relevant_keys = {"name", "type", "dueDate", "dueDateTime", "isCompleted", "assignedUserId"}
        diff = {
            k: {"before": before_task.get(k), "after": after_task.get(k)}
            for k in relevant_keys
            if before_task.get(k) != after_task.get(k)
        }
        if diff:
            problems.append({"taskId": task_id, "problem": "changed", "diff": diff})

    for task_id in after_by_id:
        if task_id not in before_by_id and task_id not in allowed_new_task_ids:
            problems.append({"taskId": task_id, "problem": "unexpected_new_task", "task": after_by_id[task_id]})

    return problems
