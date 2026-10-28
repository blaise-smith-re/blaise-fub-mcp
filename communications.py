"""Truthful, read-only communication coverage; no sending, writes, or persistence."""

from __future__ import annotations

from typing import Any


def body_visibility(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unavailable"
    text = value.strip().casefold()
    if "hidden for privacy" in text or text in {"[redacted]", "* redacted *", "[hidden]"}:
        return "restricted"
    return "readable"


def text_coverage(messages: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"readable": 0, "restricted": 0, "unavailable": 0}
    directions: dict[str, dict[str, int]] = {
        "incoming": dict(counts),
        "outgoing": dict(counts),
        "unknown": dict(counts),
    }
    for message in messages:
        state = body_visibility(message.get("message"))
        counts[state] += 1
        direction = (
            "incoming"
            if message.get("isIncoming") is True
            else ("outgoing" if message.get("isIncoming") is False else "unknown")
        )
        directions[direction][state] += 1
    return {
        "bodies": counts,
        "by_direction": directions,
        "full_communication_history": False,
        "api_exhaustion_does_not_establish_full_history": True,
        "restriction": (
            "FUB restricts some SMS data to its application. Metadata, sent/delivery status "
            "and counters do not establish readable content or absence of another touch."
        ),
        "other_sources": {
            "emails": "Read relevant original connected Gmail threads, including SENT/DRAFT labels and attachments.",
            "personal_phone": (
                "Unavailable unless explicitly shared or an authorized personal-message source is connected."
            ),
        },
    }


def latest_communication(person: dict[str, Any], person_id: int) -> dict[str, Any] | None:
    if person.get("id") != person_id:
        raise ValueError("Latest communication person ID mismatch.")
    latest = person.get("lastCommunication")
    if not isinstance(latest, dict) or not latest:
        return None
    state = body_visibility(latest.get("content"))
    result = {
        "id": latest.get("id"),
        "date": latest.get("date"),
        "type": latest.get("type"),
        "direction": latest.get("direction"),
        "body_visibility": state,
        "source": "person.lastCommunication",
        "coverage": "latest_field_only; not a complete thread or guaranteed untruncated body",
    }
    if state == "readable":
        result["content"] = latest["content"]
    return result


def call_coverage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "returned_count": len(calls),
        "readable_log_notes": sum(body_visibility(c.get("note")) == "readable" for c in calls),
        "notes_explicitly_say_not_a_phone_call": sum(
            "not a phone call" in str(c.get("note", "")).casefold() for c in calls
        ),
        "recording_url_fields_present": sum(bool(c.get("recordingUrl")) for c in calls),
        "recordings_retrieved": False,
        "transcripts_retrieved": False,
        "full_communication_history": False,
        "interpretation": (
            "These are API-visible call logs and entered notes, not audio or verbatim transcripts. "
            "A call container may explicitly describe a personal text. Read its note; do not count it "
            "as a phone conversation. Missing API data does not prove no call occurred."
        ),
    }
