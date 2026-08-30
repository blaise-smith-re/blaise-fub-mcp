"""An in-memory stand-in for FUBClient used across the test suite.

No network access, no real credentials. Supports injectable failure modes
(create failures, read-back failures/corruption) so the write-safety tests
can exercise real failure paths instead of only the happy path.
"""

from __future__ import annotations

from typing import Any

from fub_client import FUBClient


class FakeFUBClient:
    def __init__(self) -> None:
        self.people: dict[int, dict[str, Any]] = {}
        self.notes: dict[int, dict[str, Any]] = {}
        self.tasks: dict[int, dict[str, Any]] = {}
        self._task_order: list[int] = []
        self.users: dict[int, dict[str, Any]] = {}
        self.events: dict[int, list[dict[str, Any]]] = {}

        self._next_note_id = 9000
        self._next_task_id = 9500

        self.create_note_calls = 0
        self.create_task_calls = 0

        # Failure injection knobs.
        self.fail_create_note = False
        self.fail_create_task = False
        self.fail_note_readback = False  # note is created but never shows up in get_notes
        self.fail_task_readback = False  # get_task raises after a successful create
        self.corrupt_note_readback = False  # get_notes returns altered content for the note
        self.corrupt_task_readback = False  # get_task returns altered content for the task

    # ---------- seeding helpers ----------
    def add_person(self, person_id: int, **fields: Any) -> dict[str, Any]:
        person = {"id": person_id, **fields}
        self.people[person_id] = person
        return person

    def add_user(self, user_id: int, **fields: Any) -> dict[str, Any]:
        user = {"id": user_id, **fields}
        self.users[user_id] = user
        return user

    def add_task(self, task_id: int, **fields: Any) -> dict[str, Any]:
        task = {"id": task_id, "isCompleted": False, **fields}
        if task_id not in self.tasks:
            self._task_order.append(task_id)
        self.tasks[task_id] = task
        return task

    def add_note(self, note_id: int, **fields: Any) -> dict[str, Any]:
        note = {"id": note_id, **fields}
        self.notes[note_id] = note
        return note

    # ---------- FUBClient-compatible surface ----------
    async def get_person(self, person_id: int) -> dict[str, Any]:
        if person_id not in self.people:
            raise ValueError(f"person {person_id} not found")
        return dict(self.people[person_id])

    async def get_notes(self, person_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        notes = [
            dict(n) for n in self.notes.values() if n["personId"] == person_id and not n.get("_hidden_from_readback")
        ]
        if self.corrupt_note_readback:
            notes = [{**n, "body": str(n.get("body", "")) + " [UNEXPECTED SERVER EDIT]"} for n in notes]
        return {"notes": notes}

    async def create_note(self, person_id: int, subject: str, body: str) -> dict[str, Any]:
        self.create_note_calls += 1
        if self.fail_create_note:
            raise RuntimeError("simulated FUB API failure creating note")
        note_id = self._next_note_id
        self._next_note_id += 1
        note = {
            "id": note_id,
            "personId": person_id,
            "subject": subject,
            "body": body,
            "created": "2026-08-29T12:00:00Z",
            "_hidden_from_readback": self.fail_note_readback,
        }
        self.notes[note_id] = note
        return {"id": note_id, "personId": person_id, "subject": subject, "body": body}

    async def search_tasks(self, **params: Any) -> dict[str, Any]:
        # Insertion order, not dict-hash order, so paging is deterministic and
        # comparable to a stable real-API ordering across repeated calls.
        tasks = [dict(self.tasks[k]) for k in self._task_order if k in self.tasks]
        if params.get("personId") is not None:
            tasks = [t for t in tasks if t["personId"] == params["personId"]]
        if params.get("assignedUserId") is not None:
            tasks = [t for t in tasks if t.get("assignedUserId") == params["assignedUserId"]]
        if params.get("type") is not None:
            tasks = [t for t in tasks if t.get("type") == params["type"]]
        if params.get("isCompleted") is not None:
            tasks = [t for t in tasks if bool(t.get("isCompleted")) == bool(params["isCompleted"])]
        total = len(tasks)
        offset = int(params.get("offset") or 0)
        limit = params.get("limit")
        page = tasks[offset : offset + int(limit)] if limit is not None else tasks[offset:]
        return {"tasks": page, "_metadata": {"total": total, "offset": offset, "limit": limit}}

    async def search_tasks_all(self, **params: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        # Exercises the real pagination/dedup/cap algorithm against this fake's
        # own (paginating) search_tasks, rather than reimplementing it, so the
        # tests cover the actual production logic.
        return await FUBClient.search_tasks_all(self, **params)  # type: ignore[arg-type]

    async def get_task(self, task_id: int) -> dict[str, Any]:
        if self.fail_task_readback:
            raise RuntimeError("simulated FUB API failure reading back task")
        if task_id not in self.tasks:
            raise ValueError(f"task {task_id} not found")
        task = dict(self.tasks[task_id])
        if self.corrupt_task_readback:
            task["name"] = str(task.get("name", "")) + " [UNEXPECTED SERVER EDIT]"
        return task

    async def create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        self.create_task_calls += 1
        if self.fail_create_task:
            raise RuntimeError("simulated FUB API failure creating task")
        task_id = self._next_task_id
        self._next_task_id += 1
        task = dict(body)
        task["id"] = task_id
        self.tasks[task_id] = task
        self._task_order.append(task_id)
        return dict(task)

    async def get_user(self, user_id: int) -> dict[str, Any]:
        if user_id not in self.users:
            raise ValueError(f"user {user_id} not found")
        return dict(self.users[user_id])

    async def get_events(self, person_id: int, limit: int = 50, next_token: str | None = None) -> dict[str, Any]:
        return {"events": self.events.get(person_id, [])}
