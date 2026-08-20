from __future__ import annotations

import os
from typing import Any

import httpx


class FUBClient:
    """Minimal read-only Follow Up Boss API client.

    Upstream auth uses FUB's documented API-key Basic Auth plus registered
    X-System / X-System-Key headers. No write methods exist in v1.
    """

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

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            auth=(self.api_key, ""),
            headers=self._headers,
            timeout=30.0,
        ) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    async def find_people(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        stage: str | None = None,
        assigned_user_id: int | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if not any([email, phone, name, stage, assigned_user_id]):
            raise ValueError("Provide at least one search criterion.")
        params: dict[str, Any] = {
            "limit": min(max(limit, 1), 25),
            "fields": "id,firstName,lastName,emails,phones,stage,source,assignedTo,assignedUserId,lastActivity,lastCommunication,nextTask,created,updated",
        }
        if email:
            params["email"] = email
        if phone:
            params["phone"] = phone
        if name:
            params["name"] = name
        if stage:
            params["stage"] = stage
        if assigned_user_id is not None:
            params["assignedUserId"] = assigned_user_id
        return await self._get("/people", params=params)

    async def get_person(self, person_id: int) -> dict[str, Any]:
        return await self._get(f"/people/{person_id}", params={"fields": "allFields"})

    async def get_events(self, person_id: int, limit: int = 50, next_token: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"personId": person_id, "limit": min(max(limit, 1), 100)}
        if next_token:
            params["next"] = next_token
        return await self._get("/events", params=params)


    async def get_notes(self, person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Retrieve API-visible notes for one person.

        FUB may restrict some notes from API access even when they are visible in the UI.
        """
        return await self._get(
            "/notes",
            params={
                "personId": person_id,
                "limit": min(max(limit, 1), 100),
                "offset": max(offset, 0),
            },
        )

    async def get_calls(self, person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Retrieve API-visible calls for one person.

        FUB documents that some call data is visible only inside the FUB application.
        """
        return await self._get(
            "/calls",
            params={
                "personId": person_id,
                "limit": min(max(limit, 1), 100),
                "offset": max(offset, 0),
            },
        )

    async def get_text_messages(self, person_id: int) -> dict[str, Any]:
        """Retrieve API-visible text messages for one person.

        FUB documents that some text-message data is visible only inside the FUB application.
        """
        return await self._get("/textMessages", params={"personId": person_id})

    async def get_appointments(self, person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Retrieve API-visible FUB-created appointments for one person.

        FUB documents restrictions around appointment ownership, calendar sharing, and
        appointments synced from third-party calendars.
        """
        return await self._get(
            "/appointments",
            params={
                "personId": person_id,
                "limit": min(max(limit, 1), 100),
                "offset": max(offset, 0),
            },
        )

    async def get_open_tasks(self, person_id: int) -> dict[str, Any]:
        return await self._get("/tasks", params={"personId": person_id, "isCompleted": "false"})

    async def get_stages(self) -> dict[str, Any]:
        return await self._get("/stages", params={"limit": 100, "sort": "orderWeight"})

    async def get_deals(self, person_id: int) -> dict[str, Any]:
        return await self._get("/deals", params={"personId": person_id, "status": "Active"})
