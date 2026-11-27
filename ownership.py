"""Non-configurable user-33 authorization at the shared FUB transport boundary.

The raw transport is private and never exposed as an MCP tool. Ownership is
read afresh for each operation, including immediately before a mutation.
No token, prompt, search argument, preview, or environment setting widens it.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

OWNER_ID = 33
DENIED = "FUB access denied: record must be assigned to user 33."
RawRequest = Callable[..., Awaitable[dict[str, Any]]]
CONFIG_READS = {
    "stages",
    "users",
    "timeframes",
    "customFields",
    "dealCustomFields",
    "pipelines",
    "appointmentTypes",
    "appointmentOutcomes",
}
ACTIVITY = {"events": "events", "notes": "notes", "calls": "calls", "textMessages": "textmessages"}


def record_id(value: Any) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise PermissionError(DENIED)
    return int(value)


def require_owner(value: Any) -> None:
    if record_id(value) != OWNER_ID:
        raise PermissionError(DENIED)


def linked_ids(record: dict[str, Any], expanded: str, legacy: str) -> set[int]:
    results = []
    for key in (expanded, legacy):
        if key not in record:
            continue
        values = record[key]
        if not isinstance(values, list):
            raise PermissionError(DENIED)
        results.append({record_id(v.get("id") if isinstance(v, dict) else v) for v in values})
    if not results or any(value != results[0] for value in results):
        raise PermissionError(DENIED)
    return results[0]


class OwnershipBoundary:
    def __init__(self, raw: RawRequest) -> None:
        self.raw = raw
        self.collection_people: set[int] | None = None

    async def person(self, person_id: Any) -> dict[str, Any]:
        pid = record_id(person_id)
        if self.collection_people is not None and pid in self.collection_people:
            return {"id": pid, "assignedUserId": OWNER_ID}
        row = await self.raw("GET", f"/people/{pid}", params={"fields": "id,assignedUserId"})
        if record_id(row.get("id")) != pid:
            raise PermissionError(DENIED)
        require_owner(row.get("assignedUserId"))
        if self.collection_people is not None:
            self.collection_people.add(pid)
        return row

    async def validate(self, kind: str, row: dict[str, Any], expected_id: int | None = None) -> None:
        rid = record_id(row.get("id"))
        if expected_id is not None and rid != expected_id:
            raise PermissionError(DENIED)
        if kind == "people":
            require_owner(row.get("assignedUserId"))
        elif kind == "tasks":
            require_owner(row.get("assignedUserId"))
            await self.person(row.get("personId"))
        elif kind == "deals":
            if OWNER_ID not in linked_ids(row, "users", "userIds"):
                raise PermissionError(DENIED)
            people = linked_ids(row, "people", "peopleIds")
            if not people:
                raise PermissionError(DENIED)
            for pid in sorted(people):
                await self.person(pid)
        elif kind == "appointments":
            people, users = self.invitees(row)
            if not people or OWNER_ID not in users:
                raise PermissionError(DENIED)
            for pid in sorted(people):
                await self.person(pid)
        elif kind == "dealAttachments":
            await self.existing("deals", record_id(row.get("dealId")))
        else:
            raise PermissionError(DENIED)

    @staticmethod
    def invitees(row: dict[str, Any]) -> tuple[set[int], set[int]]:
        values = row.get("invitees")
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise PermissionError(DENIED)
        return (
            {record_id(v["personId"]) for v in values if v.get("personId") is not None},
            {record_id(v["userId"]) for v in values if v.get("userId") is not None},
        )

    async def existing(self, kind: str, rid: int) -> dict[str, Any]:
        row = await self.raw("GET", f"/{kind}/{rid}")
        await self.validate(kind, row, rid)
        return row

    async def write_scope(self, kind: str, body: dict[str, Any], before: dict[str, Any] | None) -> None:
        if kind == "people":
            if "assignedUserId" in body:
                require_owner(body["assignedUserId"])
            # The MCP may maintain a profile, but cannot transfer ownership.
            for key in ("assignedTo", "assignedLenderId", "assignedLenderName"):
                if key in body and (before is None or body[key] != before.get(key)):
                    raise PermissionError("FUB ownership/lender reassignment is not permitted.")
        elif kind in ACTIVITY or kind == "tasks":
            if before is not None and "personId" in body and body["personId"] != before.get("personId"):
                raise PermissionError(DENIED)
            await self.person(body.get("personId", (before or {}).get("personId")))
            if kind == "tasks":
                require_owner(body.get("assignedUserId", (before or {}).get("assignedUserId")))
            if "userId" in body:
                require_owner(body["userId"])
        elif kind == "deals":
            merged = {**(before or {}), **body}
            users = linked_ids(merged, "users", "userIds")
            people = linked_ids(merged, "people", "peopleIds")
            if not people or OWNER_ID not in users:
                raise PermissionError(DENIED)
            if before is None and users != {OWNER_ID}:
                raise PermissionError(DENIED)
            if before is not None and (
                users != linked_ids(before, "users", "userIds") or people != linked_ids(before, "people", "peopleIds")
            ):
                raise PermissionError("FUB deal ownership/contact reassignment is not permitted.")
            for pid in sorted(people):
                await self.person(pid)
        elif kind == "appointments":
            people, users = self.invitees({**(before or {}), **body})
            if not people or OWNER_ID not in users:
                raise PermissionError(DENIED)
            if before is None and users != {OWNER_ID}:
                raise PermissionError(DENIED)
            if before is not None and (people, users) != self.invitees(before):
                raise PermissionError("FUB appointment reassignment is not permitted.")
            for pid in sorted(people):
                await self.person(pid)
        elif kind == "dealAttachments":
            await self.existing("deals", record_id(body.get("dealId")))
        else:
            raise PermissionError("This FUB mutation is not permitted.")

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        match = re.fullmatch(r"/([A-Za-z]+)(?:/([1-9][0-9]*))?", path)
        if not match:
            raise PermissionError("Unsupported FUB resource.")
        kind, identifier = match.groups()
        rid = int(identifier) if identifier else None
        query = dict(params or {})
        if method == "GET" and kind in CONFIG_READS and (rid is None or kind == "users"):
            return await self.raw(method, path, params=params, json_body=json_body)
        if kind not in {"people", "tasks", "deals", "appointments", "dealAttachments", *ACTIVITY}:
            raise PermissionError("Unsupported FUB resource.")
        if method in {"POST", "PUT"}:
            allowed = {
                "POST": {"notes", "calls", "textMessages", "tasks", "deals", "appointments", "dealAttachments"},
                "PUT": {"people", "tasks", "deals", "appointments"},
            }
            if kind not in allowed[method]:
                raise PermissionError("Unsupported FUB mutation.")
            if method == "PUT" and rid is None or method == "POST" and rid is not None:
                raise PermissionError("Unsupported FUB mutation.")
            if not isinstance(json_body, dict):
                raise PermissionError("Missing FUB mutation body.")
            before = await self.existing(kind, rid) if rid else None
            await self.write_scope(kind, json_body, before)
            return await self.raw(method, path, params=params, json_body=json_body)
        if method != "GET":
            raise PermissionError("Unsupported FUB mutation.")
        if rid is not None:
            row = await self.raw(method, path, params=params)
            await self.validate(kind, row, rid)
            return row
        owner_field = {"people": "assignedUserId", "tasks": "assignedUserId", "deals": "userId"}.get(kind)
        if owner_field:
            if query.get(owner_field) is not None:
                require_owner(query[owner_field])
            query[owner_field] = OWNER_ID
        if kind in ACTIVITY or kind == "appointments" or query.get("personId") is not None:
            await self.person(query.get("personId"))
        # Attachments have only exact-ID reads in the MCP.
        if kind == "dealAttachments":
            raise PermissionError("Exact attachment ID required.")
        result = await self.raw(method, path, params=query)
        key = ACTIVITY.get(kind, kind)
        if key not in result and "data" in result:
            key = "data"
        rows = result.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise PermissionError("Invalid scoped FUB collection.")
        if key != "data" and "data" in result:
            # Never leave a second, unvalidated copy of collection records.
            result = {k: v for k, v in result.items() if k != "data"}
        authorized = []
        # Reuse checks only inside this one read page; never across requests,
        # previews, write preflights, or pagination calls.
        self.collection_people = set()
        for row in rows:
            try:
                if kind in ACTIVITY:
                    if row.get("personId") is not None and record_id(row["personId"]) != record_id(query["personId"]):
                        raise PermissionError(DENIED)
                else:
                    await self.validate(kind, row)
                authorized.append(row)
            except PermissionError:
                continue
        if len(authorized) == len(rows):
            return result
        # Keep cursor/offset traversal honest even when an upstream owner filter
        # returns a mixed page. Do not expose excluded records or their totals.
        result = {**result, key: authorized}
        result["_metadata"] = {**(result.get("_metadata") or {}), "total": None}
        result["_scope"] = {"assigned_user_id": OWNER_ID, "filtered": True, "raw_page_count": len(rows)}
        return result
