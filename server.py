from __future__ import annotations

import os
import re
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

from auth0_verifier import Auth0TokenVerifier
from closeout import (
    diff_person_snapshot,
    find_duplicate_note,
    find_exact_duplicate_task,
    find_unexpected_task_changes,
    is_vague_task_name,
    summarize_recent_notes,
)
from daily_control import find_gaps
from fub_client import FUBClient
from redaction import assert_no_sensitive_data, redact_for_log
from task_dates import filter_tasks_by_due_date, parse_calendar_date, resolve_timezone


def _public_base() -> str:
    value = os.getenv("MCP_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not value:
        raise RuntimeError("Set MCP_PUBLIC_URL or deploy on Render.")
    return value.rstrip("/")


PUBLIC_BASE = _public_base()
AUTH0_DOMAIN = os.environ["AUTH0_DOMAIN"].strip().rstrip("/")
if not AUTH0_DOMAIN.startswith("http"):
    AUTH0_DOMAIN = f"https://{AUTH0_DOMAIN}"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "10000"))

mcp = FastMCP(
    "Blaise FUB Full Operator",
    host=HOST,
    port=PORT,
    stateless_http=True,
    json_response=True,
    instructions=(
        "Operate Blaise Smith's Follow Up Boss account using exact-record targeting and source control. "
        "Read before write. Never expose credentials. Never infer that missing API activity did not occur. "
        "Use execute=False for previews when appropriate. Only execute a write when Blaise has authorized "
        "the action or the current controlling workflow clearly authorizes it. Never create/edit shared "
        "FUB stages, Smart Lists, action plans, automations, lead-flow rules, templates, or other team-owned "
        "structures without the required team approval. Text/call logging tools only RECORD external activity; "
        "they do not actually send a text or place a call."
    ),
    token_verifier=Auth0TokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(f"{AUTH0_DOMAIN}/"),
        resource_server_url=AnyHttpUrl(f"{PUBLIC_BASE}/mcp"),
        required_scopes=["fub:read", "fub:write"],
    ),
)


def _client() -> FUBClient:
    return FUBClient()


def _require_write_scope() -> None:
    token = get_access_token()
    if token is None or "fub:write" not in token.scopes:
        raise PermissionError("This action requires the fub:write OAuth scope.")


def _person_name(person: dict[str, Any]) -> str:
    if person.get("name"):
        return str(person["name"])
    return " ".join(p for p in [person.get("firstName"), person.get("lastName")] if p).strip()


def _assert_person(person: dict[str, Any], person_id: int, expected_name: str) -> None:
    actual_id = person.get("id")
    if actual_id is None or int(actual_id) != person_id:
        raise ValueError("Exact person ID check failed.")
    actual = _person_name(person)
    if actual.casefold().strip() != expected_name.casefold().strip():
        raise ValueError(f"Exact contact-name check failed: record is '{actual}', not '{expected_name}'.")


def _assert_task(task: dict[str, Any], task_id: int, person_id: int, expected_name: str) -> None:
    actual_task_id = task.get("id")
    if actual_task_id is None or int(actual_task_id) != task_id:
        raise ValueError("Exact task ID check failed.")
    actual_person_id = task.get("personId")
    if actual_person_id is None or int(actual_person_id) != person_id:
        raise ValueError("Task belongs to a different contact.")
    current_name = str(task.get("name") or "")
    if current_name.casefold().strip() != expected_name.casefold().strip():
        raise ValueError(f"Stale task check failed: current task name is '{current_name}'.")


