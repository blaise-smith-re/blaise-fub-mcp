from __future__ import annotations

import inspect
import os

import pytest

os.environ.setdefault("AUTH0_DOMAIN", "tenant.example")
os.environ.setdefault("MCP_PUBLIC_URL", "https://readonly.example")

import readonly_server


class ReadFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get_person(self, person_id: int):
        self.calls.append(("get_person", {"person_id": person_id}))
        return {"id": person_id, "stage": "Synthetic Active"}

    async def get_events(self, person_id: int, *, limit: int, next_token: str | None):
        self.calls.append(("get_events", {"person_id": person_id, "limit": limit, "next_token": next_token}))
        return {"events": [{"id": 98001, "personId": person_id}]}

    async def get_notes(self, person_id: int, *, limit: int, offset: int):
        self.calls.append(("get_notes", {"person_id": person_id, "limit": limit, "offset": offset}))
        return {"notes": [{"id": 97001, "personId": person_id}], "_metadata": {"total": 1}}

    async def search_appointments(self, **params):
        self.calls.append(("search_appointments", params))
        return {"appointments": [{"id": 96001, "personId": params["personId"]}]}

    async def search_tasks_all(self, **params):
        self.calls.append(("search_tasks_all", params))
        tasks = [
            {"id": 99001, "personId": 90001, "dueDate": "2026-09-03"},
            {"id": 99002, "personId": 90001, "dueDate": "2026-09-04"},
        ]
        return tasks, {
            "returned_count": 2,
            "total_count": 2,
            "has_more": False,
            "capped": False,
            "pages_fetched": 1,
        }


@pytest.fixture
def fake(monkeypatch):
    client = ReadFake()
    monkeypatch.setattr(readonly_server, "_client", lambda: client)
    return client


def test_exact_six_tool_inventory_and_read_scope_only():
    assert readonly_server.READ_TOOL_NAMES == (
        "get_contact",
        "get_contact_events",
        "get_contact_notes",
        "get_contact_appointments",
        "search_tasks",
        "get_open_tasks",
    )
    assert readonly_server.REQUIRED_SCOPES == ("fub:read",)
    registered = {tool.name for tool in readonly_server.mcp._tool_manager.list_tools()}
    assert registered == set(readonly_server.READ_TOOL_NAMES)
    source = inspect.getsource(readonly_server)
    for forbidden in ("_post(", "_put(", "_delete(", "fub:write", "execute=True"):
        assert forbidden not in source


def test_auth0_verifier_supports_explicit_shared_audience(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "tenant.example")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://readonly.example")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://operator.example/mcp")
    verifier = readonly_server.Auth0TokenVerifier()
    assert verifier.audience == "https://operator.example/mcp"


async def test_exact_contact_and_bounded_history_reads(fake):
    assert (await readonly_server.get_contact(90001))["id"] == 90001
    assert len((await readonly_server.get_contact_events(90001))["events"]) == 1
    assert len((await readonly_server.get_contact_notes(90001))["notes"]) == 1
    assert len((await readonly_server.get_contact_appointments(90001))["appointments"]) == 1
    assert {call[0] for call in fake.calls} == {
        "get_person",
        "get_events",
        "get_notes",
        "search_appointments",
    }


async def test_task_search_is_complete_chicago_anchored_and_date_bounded(fake):
    result = await readonly_server.search_tasks(
        assigned_user_id=70001,
        is_completed=False,
        due_on="2026-09-03",
    )
    assert [task["id"] for task in result["tasks"]] == [99001]
    assert result["_completeness"]["returned_count"] == result["_completeness"]["total_count"] == 2
    assert result["due_date_filter"]["timezone"] == "America/Chicago"
    assert fake.calls[-1] == (
        "search_tasks_all",
        {"personId": None, "assignedUserId": 70001, "type": None, "isCompleted": False},
    )


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"due_on": "2026-09-03"}, "person_id or assigned_user_id"),
        ({"assigned_user_id": 70001}, "due_on"),
        ({"assigned_user_id": 70001, "due_on": "2026-09-03", "fetch_all": False}, "Partial"),
        ({"assigned_user_id": 70001, "due_on": "2026-09-03", "limit": 25}, "Partial"),
        (
            {"assigned_user_id": 70001, "due_on": "2026-09-03", "due_timezone": "UTC"},
            "America/Chicago",
        ),
    ],
)
async def test_task_search_refuses_degraded_scope(fake, kwargs, match):
    with pytest.raises(ValueError, match=match):
        await readonly_server.search_tasks(**kwargs)
    assert fake.calls == []


async def test_open_tasks_always_returns_completeness(fake):
    result = await readonly_server.get_open_tasks(90001)
    assert result["_metadata"]["total"] == 2
    assert result["_completeness"] == {
        "returned_count": 2,
        "total_count": 2,
        "has_more": False,
        "capped": False,
        "pages_fetched": 1,
    }


@pytest.mark.parametrize("value", [0, -1, True])
async def test_exact_id_reads_reject_non_positive_or_boolean_ids(fake, value):
    with pytest.raises(ValueError, match="positive integer"):
        await readonly_server.get_contact(value)
    assert fake.calls == []
