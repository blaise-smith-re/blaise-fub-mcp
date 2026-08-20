from __future__ import annotations

import os
import re
from typing import Any

from pydantic import AnyHttpUrl
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP

from auth0_verifier import Auth0TokenVerifier
from fub_client import FUBClient


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
    return " ".join(
        p for p in [person.get("firstName"), person.get("lastName")] if p
    ).strip()


def _assert_person(person: dict[str, Any], person_id: int, expected_name: str) -> None:
    if int(person.get("id")) != person_id:
        raise ValueError("Exact person ID check failed.")
    actual = _person_name(person)
    if actual.casefold().strip() != expected_name.casefold().strip():
        raise ValueError(
            f"Exact contact-name check failed: record is '{actual}', not '{expected_name}'."
        )


def _assert_task(task: dict[str, Any], task_id: int, person_id: int, expected_name: str) -> None:
    if int(task.get("id")) != task_id:
        raise ValueError("Exact task ID check failed.")
    if int(task.get("personId")) != person_id:
        raise ValueError("Task belongs to a different contact.")
    current_name = str(task.get("name") or "")
    if current_name.casefold().strip() != expected_name.casefold().strip():
        raise ValueError(
            f"Stale task check failed: current task name is '{current_name}'."
        )


def _validate_tz(value: str | None, label: str = "date-time") -> None:
    if value and not (value.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", value)):
        raise ValueError(f"{label} must include an explicit timezone offset or Z.")


def _normalized_values(items: list[dict[str, Any]] | None) -> list[str]:
    return sorted(
        str(item.get("value", "")).strip().casefold()
        for item in (items or [])
        if item.get("value")
    )


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
        email=email, phone=phone, name=name, stage=stage,
        assignedUserId=assigned_user_id, limit=limit,
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
) -> dict[str, Any]:
    return await _client().search_tasks(
        personId=person_id,
        assignedUserId=assigned_user_id,
        type=task_type,
        isCompleted=is_completed,
        due=due,
    )


@mcp.tool()
async def get_open_tasks(person_id: int) -> dict[str, Any]:
    return await _client().search_tasks(personId=person_id, isCompleted=False)


@mcp.tool()
async def get_task(task_id: int) -> dict[str, Any]:
    return await _client().get_task(task_id)


