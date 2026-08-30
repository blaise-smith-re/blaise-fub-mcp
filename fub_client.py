from __future__ import annotations

import os
from typing import Any

import httpx


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

    async def get_text_messages(self, person_id: int) -> dict[str, Any]:
        return await self._get("/textMessages", params={"personId": person_id})

    async def log_text_message(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/textMessages", body)

    # ---------- tasks ----------
    async def search_tasks(self, **params: Any) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        return await self._get("/tasks", params=clean)

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
