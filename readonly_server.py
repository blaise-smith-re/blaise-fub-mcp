from __future__ import annotations

import os
from typing import Any

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

from auth0_verifier import Auth0TokenVerifier
from fub_client import FUBClient
from task_dates import filter_tasks_by_due_date, parse_calendar_date, resolve_timezone

CHICAGO_TIMEZONE = "America/Chicago"
REQUIRED_SCOPES = ("fub:read",)
READ_TOOL_NAMES = (
    "get_contact",
    "get_contact_events",
    "get_contact_notes",
    "get_contact_appointments",
    "search_tasks",
    "get_open_tasks",
)


def _public_base() -> str:
    value = os.getenv("MCP_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not value:
        raise RuntimeError("Set MCP_PUBLIC_URL or deploy on Render.")
    return value.rstrip("/")


PUBLIC_BASE = _public_base()
RESOURCE_SERVER_URL = os.getenv("AUTH0_AUDIENCE") or f"{PUBLIC_BASE}/mcp"
AUTH0_DOMAIN = os.environ["AUTH0_DOMAIN"].strip().rstrip("/")
if not AUTH0_DOMAIN.startswith("http"):
    AUTH0_DOMAIN = f"https://{AUTH0_DOMAIN}"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "10000"))

mcp = FastMCP(
    "Blaise FUB Read-Only Pilot",
    host=HOST,
    port=PORT,
    stateless_http=True,
    json_response=True,
    instructions=(
        "Read only from Blaise Smith's Follow Up Boss account for the Real Estate OS pilot. "
        "Use exact-record targeting, complete task retrieval, and America/Chicago for date-sensitive work. "
        "No write, send, delete, scheduling, or account-configuration tool exists on this endpoint."
    ),
    token_verifier=Auth0TokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(f"{AUTH0_DOMAIN}/"),
        # OAuth discovery must advertise the same resource identifier that the
        # token verifier accepts. This may intentionally differ from the
        # read-only service's transport URL when it reuses an existing Auth0 API.
        resource_server_url=AnyHttpUrl(RESOURCE_SERVER_URL),
        required_scopes=list(REQUIRED_SCOPES),
    ),
)


def _client() -> FUBClient:
    return FUBClient()


def _positive_id(value: int | None, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer.")
    return value


def _required_positive_id(value: int, field: str) -> int:
    normalized = _positive_id(value, field)
    if normalized is None:
        raise ValueError(f"{field} is required.")
    return normalized


@mcp.tool()
async def get_contact(person_id: int) -> dict[str, Any]:
    """Retrieve one contact by exact FUB person ID. Read-only."""
    return await _client().get_person(_required_positive_id(person_id, "person_id"))


@mcp.tool()
async def get_contact_events(person_id: int, limit: int = 50, next_token: str | None = None) -> dict[str, Any]:
    """Retrieve a bounded contact-event window. Read-only; pagination remains disclosed."""
    return await _client().get_events(_required_positive_id(person_id, "person_id"), limit=limit, next_token=next_token)


@mcp.tool()
async def get_contact_notes(person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Retrieve a bounded contact-note window. Read-only; total/offset metadata remains disclosed."""
    return await _client().get_notes(_required_positive_id(person_id, "person_id"), limit=limit, offset=offset)


@mcp.tool()
async def get_contact_appointments(person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Retrieve a bounded appointment window for one exact contact. Read-only."""
    return await _client().search_appointments(
        personId=_required_positive_id(person_id, "person_id"),
        limit=min(max(limit, 1), 100),
        offset=max(offset, 0),
    )


@mcp.tool()
async def search_tasks(
    person_id: int | None = None,
    assigned_user_id: int | None = None,
    task_type: str | None = None,
    is_completed: bool | None = None,
    due_on: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    due_timezone: str = CHICAGO_TIMEZONE,
    limit: int = 100,
    offset: int = 0,
    fetch_all: bool = True,
) -> dict[str, Any]:
    """Retrieve a complete, owner/contact-bound, calendar-date-bounded task set.

    This pilot endpoint intentionally omits FUB's unreliable legacy ``due`` keyword and refuses
    caller-controlled pagination. The full matching set is retrieved before local date filtering.
    """
    person_id = _positive_id(person_id, "person_id")
    assigned_user_id = _positive_id(assigned_user_id, "assigned_user_id")
    if person_id is None and assigned_user_id is None:
        raise ValueError("Provide an exact person_id or assigned_user_id.")
    if due_on is None and due_from is None and due_to is None:
        raise ValueError("Provide due_on or a due_from/due_to calendar-date bound.")
    if due_timezone != CHICAGO_TIMEZONE:
        raise ValueError(f"due_timezone must be {CHICAGO_TIMEZONE} for this endpoint.")
    if fetch_all is not True or limit != 100 or offset != 0:
        raise ValueError("Partial task retrieval is prohibited; use fetch_all=true, limit=100, offset=0.")

    tz = resolve_timezone(due_timezone)
    due_on_date = parse_calendar_date(due_on, field_label="due_on") if due_on is not None else None
    due_from_date = parse_calendar_date(due_from, field_label="due_from") if due_from is not None else None
    due_to_date = parse_calendar_date(due_to, field_label="due_to") if due_to is not None else None
    if due_from_date is not None and due_to_date is not None and due_from_date > due_to_date:
        raise ValueError(f"due_from {due_from!r} is after due_to {due_to!r}.")

    tasks, completeness = await _client().search_tasks_all(
        personId=person_id,
        assignedUserId=assigned_user_id,
        type=task_type,
        isCompleted=is_completed,
    )
    tasks, unusable_due = filter_tasks_by_due_date(
        tasks,
        due_on=due_on_date,
        due_from=due_from_date,
        due_to=due_to_date,
        tz=tz,
    )
    return {
        "tasks": tasks,
        "_completeness": completeness,
        "due_date_filter": {
            "due_on": due_on_date.isoformat() if due_on_date else None,
            "due_from": due_from_date.isoformat() if due_from_date else None,
            "due_to": due_to_date.isoformat() if due_to_date else None,
            "timezone": due_timezone,
            "excluded_no_usable_due_date": unusable_due,
        },
    }


@mcp.tool()
async def get_open_tasks(person_id: int) -> dict[str, Any]:
    """Retrieve every open task for one exact contact with completeness metadata. Read-only."""
    tasks, completeness = await _client().search_tasks_all(
        personId=_required_positive_id(person_id, "person_id"),
        isCompleted=False,
    )
    return {
        "tasks": tasks,
        "_metadata": {"total": completeness["total_count"]},
        "_completeness": completeness,
    }


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
