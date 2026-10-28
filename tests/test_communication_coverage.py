"""Real gap regressions using synthetic data; no live client or network effects."""

from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

import server
from communications import body_visibility, call_coverage, latest_communication, text_coverage
from fub_client import FUBClient


def hidden(message_id: int, incoming: bool = False) -> dict:
    return {
        "id": message_id,
        "personId": 7,
        "isIncoming": incoming,
        "message": "* Body is hidden for privacy reasons *",
        "status": "Received" if incoming else "Sent",
    }


async def test_legacy_person_only_call_reads_beyond_ten_and_preserves_restriction(monkeypatch):
    client = FUBClient()
    requests = []

    async def get(path, params):
        requests.append((path, deepcopy(params)))
        assert path == "/textMessages" and params["personId"] == 7
        if "next" not in params:
            return {
                "textmessages": [hidden(i, i % 2 == 0) for i in range(1, 11)],
                "_metadata": {"total": 13, "limit": 10, "next": "older"},
            }
        assert params["next"] == "older"
        return {
            "textmessages": [hidden(i) for i in range(11, 14)],
            "_metadata": {"total": 13, "limit": 10, "next": None},
        }

    async def person(person_id):
        return {
            "id": person_id,
            "lastCommunication": {
                "id": 13,
                "type": "lastText",
                "direction": "outgoing",
                "date": "2026-01-02T15:00:00Z",
                "content": "We already discussed that; waiting for your answer.",
            },
        }

    monkeypatch.setattr(client, "_get", get)
    monkeypatch.setattr(client, "get_person", person)
    monkeypatch.setattr(server, "_client", lambda: client)
    result = await server.get_contact_text_messages(person_id=7)
    assert len(result["textmessages"]) == 13 and len(requests) == 2
    assert result["_completeness"]["api_pages_exhausted"] is True
    assert result["_coverage"]["bodies"] == {"readable": 0, "restricted": 13, "unavailable": 0}
    assert result["_coverage"]["full_communication_history"] is False
    assert result["latest_communication"]["content"].startswith("We already")
    assert result["latest_communication"]["coverage"].startswith("latest_field_only")
    assert result["textmessages"][0]["message"] == "* Body is hidden for privacy reasons *"


async def test_cursor_limit_failure_and_duplicate_pages_cannot_claim_complete(monkeypatch):
    client = FUBClient()
    requests = []

    async def page(person_id, limit=50, next_token=None):
        requests.append(next_token)
        return {"textmessages": [hidden(1)], "_metadata": {"total": 20, "next": "same"}}

    monkeypatch.setattr(client, "get_text_messages", page)
    result = await client.get_text_messages_all(7, max_pages=5)
    assert requests == [None, "same"]
    assert len(result["textmessages"]) == 1
    assert result["_completeness"]["complete"] is False
    assert result["_completeness"]["stop_reason"] == "repeated_cursor"
    assert result["_metadata"]["next"] == "same"


async def test_partial_http_failure_preserves_resume_without_echoing_request(monkeypatch):
    client = FUBClient()

    async def page(person_id, limit=50, next_token=None):
        if next_token:
            request = httpx.Request("GET", "https://api.example.invalid/private?credential=not-for-output")
            raise httpx.HTTPStatusError("do not echo this", request=request, response=httpx.Response(429))
        return {"textmessages": [hidden(1)], "_metadata": {"total": 2, "next": "resume"}}

    monkeypatch.setattr(client, "get_text_messages", page)
    result = await client.get_text_messages_all(7)
    assert result["_completeness"]["complete"] is False
    assert result["_completeness"]["error"] == "HTTP 429"
    assert result["_metadata"]["next"] == "resume"
    assert "credential" not in str(result)


async def test_page_cap_and_manual_resume_do_not_change_person_filter(monkeypatch):
    client = FUBClient()

    async def page(person_id, limit=50, next_token=None):
        assert person_id == 7 and limit == 10
        return {"textmessages": [hidden(1)], "_metadata": {"total": 99, "next": "next"}}

    monkeypatch.setattr(client, "get_text_messages", page)
    capped = await client.get_text_messages_all(7, limit=10, max_pages=1)
    assert capped["_completeness"]["stop_reason"] == "page_limit"
    assert capped["_completeness"]["complete"] is False
    assert capped["_metadata"]["next"] == "next"


