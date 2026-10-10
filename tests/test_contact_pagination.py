"""Bounded, scoped contact discovery across FUB cursor pages; no network."""

from __future__ import annotations

import pytest

import server
from fub_client import FUBClient


async def test_cursor_reaches_contacts_beyond_first_page_without_widening_scope(monkeypatch):
    client = FUBClient()
    requests = []

    async def get_page(path, params):
        requests.append((path, params.copy()))
        assert path == "/people"
        assert params["assignedUserId"] == 33
        assert params["stage"] == "Lead"
        assert params["limit"] == 25
        if "next" not in params:
            return {"people": [{"id": n} for n in range(1, 26)], "_metadata": {"total": 29, "next": "page-two"}}
        assert params["next"] == "page-two"
        return {"people": [{"id": n} for n in range(26, 30)], "_metadata": {"total": 29, "next": None}}

    monkeypatch.setattr(client, "_get", get_page)
    monkeypatch.setattr(server, "_client", lambda: client)
    first = await server.find_contact(assigned_user_id=33, stage="Lead", limit=100)
    assert len(requests) == 1  # No hidden automatic account sweep.
    second = await server.find_contact(
        assigned_user_id=33, stage="Lead", limit=100, next_token=first["_metadata"]["next"]
    )
    assert [person["id"] for person in first["people"] + second["people"]] == list(range(1, 30))
    assert second["_metadata"]["next"] is None
    assert len(requests) == 2
    assert requests[0][1]["fields"] == requests[1][1]["fields"]


@pytest.mark.parametrize("criteria", [{}, {"next_token": "page-two"}, {"name": "   "}])
async def test_search_controls_alone_do_not_authorize_an_unscoped_read(monkeypatch, criteria):
    monkeypatch.setattr(server, "_client", lambda: pytest.fail("Must reject before client access"))
    with pytest.raises(ValueError, match="search criterion"):
        await server.find_contact(**criteria)


async def test_exact_search_remains_backwards_compatible(monkeypatch):
    class Client:
        async def find_people(self, **params):
            assert params["email"] == "synthetic@example.test"
            assert params["limit"] == 10
            assert "next" not in params
            return {"people": [{"id": 1}], "_metadata": {"total": 1}}

    monkeypatch.setattr(server, "_client", Client)
    assert (await server.find_contact(email="synthetic@example.test"))["people"] == [{"id": 1}]


async def test_registered_tool_exposes_optional_cursor_and_preserves_tool_name():
    tools = await server.mcp.list_tools()
    tool = next(tool for tool in tools if tool.name == "find_contact")
    assert "next_token" in tool.inputSchema["properties"]
    assert "next_token" not in tool.inputSchema.get("required", [])
