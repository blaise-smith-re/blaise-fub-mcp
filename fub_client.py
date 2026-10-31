from __future__ import annotations

import os
import ssl
from functools import lru_cache
from typing import Any

import certifi
import httpx


@lru_cache(maxsize=1)
def _tls_context() -> ssl.SSLContext:
    """Reuse the CA store, not responses, credentials, sockets or MCP sessions.

    Match HTTPX's default trust-store selection. Configuration/certificate
    changes take effect on process restart, as with the service's auth setup.
    """
    if os.environ.get("SSL_CERT_FILE"):
        return ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    if os.environ.get("SSL_CERT_DIR"):
        return ssl.create_default_context(capath=os.environ["SSL_CERT_DIR"])
    return ssl.create_default_context(cafile=certifi.where())


class FUBClient:
    """Follow Up Boss API client used by the Blaise FUB MCP."""

    def __init__(self) -> None:
        self.base_url = os.getenv("FUB_BASE_URL", "https://api.followupboss.com/v1").rstrip("/")
        self.api_key = os.environ["FUB_API_KEY"]
        self.x_system = os.environ["FUB_X_SYSTEM"]
        self.x_system_key = os.environ["FUB_X_SYSTEM_KEY"]

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-System": self.x_system,
            "X-System-Key": self.x_system_key,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = dict(self._headers)
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(
            base_url=self.base_url,
            auth=(self.api_key, ""),
            headers=headers,
            timeout=30.0,
            verify=_tls_context(),
        ) as client:
            response = await client.request(method, path, params=params, json=json_body)
            response.raise_for_status()
            if not response.content:
                return {"ok": True, "status_code": response.status_code}
            return response.json()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, body: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", path, params=params, json_body=body)

    async def _put(self, path: str, body: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("PUT", path, params=params, json_body=body)

    # ---------- people ----------
    async def find_people(self, **params: Any) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        if not clean:
            raise ValueError("Provide at least one search criterion.")
        clean.setdefault("limit", 10)
        clean["limit"] = min(max(int(clean["limit"]), 1), 25)
        clean.setdefault(
            "fields",
            "id,firstName,lastName,emails,phones,stage,source,assignedTo,assignedUserId,"
            "assignedLenderName,assignedLenderId,lastActivity,lastCommunication,nextTask,"
            "created,updated,tags,price,timeframeId",
        )
        return await self._get("/people", params=clean)

    async def get_person(self, person_id: int) -> dict[str, Any]:
        return await self._get(f"/people/{person_id}", params={"fields": "allFields"})

    async def update_person(self, person_id: int, body: dict[str, Any], *, merge_tags: bool = False) -> dict[str, Any]:
        return await self._put(
            f"/people/{person_id}",
            body,
            params={"mergeTags": "true"} if merge_tags else None,
        )

    # ---------- timeline/activity ----------
    async def get_events(self, person_id: int, limit: int = 50, next_token: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"personId": person_id, "limit": min(max(limit, 1), 100)}
        if next_token:
            params["next"] = next_token
        return await self._get("/events", params=params)

    async def get_notes(self, person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self._get(
            "/notes",
            params={"personId": person_id, "limit": min(max(limit, 1), 100), "offset": max(offset, 0)},
        )

    async def create_note(self, person_id: int, subject: str, body: str) -> dict[str, Any]:
        return await self._post(
            "/notes",
            {"personId": person_id, "subject": subject, "body": body, "isHtml": False},
        )

    async def get_calls(self, person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self._get(
            "/calls",
            params={"personId": person_id, "limit": min(max(limit, 1), 100), "offset": max(offset, 0)},
        )

    async def log_call(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/calls", body)

    async def get_text_messages(self, person_id: int, limit: int = 50, next_token: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"personId": person_id, "limit": min(max(int(limit), 1), 100)}
        if next_token:
            params["next"] = next_token
        return await self._get("/textMessages", params=params)

    async def get_text_messages_all(
        self, person_id: int, *, limit: int = 50, next_token: str | None = None, max_pages: int = 5
    ) -> dict[str, Any]:
        """Bounded exact-person API paging, never a claim of full communication history."""
        page_limit = min(max(int(max_pages), 1), 5)
        cursor = next_token
        seen_cursors = {cursor} if cursor else set()
        seen_ids: set[str] = set()
        messages: list[dict[str, Any]] = []
        totals: set[int] = set()
        first: dict[str, Any] | None = None
        meta: dict[str, Any] = {}
        pages = 0
        exhausted = False
        stop_reason = "page_limit"
        error: str | None = None
        for _ in range(page_limit):
            try:
                page = await self.get_text_messages(person_id, limit=limit, next_token=cursor)
                rows = page.get("textmessages")
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("FUB text-message collection is invalid.")
            except Exception as exc:
                if first is None:
                    raise
                stop_reason = "page_error"
                error = (
                    f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
                )
                break
            if first is None:
                first = page
            pages += 1
            meta = page.get("_metadata") or {}
            total = meta.get("total")
            if isinstance(total, int) and not isinstance(total, bool):
                totals.add(total)
            for row in rows:
                key = str(row["id"]) if row.get("id") is not None else None
                if key is None or key not in seen_ids:
                    messages.append(row)
                    if key is not None:
                        seen_ids.add(key)
            if "next" not in meta:
                stop_reason = "missing_pagination_metadata"
                break
            cursor = meta["next"]
            if cursor is None:
                exhausted = True
                stop_reason = "api_pages_exhausted"
                break
            if not isinstance(cursor, str) or not cursor.strip():
                stop_reason = "invalid_cursor"
                break
            if cursor in seen_cursors:
                stop_reason = "repeated_cursor"
                break
            seen_cursors.add(cursor)
        result = dict(first or {})
        result["textmessages"] = messages
        result["_metadata"] = {**meta, "next": cursor}
        complete = exhausted and len(totals) <= 1
        if len(totals) > 1:
            complete = False
            stop_reason = "total_changed"
        if complete and next_token is None and totals and len(messages) != next(iter(totals)):
            complete = False
            stop_reason = "terminal_count_mismatch"
        result["_completeness"] = {
            "returned_count": len(messages),
            "total_count": next(iter(totals)) if len(totals) == 1 else None,
            "pages_fetched": pages,
            "api_pages_exhausted": exhausted,
            "complete": complete,
            "started_at_beginning": next_token is None,
            "stop_reason": stop_reason,
            "resume_next_token": cursor,
            "error": error,
            "scope": "API-visible records only; never full SMS, email, personal-phone or app-only history",
        }
        return result

    async def log_text_message(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/textMessages", body)

    # ---------- tasks ----------
    async def search_tasks(self, **params: Any) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        return await self._get("/tasks", params=clean)

    async def search_tasks_all(
        self,
        *,
        page_size: int = 100,
        max_items: int = 1000,
        max_pages: int = 50,
        **params: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Page through /tasks until the complete matching set is retrieved.

        A single-page `search_tasks` call relies on whatever default limit
        FUB applies when none is given — verified in production to silently
        return fewer tasks than the account actually has (FUB 06 v1.6: 21 of
        22 reported open tasks, no pagination parameter exposed). This method
        exists specifically so nothing downstream has to trust that default.

        Loops on limit/offset, tracks FUB's own `_metadata.total` when
        present, and de-duplicates by task id (defensive against a page
        overlap if the underlying set mutates mid-scan). Bounded by
        `max_items` and `max_pages` so an unexpectedly huge result set fails
        safely — capped and disclosed — rather than looping unbounded.

        Returns (tasks, completeness) where completeness reports
        returned_count, total_count (None if FUB didn't disclose one),
        has_more, capped, and pages_fetched.
        """
        clean = {k: v for k, v in params.items() if v is not None}
        limit = min(max(int(page_size), 1), 100)
        offset = 0
        collected: list[dict[str, Any]] = []
        seen_ids: set[Any] = set()
        total: int | None = None
        pages = 0
        capped = False

        while True:
            response = await self.search_tasks(**clean, limit=limit, offset=offset)
            page_items = list(response.get("tasks") or response.get("data") or [])
            meta = response.get("_metadata") or {}
            if isinstance(meta.get("total"), int):
                total = meta["total"]
            pages += 1

            new_this_page = 0
            for task in page_items:
                key = task.get("id")
                dedup_key = key if key is not None else id(task)
                if dedup_key in seen_ids:
                    continue
                seen_ids.add(dedup_key)
                collected.append(task)
                new_this_page += 1

            if len(collected) >= max_items:
                capped = True
                break
            if not page_items or len(page_items) < limit:
                break
            if new_this_page == 0:
                # A full page with nothing new: stop rather than loop forever
                # against a misbehaving or shifting result set.
                break
            if pages >= max_pages:
                capped = True
                break
            offset += limit

        completeness = {
            "returned_count": len(collected),
            "total_count": total,
            "has_more": bool(capped or (isinstance(total, int) and total > len(collected))),
            "capped": capped,
            "pages_fetched": pages,
        }
        return collected, completeness

    async def get_task(self, task_id: int) -> dict[str, Any]:
        return await self._get(f"/tasks/{task_id}")

    async def create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/tasks", body)

    async def update_task(self, task_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return await self._put(f"/tasks/{task_id}", body)

    # ---------- appointments ----------
    async def search_appointments(self, **params: Any) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        return await self._get("/appointments", params=clean)

    async def get_appointment(self, appointment_id: int) -> dict[str, Any]:
        return await self._get(f"/appointments/{appointment_id}")

    async def create_appointment(self, body: dict[str, Any], *, send_invitation: bool = False) -> dict[str, Any]:
        return await self._post(
            "/appointments", body, params={"sendInvitation": "true" if send_invitation else "false"}
        )

    async def update_appointment(
        self, appointment_id: int, body: dict[str, Any], *, send_invitation: bool = False
    ) -> dict[str, Any]:
        return await self._put(
            f"/appointments/{appointment_id}",
            body,
            params={"sendInvitation": "true" if send_invitation else "false"},
        )

    # ---------- deals ----------
    async def search_deals(self, **params: Any) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        return await self._get("/deals", params=clean)

    async def get_deal(self, deal_id: int) -> dict[str, Any]:
        return await self._get(f"/deals/{deal_id}")

    async def create_deal(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/deals", body)

    async def update_deal(self, deal_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return await self._put(f"/deals/{deal_id}", body)

    async def create_deal_attachment(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/dealAttachments", body)

    async def get_deal_attachment(self, attachment_id: int) -> dict[str, Any]:
        return await self._get(f"/dealAttachments/{attachment_id}")

    # ---------- account/config reads ----------
    async def get_stages(self) -> dict[str, Any]:
        return await self._get("/stages", params={"limit": 100, "sort": "orderWeight"})

    async def get_users(self) -> dict[str, Any]:
        return await self._get("/users", params={"limit": 100, "fields": "allFields"})

    async def get_user(self, user_id: int) -> dict[str, Any]:
        return await self._get(f"/users/{user_id}")

    async def get_timeframes(self) -> dict[str, Any]:
        return await self._get("/timeframes")

    async def get_custom_fields(self) -> dict[str, Any]:
        return await self._get("/customFields")

    async def get_deal_custom_fields(self) -> dict[str, Any]:
        return await self._get("/dealCustomFields")

    async def get_pipelines(self) -> dict[str, Any]:
        return await self._get("/pipelines")

    async def get_appointment_types(self) -> dict[str, Any]:
        return await self._get("/appointmentTypes", params={"limit": 100, "sort": "orderWeight"})

    async def get_appointment_outcomes(self) -> dict[str, Any]:
        return await self._get("/appointmentOutcomes", params={"limit": 100, "sort": "orderWeight"})