@mcp.tool()
async def get_contact_appointments(person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return await _client().search_appointments(
        personId=person_id, limit=min(max(limit, 1), 100), offset=max(offset, 0)
    )


@mcp.tool()
async def get_appointment(appointment_id: int) -> dict[str, Any]:
    return await _client().get_appointment(appointment_id)


@mcp.tool()
async def get_active_deals(person_id: int) -> dict[str, Any]:
    return await _client().search_deals(personId=person_id, status="Active")


@mcp.tool()
async def search_deals(person_id: int | None = None, user_id: int | None = None, status: str | None = None) -> dict[str, Any]:
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
    """Preview/create a plain-text note on an exact contact."""
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    preview = {"personId": person_id, "name": _person_name(person), "subject": subject, "body": body}
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "preview": preview}
    _require_write_scope()
    created = await _client().create_note(person_id, subject, body)
    return {"status": "WRITE_COMPLETED", "created": created}


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
    """Preview/create one task. Exactly one due_date or due_date_time is required."""
    allowed = {"Follow Up","Call","Text","Email","Appointment","Showing","Closing","Open House","Thank You"}
    if task_type not in allowed:
        raise ValueError(f"Unsupported task type: {task_type}")
    if bool(due_date) == bool(due_date_time):
        raise ValueError("Provide exactly one of due_date or due_date_time.")
    _validate_tz(due_date_time, "due_date_time")
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    await _client().get_user(assigned_user_id)
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
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "preview": payload}
    _require_write_scope()
    created = await _client().create_task(payload)
    if created.get("id"):
        verified = await _client().get_task(int(created["id"]))
        return {"status": "WRITE_COMPLETED_AND_RE_READ", "created": created, "verified": verified}
    return {"status": "WRITE_COMPLETED", "created": created}


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
    task = await _client().get_task(task_id)
    _assert_task(task, task_id, expected_person_id, expected_task_name)
    if new_due_date and new_due_date_time:
        raise ValueError("Use only one due date field.")
    _validate_tz(new_due_date_time, "new_due_date_time")
    payload: dict[str, Any] = {}
    if new_name is not None: payload["name"] = new_name
    if new_task_type is not None: payload["type"] = new_task_type
    if new_due_date is not None: payload["dueDate"] = new_due_date
    if new_due_date_time is not None: payload["dueDateTime"] = new_due_date_time
    if mark_completed is not None: payload["isCompleted"] = mark_completed
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
    before = await _client().get_person(person_id)
    _assert_person(before, person_id, expected_contact_name)
    payload: dict[str, Any] = {}
    if new_first_name is not None: payload["firstName"] = new_first_name
    if new_last_name is not None: payload["lastName"] = new_last_name
    if existing_stage_name is not None:
        stages = await _client().get_stages()
        names = {
            str(x.get("name")) for x in (stages.get("stages") or stages.get("data") or [])
            if x.get("name")
        }
        if existing_stage_name not in names:
            raise ValueError("Stage must already exist in FUB. Shared stage creation is not exposed.")
        payload["stage"] = existing_stage_name
    if price is not None: payload["price"] = price
    if timeframe_id is not None:
        await _client().get_timeframes()
        payload["timeframeId"] = timeframe_id
    if assigned_user_id is not None:
        await _client().get_user(assigned_user_id)
        payload["assignedUserId"] = assigned_user_id
    if assigned_lender_id is not None:
        await _client().get_user(assigned_lender_id)
        payload["assignedLenderId"] = assigned_lender_id
    if assigned_lender_name is not None: payload["assignedLenderName"] = assigned_lender_name
    if background is not None: payload["background"] = background
    if custom_fields:
        definitions = await _client().get_custom_fields()
        valid = {
            str(x.get("name")) for x in (definitions.get("customFields") or definitions.get("data") or [])
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
    _validate_tz(start, "start"); _validate_tz(end, "end")
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    user = await _client().get_user(assigned_user_id)
    if send_invitation and not explicit_send_authorization:
        raise PermissionError("Sending an appointment invitation requires explicit authorization.")
    invitees = [
        {"userId": assigned_user_id, "name": str(user.get("name") or "")},
        {"personId": person_id, "name": _person_name(person), "email": ((person.get("emails") or [{}])[0].get("value"))},
    ]
    payload: dict[str, Any] = {"title": title, "invitees": invitees, "allDay": False, "start": start, "end": end}
    if location is not None: payload["location"] = location
    if description is not None: payload["description"] = description
    if type_id is not None: payload["typeId"] = type_id
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
    _validate_tz(start, "start"); _validate_tz(end, "end")
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
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    if not user_ids:
        raise ValueError("At least one FUB user ID is required so the deal remains visible.")
    for uid in user_ids:
        await _client().get_user(uid)
    payload: dict[str, Any] = {"name": deal_name, "stageId": stage_id, "peopleIds": [person_id], "userIds": user_ids}
    for k, v in {
        "description": description, "price": price, "projectedCloseDate": projected_close_date,
        "mutualAcceptanceDate": mutual_acceptance_date, "earnestMoneyDueDate": earnest_money_due_date,
        "dueDiligenceDate": due_diligence_date, "finalWalkThroughDate": final_walk_through_date,
        "possessionDate": possession_date,
    }.items():
        if v is not None: payload[k] = v
    if custom_fields:
        defs = await _client().get_deal_custom_fields()
        valid = {str(x.get("name")) for x in (defs.get("dealCustomFields") or defs.get("data") or []) if x.get("name")}
        bad = [k for k in custom_fields if k not in valid]
        if bad: raise ValueError(f"Unknown deal custom field(s): {bad}")
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
    before = await _client().get_deal(deal_id)
    if str(before.get("name") or "").casefold().strip() != expected_deal_name.casefold().strip():
        raise ValueError("Stale deal-name check failed.")
    if expected_person_id not in {int(x) for x in (before.get("peopleIds") or [])}:
        raise ValueError("Deal is not linked to the expected contact.")
    payload: dict[str, Any] = {}
    for k, v in {
        "name": new_name, "stageId": stage_id, "description": description, "price": price,
        "projectedCloseDate": projected_close_date, "mutualAcceptanceDate": mutual_acceptance_date,
        "earnestMoneyDueDate": earnest_money_due_date, "dueDiligenceDate": due_diligence_date,
        "finalWalkThroughDate": final_walk_through_date, "possessionDate": possession_date,
    }.items():
        if v is not None: payload[k] = v
    if custom_fields: payload.update(custom_fields)
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
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    payload: dict[str, Any] = {
        "personId": person_id, "phone": phone, "isIncoming": is_incoming, "duration": duration_seconds
    }
    if outcome is not None: payload["outcome"] = outcome
    if note is not None: payload["note"] = note
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
    person = await _client().get_person(person_id)
    _assert_person(person, person_id, expected_contact_name)
    payload = {
        "personId": person_id, "message": message, "toNumber": to_number, "fromNumber": from_number,
        "isIncoming": is_incoming, "externalLabel": external_label,
    }
    if not execute:
        return {"status": "PREVIEW_ONLY_NO_WRITE", "IMPORTANT": "LOG ONLY — DOES NOT SEND TEXT", "payload": payload}
    _require_write_scope()
    created = await _client().log_text_message(payload)
    return {"status": "WRITE_COMPLETED", "IMPORTANT": "LOG ONLY — NO TEXT WAS SENT", "created": created}


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