def _validate_tz(value: str | None, label: str = "date-time") -> None:
    if value and not (value.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", value)):
        raise ValueError(f"{label} must include an explicit timezone offset or Z.")


def _normalized_values(items: list[dict[str, Any]] | None) -> list[str]:
    return sorted(str(item.get("value", "")).strip().casefold() for item in (items or []) if item.get("value"))


def _list_items(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Unwrap a FUB list response defensively (primary key, then generic 'data')."""
    return list(response.get(key) or response.get("data") or [])


def _truncation_note(response: dict[str, Any], items: list[dict[str, Any]], label: str) -> str | None:
    """Disclose when a list response was capped, so silence isn't read as completeness.

    A duplicate check that only saw part of the record is a weaker guarantee
    than one that saw all of it, and the caller is entitled to know which of
    the two it got.
    """
    total = (response.get("_metadata") or {}).get("total")
    if isinstance(total, int) and total > len(items):
        return (
            f"Only the {len(items)} most recent of {total} {label} were read; "
            "duplicate detection covered that window only."
        )
    return None


async def _get_all_open_tasks(client: FUBClient, person_id: int) -> list[dict[str, Any]]:
    """The complete set of one contact's open tasks — never a possibly-truncated page.

    Single call site for the pattern every duplicate-check and audit path in
    this file needs. Per-contact open-task counts are always small in
    practice, so full pagination here is cheap; the alternative (a single
    unpaginated page) is exactly the production defect verified in FUB 06
    v1.6 — up to 21 of 22 open tasks silently returned as if it were all of
    them, with no pagination parameter to catch it.
    """
    tasks, _completeness = await client.search_tasks_all(personId=person_id, isCompleted=False)
    return tasks


def _page_completeness(
    response: dict[str, Any], items: list[dict[str, Any]], *, limit: int, offset: int
) -> dict[str, Any]:
    """Completeness metadata for a single (non-paginated) page of results."""
    total = (response.get("_metadata") or {}).get("total")
    has_more = isinstance(total, int) and (offset + len(items)) < total
    return {
        "returned_count": len(items),
        "total_count": total if isinstance(total, int) else None,
        "has_more": bool(has_more),
        "capped": False,
        "pages_fetched": 1,
        "next_offset": (offset + limit) if has_more else None,
    }


def _write_outcome(write_result: dict[str, Any]) -> dict[str, Any]:
    """Summarize what a write actually did, without overstating it.

    Distinguishes an object this call created (even when its read-back later
    failed — the caller still needs that id to reconcile by hand) from a
    pre-existing object an idempotent retry matched and deliberately did not
    rewrite. Collapsing those two into one "created" id would misreport a
    no-op as a write.
    """
    status = write_result.get("status")
    created_id = None
    for key in ("verified", "created"):
        section = write_result.get(key)
        if isinstance(section, dict) and section.get("id") is not None:
            created_id = section["id"]
            break
    matched_id = None
    for key in ("existing_note", "existing_task"):
        section = write_result.get(key)
        if isinstance(section, dict) and section.get("id") is not None:
            matched_id = section["id"]
            break

    if status == "NOT_REQUESTED":
        outcome = "not_requested"
    elif status == "SKIPPED_EXACT_DUPLICATE_EXISTS":
        outcome = "matched_existing_no_write"
    elif created_id is not None:
        outcome = "created"
    else:
        outcome = "not_written"

    return {
        "id": created_id,
        "verified": status == "WRITE_COMPLETED_AND_RE_READ",
        "outcome": outcome,
        "matched_existing_id": matched_id,
    }


def _require_meaningful_text(value: str, field_label: str) -> None:
    """Reject empty/whitespace-only content for a field that must carry meaning.

    Without this an empty note or task name writes successfully and every
    downstream check passes ("" == ""), producing a fully verified report for
    a record that documents nothing.
    """
    if not value or not value.strip():
        raise ValueError(f"{field_label} cannot be empty or whitespace only.")


def _task_summaries(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "type": t.get("type"),
            "due": t.get("dueDate") or t.get("dueDateTime"),
        }
        for t in tasks
    ]


ALLOWED_TASK_TYPES = {
    "Follow Up",
    "Call",
    "Text",
    "Email",
    "Appointment",
    "Showing",
    "Closing",
    "Open House",
    "Thank You",
}


async def _write_note_with_verification(
    client: FUBClient, person_id: int, subject: str, body: str, existing_notes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create a note, then independently re-read it to confirm the write.

    There is no confirmed single-item GET /notes/{id} endpoint reachable from
    this environment (see docs/CONNECTOR_AUDIT.md), so read-back is done by
    re-listing the contact's notes and matching on the id the create call
    returned. If that match fails or the content differs, the write is
    reported as unverified/mismatched rather than as a confirmed success.
    """
    duplicate = find_duplicate_note(existing_notes, subject=subject, body=body)
    if duplicate is not None:
        return {"status": "SKIPPED_EXACT_DUPLICATE_EXISTS", "existing_note": duplicate}

    created = await client.create_note(person_id, subject, body)

    note_id = created.get("id")
    if note_id is None:
        return {
            "status": "WRITE_COMPLETED_UNVERIFIED",
            "created": created,
            "hold": "Create response had no id; independent read-back was not possible.",
        }
    try:
        after_notes = _list_items(await client.get_notes(person_id, limit=50), "notes")
    except Exception as exc:  # noqa: BLE001 - the write already happened; report, don't crash
        return {
            "status": "WRITE_COMPLETED_UNVERIFIED",
            "created": created,
            "hold": f"Note was created (id={note_id}) but independent read-back failed: {redact_for_log(str(exc))}",
        }
    verified = next((n for n in after_notes if str(n.get("id")) == str(note_id)), None)
    if verified is None:
        return {
            "status": "WRITE_COMPLETED_UNVERIFIED",
            "created": created,
            "hold": "Independent read-back could not find the created note by id.",
        }
    if str(verified.get("subject") or "") != subject or str(verified.get("body") or "") != body:
        return {
            "status": "WRITE_COMPLETED_CONTENT_MISMATCH",
            "created": created,
            "verified": verified,
            "hold": "Read-back content does not match what was requested.",
        }
    return {"status": "WRITE_COMPLETED_AND_RE_READ", "created": created, "verified": verified}


async def _write_task_with_dedup_and_verification(
    client: FUBClient, payload: dict[str, Any], open_tasks: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create a task unless an exact duplicate is already open; always read back."""
    duplicate = find_exact_duplicate_task(
        open_tasks,
        name=str(payload["name"]),
        task_type=str(payload["type"]),
        due_date=payload.get("dueDate"),
        due_date_time=payload.get("dueDateTime"),
    )
    if duplicate is not None:
        return {"status": "SKIPPED_EXACT_DUPLICATE_EXISTS", "existing_task": duplicate}

    created = await client.create_task(payload)
    task_id = created.get("id")
    if task_id is None:
        return {
            "status": "WRITE_COMPLETED_UNVERIFIED",
            "created": created,
            "hold": "Create response had no id; independent read-back was not possible.",
        }
    try:
        verified = await client.get_task(int(task_id))
    except Exception as exc:  # noqa: BLE001 - the write already happened; report, don't crash
        return {
            "status": "WRITE_COMPLETED_UNVERIFIED",
            "created": created,
            "hold": f"Task was created (id={task_id}) but independent read-back failed: {redact_for_log(str(exc))}",
        }
    mismatches = {
        field: {"requested": payload[field], "verified": verified.get(field)}
        for field in ("name", "type", "dueDate", "dueDateTime")
        if field in payload and str(verified.get(field) or "") != str(payload.get(field) or "")
    }
    if mismatches:
        return {
            "status": "WRITE_COMPLETED_CONTENT_MISMATCH",
            "created": created,
            "verified": verified,
            "hold": f"Read-back content does not match what was requested: {sorted(mismatches.keys())}.",
        }
    return {"status": "WRITE_COMPLETED_AND_RE_READ", "created": created, "verified": verified}


# ==================== READ TOOLS ====================


@mcp.tool()
async def find_contact(
    email: str | None = None,
    phone: str | None = None,
    name: str | None = None,
    stage: str | None = None,
    assigned_user_id: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search contacts. Read-only."""
    return await _client().find_people(
        email=email,
        phone=phone,
        name=name,
        stage=stage,
        assignedUserId=assigned_user_id,
        limit=limit,
    )


@mcp.tool()
async def get_contact(person_id: int) -> dict[str, Any]:
    """Retrieve one contact by exact ID. Read-only."""
    return await _client().get_person(person_id)


@mcp.tool()
async def get_contact_events(person_id: int, limit: int = 50, next_token: str | None = None) -> dict[str, Any]:
    return await _client().get_events(person_id, limit=limit, next_token=next_token)


@mcp.tool()
async def get_contact_notes(person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return await _client().get_notes(person_id, limit=limit, offset=offset)


@mcp.tool()
async def get_contact_calls(person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return await _client().get_calls(person_id, limit=limit, offset=offset)


@mcp.tool()
async def get_contact_text_messages(person_id: int) -> dict[str, Any]:
    return await _client().get_text_messages(person_id)


@mcp.tool()
async def search_tasks(
    person_id: int | None = None,
    assigned_user_id: int | None = None,
    task_type: str | None = None,
    is_completed: bool | None = None,
    due: str | None = None,
    due_on: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    due_timezone: str = "America/Chicago",
    limit: int = 100,
    offset: int = 0,
    fetch_all: bool = False,
) -> dict[str, Any]:
    """Search tasks. Read-only.

    For anything date-sensitive, use due_on (exact calendar date) and/or
    due_from/due_to (inclusive bounded range, YYYY-MM-DD) instead of the
    legacy `due` keyword. FUB's own `due=<keyword>` server-side filtering is
    independently verified unreliable (FUB 06 v1.6, Aug 30 2026: due=today
    missed a real due-today task; due=tomorrow and specific-date inputs
    could be silently ignored). `due` is still accepted and passed through
    for backward compatibility, but a response built from it carries a
    caveat rather than being trusted silently.

    due_on/due_from/due_to are evaluated client-side, deterministically,
    against each task's raw due date in due_timezone (default
    America/Chicago) — by calendar date, not by converting to a UTC instant,
    so results are correct across a timezone's day boundary. Unsupported
    date syntax (anything other than exact YYYY-MM-DD) raises a clear error
    immediately rather than being silently ignored. Using any of these three
    always retrieves the complete matching set first (see fetch_all below),
    since a date filter applied to a partial page could silently miss a
    match sitting on a later page.

    Pagination: set fetch_all=True to retrieve the complete matching set
    (paged, bounded, and disclosed) instead of one page of up to `limit`
    starting at `offset`. Every response includes a `_completeness` block
    (returned_count, total_count when FUB discloses it, has_more, capped,
    pages_fetched) so a caller can never mistake a partial page for the
    full result — this was the verified production gap (FUB 06 v1.6): no
    pagination parameter existed and up to 21 of 22 open tasks were
    silently returned as if that were the complete set.
    """
    tz = resolve_timezone(due_timezone)
    # `is not None`, not truthiness: an empty string is still "the caller
    # supplied a value" and must be validated, not silently treated the same
    # as "no filter requested" — that would reproduce the exact class of
    # silent-ignore defect this parameter set exists to close.
    due_on_date = parse_calendar_date(due_on, field_label="due_on") if due_on is not None else None
    due_from_date = parse_calendar_date(due_from, field_label="due_from") if due_from is not None else None
    due_to_date = parse_calendar_date(due_to, field_label="due_to") if due_to is not None else None
    if due_from_date is not None and due_to_date is not None and due_from_date > due_to_date:
        raise ValueError(f"due_from {due_from!r} is after due_to {due_to!r}.")
    wants_date_filter = due_on_date is not None or due_from_date is not None or due_to_date is not None

    client = _client()
    base_params: dict[str, Any] = {
        "personId": person_id,
        "assignedUserId": assigned_user_id,
        "type": task_type,
        "isCompleted": is_completed,
        "due": due,
    }

    # A date filter must never be evaluated against a possibly-partial page —
    # that would silently miss matches sitting on an unfetched page, which is
    # the same class of defect this tool exists to close. Force complete
    # retrieval whenever one is requested, regardless of fetch_all.
    if fetch_all or wants_date_filter:
        tasks, completeness = await client.search_tasks_all(**base_params)
    else:
        response = await client.search_tasks(**base_params, limit=limit, offset=offset)
        tasks = _list_items(response, "tasks")
        completeness = _page_completeness(response, tasks, limit=limit, offset=offset)

    unusable_due = 0
    if wants_date_filter:
        tasks, unusable_due = filter_tasks_by_due_date(
            tasks, due_on=due_on_date, due_from=due_from_date, due_to=due_to_date, tz=tz
        )

    result: dict[str, Any] = {"tasks": tasks, "_completeness": completeness}
    if due is not None:
        result["due_keyword_caveat"] = (
            "The legacy `due` keyword was passed through to Follow Up Boss as-is; its "
            "server-side filtering is independently verified unreliable (FUB 06 v1.6). "
            "Prefer due_on/due_from/due_to for anything date-sensitive."
        )
    if wants_date_filter:
        result["due_date_filter"] = {
            "due_on": due_on_date.isoformat() if due_on_date else None,
            "due_from": due_from_date.isoformat() if due_from_date else None,
            "due_to": due_to_date.isoformat() if due_to_date else None,
            "timezone": due_timezone,
            "excluded_no_usable_due_date": unusable_due,
        }
    return result


@mcp.tool()
async def get_open_tasks(person_id: int) -> dict[str, Any]:
    """All open (incomplete) tasks for one contact. Always retrieves the complete set.

    Unlike a single unpaginated page (the verified production defect in
    FUB 06 v1.6, where up to 21 of 22 open tasks were silently returned as
    if it were the whole set), this pages through the full result and
    reports `_completeness` so a caller can never mistake a partial result
    for a complete one.
    """
    tasks, completeness = await _client().search_tasks_all(personId=person_id, isCompleted=False)
    return {
        "tasks": tasks,
        "_metadata": {"total": completeness["total_count"]},
        "_completeness": completeness,
    }


@mcp.tool()
async def get_task(task_id: int) -> dict[str, Any]:
    return await _client().get_task(task_id)


@mcp.tool()
async def get_contact_appointments(person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return await _client().search_appointments(personId=person_id, limit=min(max(limit, 1), 100), offset=max(offset, 0))


@mcp.tool()
async def get_appointment(appointment_id: int) -> dict[str, Any]:
    return await _client().get_appointment(appointment_id)


@mcp.tool()
async def get_active_deals(person_id: int) -> dict[str, Any]:
    return await _client().search_deals(personId=person_id, status="Active")


@mcp.tool()
async def search_deals(
    person_id: int | None = None, user_id: int | None = None, status: str | None = None
) -> dict[str, Any]:
    return await _client().search_deals(personId=person_id, userId=user_id, status=status)


@mcp.tool()
async def get_deal(deal_id: int) -> dict[str, Any]:
    return await _client().get_deal(deal_id)


@mcp.tool()
async def get_stages() -> dict[str, Any]:
    return await _client().get_stages()


@mcp.tool()
async def get_users() -> dict[str, Any]:
    return await _client().get_users()


@mcp.tool()
async def get_user(user_id: int) -> dict[str, Any]:
    return await _client().get_user(user_id)


@mcp.tool()
async def get_timeframes() -> dict[str, Any]:
    return await _client().get_timeframes()


@mcp.tool()
async def get_custom_fields() -> dict[str, Any]:
    return await _client().get_custom_fields()


@mcp.tool()
async def get_deal_custom_fields() -> dict[str, Any]:
    return await _client().get_deal_custom_fields()


@mcp.tool()
async def get_pipelines() -> dict[str, Any]:
    return await _client().get_pipelines()


@mcp.tool()
async def get_appointment_types() -> dict[str, Any]:
    return await _client().get_appointment_types()


@mcp.tool()
async def get_appointment_outcomes() -> dict[str, Any]:
    return await _client().get_appointment_outcomes()


# ==================== WRITE TOOLS ====================


@mcp.tool()
async def create_contact_note(
    person_id: int,
    expected_contact_name: str,
    subject: str,
    body: str,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/create a plain-text note on an exact contact.

    Rejects notes containing apparent secrets (passwords, SSNs, account/wire
    details, TrustFunds secret words). Skips the write if an exact-duplicate
    note already exists (idempotent retry safe). Every live write is
    independently re-read via GET /notes to confirm it before being reported
    as completed.
    """
    assert_no_sensitive_data(subject, body, field_label="note")
    _require_meaningful_text(subject, "Note subject")
    _require_meaningful_text(body, "Note body")
    client = _client()
    person = await client.get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    notes_response = await client.get_notes(person_id, limit=50)
    existing_notes = _list_items(notes_response, "notes")
    dedup_scope_note = _truncation_note(notes_response, existing_notes, "notes")
    preview = {"personId": person_id, "name": _person_name(person), "subject": subject, "body": body}

    duplicate = find_duplicate_note(existing_notes, subject=subject, body=body)
    scope: dict[str, Any] = {"dedup_scope_limitation": dedup_scope_note} if dedup_scope_note else {}
    if duplicate is not None:
        return {
            "status": "SKIPPED_EXACT_DUPLICATE_EXISTS",
            "preview": preview,
            "existing_note": duplicate,
            **scope,
        }
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "preview": preview, **scope}
    _require_write_scope()
    result = await _write_note_with_verification(client, person_id, subject, body, existing_notes)
    return {**result, "preview": preview, **scope}


@mcp.tool()
async def create_contact_task(
    person_id: int,
    expected_contact_name: str,
    assigned_user_id: int,
    name: str,
    task_type: str,
    due_date: str | None = None,
    due_date_time: str | None = None,
    remind_seconds_before: int | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/create one task. Exactly one due_date or due_date_time is required.

    Skips the write if an exact-duplicate open task (same name, type, and due
    date) already exists on this contact (idempotent retry safe). Rejects a
    bare placeholder name (e.g. just "Follow Up" or "Call") in favor of a
    task that names the actual next commitment.
    """
    assert_no_sensitive_data(name, field_label="task name")
    if is_vague_task_name(name):
        raise ValueError(
            f"Task name {name!r} is a bare placeholder, not a next commitment. "
            "Name the actual next step, e.g. 'Call to confirm inspection date' "
            "instead of 'Call' or 'Follow Up'."
        )
    if task_type not in ALLOWED_TASK_TYPES:
        raise ValueError(f"Unsupported task type: {task_type}")
    if bool(due_date) == bool(due_date_time):
        raise ValueError("Provide exactly one of due_date or due_date_time.")
    _validate_tz(due_date_time, "due_date_time")
    client = _client()
    person = await client.get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    await client.get_user(assigned_user_id)
    payload: dict[str, Any] = {
        "personId": person_id,
        "assignedUserId": assigned_user_id,
        "name": name,
        "type": task_type,
        "isCompleted": False,
    }
    if due_date:
        payload["dueDate"] = due_date
    if due_date_time:
        payload["dueDateTime"] = due_date_time
    if remind_seconds_before is not None:
        payload["remindSecondsBefore"] = remind_seconds_before

    open_tasks = await _get_all_open_tasks(client, person_id)
    duplicate = find_exact_duplicate_task(
        open_tasks, name=name, task_type=task_type, due_date=due_date, due_date_time=due_date_time
    )
    if duplicate is not None:
        return {"status": "SKIPPED_EXACT_DUPLICATE_EXISTS", "preview": payload, "existing_task": duplicate}
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "preview": payload}
    _require_write_scope()
    result = await _write_task_with_dedup_and_verification(client, payload, open_tasks)
    return {**result, "preview": payload}


@mcp.tool()
async def update_contact_task(
    task_id: int,
    expected_person_id: int,
    expected_task_name: str,
    new_name: str | None = None,
    new_task_type: str | None = None,
    new_due_date: str | None = None,
    new_due_date_time: str | None = None,
    mark_completed: bool | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/update one exact task. No reassignment or deletion."""
    assert_no_sensitive_data(new_name, field_label="task name")
    task = await _client().get_task(task_id)
    _assert_task(task, task_id, expected_person_id, expected_task_name)
    if new_due_date and new_due_date_time:
        raise ValueError("Use only one due date field.")
    _validate_tz(new_due_date_time, "new_due_date_time")
    payload: dict[str, Any] = {}
    if new_name is not None:
        payload["name"] = new_name
    if new_task_type is not None:
        payload["type"] = new_task_type
    if new_due_date is not None:
        payload["dueDate"] = new_due_date
    if new_due_date_time is not None:
        payload["dueDateTime"] = new_due_date_time
    if mark_completed is not None:
        payload["isCompleted"] = mark_completed
    if not payload:
        raise ValueError("No task changes supplied.")
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "before": task, "proposed": payload}
    _require_write_scope()
    updated = await _client().update_task(task_id, payload)
    verified = await _client().get_task(task_id)
    return {"status": "WRITE_COMPLETED_AND_RE_READ", "before": task, "updated": updated, "after": verified}


@mcp.tool()
async def update_contact_profile(
    person_id: int,
    expected_contact_name: str,
    new_first_name: str | None = None,
    new_last_name: str | None = None,
    existing_stage_name: str | None = None,
    price: int | None = None,
    timeframe_id: int | None = None,
    assigned_user_id: int | None = None,
    assigned_lender_id: int | None = None,
    assigned_lender_name: str | None = None,
    background: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/update selected contact fields. Moves only to an existing stage; never edits stage definitions."""
    assert_no_sensitive_data(new_first_name, new_last_name, background, field_label="contact profile")
    before = await _client().get_person(person_id)
    _assert_person(before, person_id, expected_contact_name)
    payload: dict[str, Any] = {}
    if new_first_name is not None:
        payload["firstName"] = new_first_name
    if new_last_name is not None:
        payload["lastName"] = new_last_name
    if existing_stage_name is not None:
        stages = await _client().get_stages()
        names = {str(x.get("name")) for x in (stages.get("stages") or stages.get("data") or []) if x.get("name")}
        if existing_stage_name not in names:
            raise ValueError("Stage must already exist in FUB. Shared stage creation is not exposed.")
        payload["stage"] = existing_stage_name
    if price is not None:
        payload["price"] = price
    if timeframe_id is not None:
        await _client().get_timeframes()
        payload["timeframeId"] = timeframe_id
    if assigned_user_id is not None:
        await _client().get_user(assigned_user_id)
        payload["assignedUserId"] = assigned_user_id
    if assigned_lender_id is not None:
        await _client().get_user(assigned_lender_id)
        payload["assignedLenderId"] = assigned_lender_id
    if assigned_lender_name is not None:
        payload["assignedLenderName"] = assigned_lender_name
    if background is not None:
        payload["background"] = background
    if custom_fields:
        definitions = await _client().get_custom_fields()
        valid = {
            str(x.get("name"))
            for x in (definitions.get("customFields") or definitions.get("data") or [])
            if x.get("name")
        }
        invalid = [k for k in custom_fields if k not in valid or not k.startswith("custom")]
        if invalid:
            raise ValueError(f"Unknown/unapproved custom field name(s): {invalid}")
        payload.update(custom_fields)
    if not payload:
        raise ValueError("No contact changes supplied.")
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "before": before, "proposed": payload}
    _require_write_scope()
    await _client().update_person(person_id, payload)
    after = await _client().get_person(person_id)
    return {"status": "WRITE_COMPLETED_AND_RE_READ", "before": before, "after": after}


@mcp.tool()
async def replace_contact_channels(
    person_id: int,
    expected_contact_name: str,
    expected_current_emails: list[str] | None = None,
    expected_current_phones: list[str] | None = None,
    new_emails: list[dict[str, str]] | None = None,
    new_phones: list[dict[str, str]] | None = None,
    confirm_full_replacement: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    """Replace the full email and/or phone list only after stale-state verification.

    FUB overwrites these lists, so expected_current_* and confirm_full_replacement are mandatory
    for whichever channel is being changed.
    """
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    payload: dict[str, Any] = {}
    if new_emails is not None:
        if expected_current_emails is None or not confirm_full_replacement:
            raise ValueError("Email replacement requires expected_current_emails and confirm_full_replacement=True.")
        actual = _normalized_values(person.get("emails"))
        expected = sorted(x.strip().casefold() for x in expected_current_emails)
        if actual != expected:
            raise ValueError(f"Email stale-state check failed. Current={actual}")
        payload["emails"] = new_emails
    if new_phones is not None:
        if expected_current_phones is None or not confirm_full_replacement:
            raise ValueError("Phone replacement requires expected_current_phones and confirm_full_replacement=True.")
        actual = _normalized_values(person.get("phones"))
        expected = sorted(x.strip().casefold() for x in expected_current_phones)
        if actual != expected:
            raise ValueError(f"Phone stale-state check failed. Current={actual}")
        payload["phones"] = new_phones
    if not payload:
        raise ValueError("No channel replacements supplied.")
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "before": person, "proposed": payload}
    _require_write_scope()
    await _client().update_person(person_id, payload)
    after = await _client().get_person(person_id)
    return {"status": "WRITE_COMPLETED_AND_RE_READ", "after": after}


@mcp.tool()
async def merge_contact_tags(
    person_id: int,
    expected_contact_name: str,
    tags_to_add: list[str],
    brent_approval_confirmed: bool,
    execute: bool = False,
) -> dict[str, Any]:
    """Merge tags without deleting existing tags.

    Team approval is required because shared FUB tag governance is team-controlled.
    """
    if not brent_approval_confirmed:
        raise PermissionError("Team approval is required before changing shared FUB tag usage.")
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "currentTags": person.get("tags"), "tagsToAdd": tags_to_add}
    _require_write_scope()
    await _client().update_person(person_id, {"tags": tags_to_add}, merge_tags=True)
    after = await _client().get_person(person_id)
    return {"status": "WRITE_COMPLETED_AND_RE_READ", "after": after}


@mcp.tool()
async def create_contact_appointment(
    person_id: int,
    expected_contact_name: str,
    assigned_user_id: int,
    title: str,
    start: str,
    end: str,
    location: str | None = None,
    description: str | None = None,
    type_id: int | None = None,
    send_invitation: bool = False,
    explicit_send_authorization: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/create an FUB appointment. Invitation sending requires explicit authorization."""
    assert_no_sensitive_data(title, location, description, field_label="appointment")
    _validate_tz(start, "start")
    _validate_tz(end, "end")
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    user = await _client().get_user(assigned_user_id)
    if send_invitation and not explicit_send_authorization:
        raise PermissionError("Sending an appointment invitation requires explicit authorization.")
    invitees = [
        {"userId": assigned_user_id, "name": str(user.get("name") or "")},
        {
            "personId": person_id,
            "name": _person_name(person),
            "email": ((person.get("emails") or [{}])[0].get("value")),
        },
    ]
    payload: dict[str, Any] = {"title": title, "invitees": invitees, "allDay": False, "start": start, "end": end}
    if location is not None:
        payload["location"] = location
    if description is not None:
        payload["description"] = description
    if type_id is not None:
        payload["typeId"] = type_id
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "payload": payload, "sendInvitation": send_invitation}
    _require_write_scope()
    created = await _client().create_appointment(payload, send_invitation=send_invitation)
    if created.get("id"):
        verified = await _client().get_appointment(int(created["id"]))
        return {"status": "WRITE_COMPLETED_AND_RE_READ", "created": created, "verified": verified}
    return {"status": "WRITE_COMPLETED", "created": created}


@mcp.tool()
async def update_contact_appointment(
    appointment_id: int,
    expected_person_id: int,
    expected_title: str,
    new_title: str | None = None,
    new_start: str | None = None,
    new_end: str | None = None,
    new_location: str | None = None,
    new_description: str | None = None,
    new_type_id: int | None = None,
    new_outcome_id: int | None = None,
    send_invitation: bool = False,
    explicit_send_authorization: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/update one appointment using a fresh read of the current record."""
    assert_no_sensitive_data(new_title, new_location, new_description, field_label="appointment")
    current = await _client().get_appointment(appointment_id)
    if str(current.get("title") or "").casefold().strip() != expected_title.casefold().strip():
        raise ValueError("Stale appointment title check failed.")
    invitees = current.get("invitees") or []
    person_ids = {int(x["personId"]) for x in invitees if x.get("personId") is not None}
    if expected_person_id not in person_ids:
        raise ValueError("Appointment is not linked to the expected contact.")
    if send_invitation and not explicit_send_authorization:
        raise PermissionError("Sending an appointment invitation requires explicit authorization.")
    start = new_start or current.get("start")
    end = new_end or current.get("end")
    _validate_tz(start, "start")
    _validate_tz(end, "end")
    payload = {
        "title": new_title or current.get("title"),
        "invitees": invitees,
        "allDay": bool(current.get("allDay", False)),
        "start": start,
        "end": end,
    }
    for k, v in {
        "location": new_location if new_location is not None else current.get("location"),
        "description": new_description if new_description is not None else current.get("description"),
        "typeId": new_type_id if new_type_id is not None else current.get("typeId"),
        "outcomeId": new_outcome_id if new_outcome_id is not None else current.get("outcomeId"),
    }.items():
        if v is not None:
            payload[k] = v
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "before": current, "proposed": payload}
    _require_write_scope()
    await _client().update_appointment(appointment_id, payload, send_invitation=send_invitation)
    after = await _client().get_appointment(appointment_id)
    return {"status": "WRITE_COMPLETED_AND_RE_READ", "before": current, "after": after}


@mcp.tool()
async def create_contact_deal(
    person_id: int,
    expected_contact_name: str,
    user_ids: list[int],
    deal_name: str,
    stage_id: int,
    description: str | None = None,
    price: int | None = None,
    projected_close_date: str | None = None,
    mutual_acceptance_date: str | None = None,
    earnest_money_due_date: str | None = None,
    due_diligence_date: str | None = None,
    final_walk_through_date: str | None = None,
    possession_date: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/create a deal for an exact contact. No empty userIds allowed."""
    assert_no_sensitive_data(deal_name, description, field_label="deal")
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    if not user_ids:
        raise ValueError("At least one FUB user ID is required so the deal remains visible.")
    for uid in user_ids:
        await _client().get_user(uid)
    payload: dict[str, Any] = {"name": deal_name, "stageId": stage_id, "peopleIds": [person_id], "userIds": user_ids}
    for k, v in {
        "description": description,
        "price": price,
        "projectedCloseDate": projected_close_date,
        "mutualAcceptanceDate": mutual_acceptance_date,
        "earnestMoneyDueDate": earnest_money_due_date,
        "dueDiligenceDate": due_diligence_date,
        "finalWalkThroughDate": final_walk_through_date,
        "possessionDate": possession_date,
    }.items():
        if v is not None:
            payload[k] = v
    if custom_fields:
        defs = await _client().get_deal_custom_fields()
        valid = {str(x.get("name")) for x in (defs.get("dealCustomFields") or defs.get("data") or []) if x.get("name")}
        bad = [k for k in custom_fields if k not in valid]
        if bad:
            raise ValueError(f"Unknown deal custom field(s): {bad}")
        payload.update(custom_fields)
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "payload": payload}
    _require_write_scope()
    created = await _client().create_deal(payload)
    if created.get("id"):
        verified = await _client().get_deal(int(created["id"]))
        return {"status": "WRITE_COMPLETED_AND_RE_READ", "created": created, "verified": verified}
    return {"status": "WRITE_COMPLETED", "created": created}


@mcp.tool()
async def update_contact_deal(
    deal_id: int,
    expected_deal_name: str,
    expected_person_id: int,
    new_name: str | None = None,
    stage_id: int | None = None,
    description: str | None = None,
    price: int | None = None,
    projected_close_date: str | None = None,
    mutual_acceptance_date: str | None = None,
    earnest_money_due_date: str | None = None,
    due_diligence_date: str | None = None,
    final_walk_through_date: str | None = None,
    possession_date: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/update one exact deal. No delete/archive tool is exposed."""
    assert_no_sensitive_data(new_name, description, field_label="deal")
    before = await _client().get_deal(deal_id)
    if str(before.get("name") or "").casefold().strip() != expected_deal_name.casefold().strip():
        raise ValueError("Stale deal-name check failed.")
    if expected_person_id not in {int(x) for x in (before.get("peopleIds") or [])}:
        raise ValueError("Deal is not linked to the expected contact.")
    payload: dict[str, Any] = {}
    for k, v in {
        "name": new_name,
        "stageId": stage_id,
        "description": description,
        "price": price,
        "projectedCloseDate": projected_close_date,
        "mutualAcceptanceDate": mutual_acceptance_date,
        "earnestMoneyDueDate": earnest_money_due_date,
        "dueDiligenceDate": due_diligence_date,
        "finalWalkThroughDate": final_walk_through_date,
        "possessionDate": possession_date,
    }.items():
        if v is not None:
            payload[k] = v
    if custom_fields:
        payload.update(custom_fields)
    if not payload:
        raise ValueError("No deal changes supplied.")
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "before": before, "proposed": payload}
    _require_write_scope()
    await _client().update_deal(deal_id, payload)
    after = await _client().get_deal(deal_id)
    return {"status": "WRITE_COMPLETED_AND_RE_READ", "before": before, "after": after}


@mcp.tool()
async def log_external_call_record(
    person_id: int,
    expected_contact_name: str,
    phone: str,
    is_incoming: bool,
    duration_seconds: int,
    outcome: str | None = None,
    note: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Record an externally made/received call in FUB. DOES NOT place a call."""
    assert_no_sensitive_data(outcome, note, field_label="call log")
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    payload: dict[str, Any] = {
        "personId": person_id,
        "phone": phone,
        "isIncoming": is_incoming,
        "duration": duration_seconds,
    }
    if outcome is not None:
        payload["outcome"] = outcome
    if note is not None:
        payload["note"] = note
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "IMPORTANT": "LOG ONLY — DOES NOT PLACE CALL", "payload": payload}
    _require_write_scope()
    created = await _client().log_call(payload)
    return {"status": "WRITE_COMPLETED", "IMPORTANT": "LOG ONLY — NO CALL WAS PLACED", "created": created}


@mcp.tool()
async def log_external_text_record(
    person_id: int,
    expected_contact_name: str,
    message: str,
    to_number: str,
    from_number: str,
    is_incoming: bool = False,
    external_label: str = "Blaise FUB MCP external log",
    execute: bool = False,
) -> dict[str, Any]:
    """Record an externally sent/received text in FUB. DOES NOT send a text."""
    assert_no_sensitive_data(message, field_label="text log")
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    payload = {
        "personId": person_id,
        "message": message,
        "toNumber": to_number,
        "fromNumber": from_number,
        "isIncoming": is_incoming,
        "externalLabel": external_label,
    }
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "IMPORTANT": "LOG ONLY — DOES NOT SEND TEXT", "payload": payload}
    _require_write_scope()
    created = await _client().log_text_message(payload)
    return {"status": "WRITE_COMPLETED", "IMPORTANT": "LOG ONLY — NO TEXT WAS SENT", "created": created}


# ==================== DAILY CONTROL AUDIT (read-only) ====================


async def _audit_contact_daily_control(
    person_id: int,
    expected_contact_name: str,
    expected_assigned_user_id: int | None,
    stale_note_days: int,
) -> dict[str, Any]:
    client = _client()
    person = await client.get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    open_tasks = await _get_all_open_tasks(client, person_id)
    notes_response = await client.get_notes(person_id, limit=50)
    notes = _list_items(notes_response, "notes")
    notes_scope_note = _truncation_note(notes_response, notes, "notes")
    events = _list_items(await client.get_events(person_id, limit=50), "events")
    findings = find_gaps(
        person=person,
        open_tasks=open_tasks,
        notes=notes,
        events=events,
        expected_assigned_user_id=expected_assigned_user_id,
        stale_note_days=stale_note_days,
    )
    return {
        "status": "AUDIT_COMPLETE",
        "personId": person_id,
        "name": _person_name(person),
        "assignedUserId": person.get("assignedUserId"),
        "findings": findings,
        "evidence_scope": {
            "open_tasks_checked": len(open_tasks),
            "notes_checked": len(notes),
            "events_checked": len(events),
            "notes_scope_limitation": notes_scope_note,
        },
        "caveats": [
            "Findings reflect only what the FUB API returned at read time.",
            "Absence of API-visible communication, events, or notes is not proof that no interaction occurred.",
            "An empty findings list means no gap was detected by these specific checks at "
            "their configured thresholds; it is not a certification that the record is complete.",
            "Threshold-based findings are advisory implementation defaults, not Follow Up Boss business policy.",
        ],
    }


@mcp.tool()
async def audit_contact_daily_control(
    person_id: int,
    expected_contact_name: str,
    expected_assigned_user_id: int | None = None,
    stale_note_days: int = 21,
) -> dict[str, Any]:
    """Read-only control-gap audit for one specifically authorized contact.

    Checks: no future task, overdue tasks, exact-duplicate open tasks,
    same-day conflicting next actions, no sufficiently recent interaction
    note, and (when expected_assigned_user_id is supplied) ownership
    mismatch. Every finding includes the evidence it was derived from. This
    tool makes no writes and never treats missing API activity as proof that
    no activity occurred.
    """
    return await _audit_contact_daily_control(
        person_id, expected_contact_name, expected_assigned_user_id, stale_note_days
    )


@mcp.tool()
async def audit_contacts_daily_control_batch(
    contacts: list[dict[str, Any]],
    stale_note_days: int = 21,
) -> dict[str, Any]:
    """Run the daily-control audit over an explicit, caller-authorized contact list.

    Each entry in `contacts` must provide person_id and expected_contact_name;
    expected_assigned_user_id is optional per entry. This never enumerates or
    scans the account on its own — only the exact records passed in are read.
    """
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for entry in contacts:
        try:
            person_id = int(entry["person_id"])
            expected_contact_name = str(entry["expected_contact_name"])
            expected_assigned_user_id = entry.get("expected_assigned_user_id")
            results.append(
                await _audit_contact_daily_control(
                    person_id, expected_contact_name, expected_assigned_user_id, stale_note_days
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad entry must not abort the batch
            errors.append({"input": entry, "error": str(exc)})
    return {"status": "BATCH_AUDIT_COMPLETE", "results": results, "errors": errors}


# ==================== SAFE INTERACTION CLOSEOUT ====================


@mcp.tool()
async def close_out_contact_interaction(
    person_id: int,
    expected_contact_name: str,
    expected_assigned_user_id: int,
    note_subject: str,
    note_body: str,
    create_next_task: bool = False,
    next_task_name: str | None = None,
    next_task_type: str | None = None,
    next_task_due_date: str | None = None,
    next_task_due_date_time: str | None = None,
    next_task_remind_seconds_before: int | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview/execute a safe FUB interaction closeout: one note + at most one task.

    Defaults to PREVIEW_ONLY_NO_WRITE. On execute=True: verifies the exact
    contact and current owner, skips a note or task that already exists as an
    exact duplicate, creates the requested note and (if asked) exactly one
    dated next task, independently re-reads every write, diffs the contact
    and its other open tasks before vs. after, and reports any change outside
    what was requested as unresolved rather than silently accepting it.
    """
    assert_no_sensitive_data(note_subject, note_body, next_task_name, field_label="closeout content")
    _require_meaningful_text(note_subject, "Note subject")
    _require_meaningful_text(note_body, "Note body")

    if create_next_task:
        if not next_task_name or not next_task_type:
            raise ValueError("next_task_name and next_task_type are required when create_next_task=True.")
        if is_vague_task_name(next_task_name):
            raise ValueError(
                f"next_task_name {next_task_name!r} is a bare placeholder, not a next commitment. "
                "Name the actual next step, e.g. 'Call to confirm inspection date' instead of "
                "'Call' or 'Follow Up'."
            )
        if next_task_type not in ALLOWED_TASK_TYPES:
            raise ValueError(f"Unsupported task type: {next_task_type}")
        if bool(next_task_due_date) == bool(next_task_due_date_time):
            raise ValueError("Provide exactly one of next_task_due_date or next_task_due_date_time.")
        _validate_tz(next_task_due_date_time, "next_task_due_date_time")

    client = _client()
    before_person = await client.get_person(person_id)
    _assert_person(before_person, person_id, expected_contact_name)

    actual_owner = before_person.get("assignedUserId")
    if actual_owner is None or int(actual_owner) != int(expected_assigned_user_id):
        raise ValueError(
            f"Owner verification failed: contact {person_id} is assigned to user "
            f"{actual_owner!r}, expected {expected_assigned_user_id}. Refusing to "
            "close out with an unverified owner."
        )

    before_open_tasks = await _get_all_open_tasks(client, person_id)
    notes_response = await client.get_notes(person_id, limit=50)
    existing_notes = _list_items(notes_response, "notes")
    dedup_scope_note = _truncation_note(notes_response, existing_notes, "notes")

    note_duplicate = find_duplicate_note(existing_notes, subject=note_subject, body=note_body)
    task_payload: dict[str, Any] | None = None
    task_duplicate: dict[str, Any] | None = None
    if create_next_task:
        task_payload = {
            "personId": person_id,
            "assignedUserId": expected_assigned_user_id,
            "name": next_task_name,
            "type": next_task_type,
            "isCompleted": False,
        }
        if next_task_due_date:
            task_payload["dueDate"] = next_task_due_date
        if next_task_due_date_time:
            task_payload["dueDateTime"] = next_task_due_date_time
        if next_task_remind_seconds_before is not None:
            task_payload["remindSecondsBefore"] = next_task_remind_seconds_before
        task_duplicate = find_exact_duplicate_task(
            before_open_tasks,
            name=next_task_name,  # type: ignore[arg-type]
            task_type=next_task_type,  # type: ignore[arg-type]
            due_date=next_task_due_date,
            due_date_time=next_task_due_date_time,
        )

    # Relationship-context surfaced for human review only — never written back
    # to FUB. Helps confirm the new note doesn't contradict recent history and
    # that a real next commitment exists rather than the record going stale.
    context = {
        "recent_notes": summarize_recent_notes(existing_notes),
        "open_tasks_before": _task_summaries(before_open_tasks),
        "dedup_scope_limitation": dedup_scope_note,
    }
    next_commitment_advisory: str | None = None
    if not create_next_task and not before_open_tasks:
        next_commitment_advisory = (
            "No open task exists and this closeout does not create one — the contact will have "
            "no dated next action after this write. Consider create_next_task=True."
        )

    preview = {
        "personId": person_id,
        "name": _person_name(before_person),
        "assignedUserId": actual_owner,
        "context": context,
        "next_commitment_advisory": next_commitment_advisory,
        "note": {
            "subject": note_subject,
            "body": note_body,
            "would_skip_as_duplicate": note_duplicate is not None,
        },
        "task": (
            {**task_payload, "would_skip_as_duplicate": task_duplicate is not None}
            if task_payload is not None
            else {"status": "NOT_REQUESTED"}
        ),
    }

    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "preview": preview}

    _require_write_scope()

    unresolved: list[str] = []

    try:
        note_result = await _write_note_with_verification(client, person_id, note_subject, note_body, existing_notes)
    except Exception as exc:  # noqa: BLE001 - report the partial state, never lose it to a crash
        note_result = {"status": "WRITE_FAILED", "error": redact_for_log(str(exc))}

    task_result: dict[str, Any] = {"status": "NOT_REQUESTED"}
    if task_payload is not None:
        try:
            task_result = await _write_task_with_dedup_and_verification(client, task_payload, before_open_tasks)
        except Exception as exc:  # noqa: BLE001 - report the partial state, never lose it to a crash
            task_result = {"status": "WRITE_FAILED", "error": redact_for_log(str(exc))}

    try:
        after_person = await client.get_person(person_id)
        after_open_tasks = await _get_all_open_tasks(client, person_id)
    except Exception as exc:  # noqa: BLE001
        after_person = before_person
        after_open_tasks = before_open_tasks
        unresolved.append(
            f"Could not independently confirm final contact/task state after writing: {redact_for_log(str(exc))}"
        )

    # Resolve created object ids from ANY status that actually wrote something.
    # Restricting this to the fully-verified status loses the id in exactly the
    # case where a human most needs it: the object was created but read-back
    # failed, so it must be reconciled by hand.
    task_outcome = _write_outcome(task_result)
    created_task_id = task_outcome["id"]
    task_id_verified = task_outcome["verified"]
    # A task this call created is never an "unexpected" new task, even when its
    # read-back failed — otherwise the report accuses itself of an unrelated change.
    allowed_new_task_ids: frozenset[Any] = frozenset({created_task_id}) if created_task_id is not None else frozenset()

    person_diff = diff_person_snapshot(before_person, after_person)
    unrelated_task_changes = find_unexpected_task_changes(
        before_open_tasks, after_open_tasks, allowed_new_task_ids=allowed_new_task_ids
    )

    note_outcome = _write_outcome(note_result)
    created_note_id = note_outcome["id"]
    note_id_verified = note_outcome["verified"]

    ok_statuses = {"WRITE_COMPLETED_AND_RE_READ", "SKIPPED_EXACT_DUPLICATE_EXISTS", "NOT_REQUESTED"}
    if note_result.get("status") not in ok_statuses:
        unresolved.append(f"Note write not fully verified: {note_result.get('status')}.")
    if task_result.get("status") not in ok_statuses:
        unresolved.append(f"Task write not fully verified: {task_result.get('status')}.")
    if person_diff:
        unresolved.append(f"Unexpected contact field change(s) detected: {sorted(person_diff.keys())}.")
    if unrelated_task_changes:
        unresolved.append("Unexpected change(s) detected on pre-existing open tasks.")

    return {
        "status": "CLOSEOUT_COMPLETED" if not unresolved else "CLOSEOUT_COMPLETED_WITH_HOLD",
        "personId": person_id,
        "name": _person_name(after_person),
        "note": note_result,
        "task": task_result,
        "dedup_scope_limitation": dedup_scope_note,
        "before_after": {
            "person_field_changes": person_diff,
            "unrelated_open_task_changes": unrelated_task_changes,
            "open_task_count_before": len(before_open_tasks),
            "open_task_count_after": len(after_open_tasks),
        },
        "created_object_ids": {
            "note_id": created_note_id,
            "note_id_verified": note_id_verified,
            "note_outcome": note_outcome["outcome"],
            "note_matched_existing_id": note_outcome["matched_existing_id"],
            "task_id": created_task_id,
            "task_id_verified": task_id_verified,
            "task_outcome": task_outcome["outcome"],
            "task_matched_existing_id": task_outcome["matched_existing_id"],
        },
        "unresolved": unresolved,
    }


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