@pytest.mark.parametrize("meta", [{}, {"total": 4}, {"total": 4, "next": None}])
async def test_missing_metadata_or_terminal_count_mismatch_is_incomplete(monkeypatch, meta):
    client = FUBClient()

    async def page(person_id, limit=50, next_token=None):
        return {"textmessages": [hidden(1)], "_metadata": meta}

    monkeypatch.setattr(client, "get_text_messages", page)
    result = await client.get_text_messages_all(7)
    assert result["_completeness"]["complete"] is False


async def test_first_page_error_is_not_an_empty_conversation(monkeypatch):
    client = FUBClient()

    async def page(*args, **kwargs):
        raise RuntimeError("not connected")

    monkeypatch.setattr(client, "get_text_messages", page)
    with pytest.raises(RuntimeError):
        await client.get_text_messages_all(7)


async def test_changed_totals_do_not_claim_a_consistent_snapshot(monkeypatch):
    client = FUBClient()

    async def page(person_id, limit=50, next_token=None):
        return {
            "textmessages": [hidden(2 if next_token else 1)],
            "_metadata": {"total": 3 if next_token else 2, "next": None if next_token else "older"},
        }

    monkeypatch.setattr(client, "get_text_messages", page)
    result = await client.get_text_messages_all(7)
    assert result["_completeness"]["api_pages_exhausted"] is True
    assert result["_completeness"]["complete"] is False
    assert result["_completeness"]["stop_reason"] == "total_changed"


async def test_latest_field_failure_preserves_visible_text_records(monkeypatch):
    client = FUBClient()

    async def page(person_id, limit=50, next_token=None):
        return {"textmessages": [hidden(1)], "_metadata": {"total": 1, "next": None}}

    async def person(person_id):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(client, "get_text_messages", page)
    monkeypatch.setattr(client, "get_person", person)
    monkeypatch.setattr(server, "_client", lambda: client)
    result = await server.get_contact_text_messages(7)
    assert len(result["textmessages"]) == 1
    assert result["_coverage"]["latest_field_status"] == "unavailable"
    assert "latest_communication" not in result


async def test_schema_backwards_compatible_and_no_new_tool_or_send_surface():
    tools = await server.mcp.list_tools()
    sms = next(t for t in tools if t.name == "get_contact_text_messages")
    assert sms.inputSchema["required"] == ["person_id"]
    assert {"limit", "next_token", "fetch_all", "max_pages"} <= sms.inputSchema["properties"].keys()
    assert "send_text" not in {t.name for t in tools}


def test_visibility_inbound_outbound_and_call_container_are_not_conflated():
    assert body_visibility(None) == "unavailable"
    assert body_visibility("* Body is hidden for privacy reasons *") == "restricted"
    cov = text_coverage([hidden(1), hidden(2, True), {"isIncoming": True, "message": "Actual reply"}])
    assert cov["by_direction"]["outgoing"]["restricted"] == 1
    assert cov["by_direction"]["incoming"]["readable"] == 1
    calls = call_coverage([{"note": "Personal text completed — not a phone call.", "duration": 0}])
    assert calls["notes_explicitly_say_not_a_phone_call"] == 1
    assert calls["recordings_retrieved"] is False


def test_latest_excerpt_requires_exact_person_and_does_not_unhide_body():
    with pytest.raises(ValueError, match="mismatch"):
        latest_communication({"id": 8}, 7)
    latest = latest_communication({"id": 7, "lastCommunication": {"content": "[REDACTED]"}}, 7)
    assert latest is not None
    assert latest["body_visibility"] == "restricted" and "content" not in latest


async def test_negative_person_rejected_before_any_access(monkeypatch):
    monkeypatch.setattr(server, "_client", lambda: pytest.fail("No unscoped read"))
    with pytest.raises(ValueError, match="positive"):
        await server.get_contact_text_messages(0)
