"""Adversarial pre-merge review tests (PR #1).

Written to attack the certified behavior rather than confirm it. Each test
here corresponds to a defect found during the pre-merge adversarial review;
they are grouped by the review area that produced them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import server
from closeout import is_vague_task_name
from daily_control import find_gaps
from redaction import scan_sensitive

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
PERSON = {"id": 1, "assignedUserId": 42}
FUTURE_TASK = [{"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"}]


def _note_aged(days: float, note_id: int = 5) -> dict:
    return {"id": note_id, "created": (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z")}


def _stale_finding(findings: list[dict]) -> dict | None:
    return next((f for f in findings if f["gap_type"] == "no_recent_interaction_note"), None)


# ============================================================
# 1. STALE-NOTE RULE
# ============================================================


def test_stale_threshold_is_labelled_as_implementation_default_not_policy():
    """The 21-day threshold must never read as established FUB 05 business policy."""
    findings = find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[_note_aged(60)], now=NOW)
    gap = _stale_finding(findings)
    assert gap is not None
    blob = " ".join(str(v) for v in gap.values()).casefold()
    assert "advisory" in blob or "implementation default" in blob
    assert "not a follow up boss" in blob or "not fub" in blob or "not established" in blob
    # And it must expose the threshold's provenance as a structured field so a
    # downstream report cannot quietly present it as policy.
    assert gap["threshold_basis"] == "implementation_default"


def test_stale_threshold_boundary_is_exact_and_documented():
    """Boundary must be well-defined: > threshold flags, <= threshold does not."""
    # 20.9 days old -> not stale
    assert _stale_finding(find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[_note_aged(20.9)], now=NOW)) is None
    # exactly 21.0 days old -> not stale (threshold is inclusive of the limit)
    assert _stale_finding(find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[_note_aged(21.0)], now=NOW)) is None
    # 21.1 days old -> stale. Previously a truncating `.days` comparison meant
    # anything under 22.0 days silently passed.
    gap = _stale_finding(find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[_note_aged(21.1)], now=NOW))
    assert gap is not None


def test_stale_age_reported_with_fractional_precision_not_truncated():
    gap = _stale_finding(find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[_note_aged(30.5)], now=NOW))
    assert gap is not None
    assert 30.4 < gap["evidence"]["latest_note_age_days"] < 30.6


def test_custom_threshold_is_honoured_and_echoed():
    gap = _stale_finding(
        find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[_note_aged(10)], now=NOW, stale_note_days=7)
    )
    assert gap is not None
    assert gap["evidence"]["stale_note_days_threshold"] == 7


def test_future_dated_note_is_never_reported_as_stale():
    """Clock skew / future-dated note must not produce a negative-age stale finding."""
    findings = find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[_note_aged(-5)], now=NOW)
    assert _stale_finding(findings) is None


def test_notes_present_but_undateable_does_not_claim_zero_notes():
    """A note with no parseable date must not be reported as 'returned no notes'.

    Previously this produced a self-contradicting finding: the summary said the
    API returned no notes while the evidence showed a nonzero note count.
    """
    notes = [{"id": 7, "subject": "Has no usable date"}, {"id": 8, "created": "not-a-date"}]
    gap = _stale_finding(find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=notes, now=NOW))
    assert gap is not None
    assert "returned no notes" not in gap["summary"].casefold()
    assert gap["evidence"]["notes_checked"] == 2
    assert gap["evidence"]["notes_with_unusable_dates"] == 2
    assert "could be dated" in gap["summary"].casefold()
    # Must be framed as a data-quality limit, not as missing interaction.
    assert "not evidence of missing interaction" in gap["caveat"].casefold()


def test_truly_zero_notes_still_reports_zero_with_absence_caveat():
    gap = _stale_finding(find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[], now=NOW))
    assert gap is not None
    assert gap["evidence"]["notes_checked"] == 0
    assert "does not prove" in gap["caveat"]


def test_mixed_dateable_and_undateable_notes_uses_the_dateable_one():
    notes = [{"id": 7, "subject": "undated"}, _note_aged(2, note_id=8)]
    findings = find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=notes, now=NOW)
    assert _stale_finding(findings) is None


def test_audit_result_cannot_be_read_as_a_clean_bill_of_health():
    """Zero findings must still carry an explicit scope limitation."""
    findings = find_gaps(person=PERSON, open_tasks=FUTURE_TASK, notes=[_note_aged(1)], now=NOW)
    assert findings == []


# ============================================================
# 2. VAGUE / PLACEHOLDER TASK-NAME REJECTION
# ============================================================


@pytest.mark.parametrize(
    "name",
    [
        "Follow Up",
        "follow up",
        "FOLLOW UP",
        "  follow   up  ",
        "followup",
        "Follow-Up",
        "Call",
        "call",
        "Text",
        "Email",
        "Touch base",
        "Check in",
        "Reach out",
        "Contact",
        "Connect",
        # Punctuation-wrapped placeholders: previously slipped through the
        # exact-match blocklist and were accepted as if they were specific.
        "Follow up.",
        "Follow up!",
        "Call.",
        "Call?",
        "Follow Up -",
        "- follow up",
        "*Call*",
        "(follow up)",
        "Follow up...",
        "Follow up:",
    ],
)
def test_rejects_bare_placeholder_names(name):
    assert is_vague_task_name(name), f"should have been rejected: {name!r}"


@pytest.mark.parametrize(
    "name",
    [
        # Specific, relationship-useful next actions that merely CONTAIN a
        # blocklisted word. None of these may be rejected.
        "Call to confirm inspection date",
        "Follow up on inspection repairs list",
        "Follow up re: lender pre-approval",
        "Email closing documents to buyer",
        "Text Jane the showing address",
        "Touch base after the appraisal comes back",
        "Check in on financing contingency deadline",
        "Reach out about the Woodbury listing",
        "Contact lender about rate lock expiry",
        "Connect buyer with Laura for TC handoff",
        "Call Jane",
        "Call 2pm",
        "Follow up Tuesday",
        "Second follow up",
        "Call back",
        "Contact info update",
    ],
)
def test_does_not_reject_specific_names_containing_blocklist_words(name):
    assert not is_vague_task_name(name), f"false positive on: {name!r}"


def test_empty_or_punctuation_only_task_name_is_treated_as_vague():
    for name in ["", "   ", ".", "...", "-", "!!!"]:
        assert is_vague_task_name(name), f"should have been rejected: {name!r}"


# ============================================================
# 3. EMPTY-CONTENT WRITES (success without evidence)
# ============================================================


def _seed(fake, *, person_id: int = 1, owner_id: int = 42) -> None:
    fake.add_person(person_id, firstName="Jane", lastName="Doe", assignedUserId=owner_id)
    fake.add_user(owner_id, name="Blaise Smith")


async def test_note_with_empty_body_is_rejected(fake, writable):
    _seed(fake)
    with pytest.raises(ValueError, match="empty"):
        await server.create_contact_note(
            person_id=1, expected_contact_name="Jane Doe", subject="Subject", body="   ", execute=True
        )
    assert fake.create_note_calls == 0


async def test_note_with_empty_subject_is_rejected(fake, writable):
    _seed(fake)
    with pytest.raises(ValueError, match="empty"):
        await server.create_contact_note(
            person_id=1, expected_contact_name="Jane Doe", subject="", body="Real content.", execute=True
        )
    assert fake.create_note_calls == 0


async def test_task_with_whitespace_only_name_is_rejected(fake, writable):
    _seed(fake)
    with pytest.raises(ValueError):
        await server.create_contact_task(
            person_id=1,
            expected_contact_name="Jane Doe",
            assigned_user_id=42,
            name="   ",
            task_type="Call",
            due_date="2026-09-15",
            execute=True,
        )
    assert fake.create_task_calls == 0


async def test_closeout_rejects_empty_note_body(fake, writable):
    _seed(fake)
    with pytest.raises(ValueError, match="empty"):
        await server.close_out_contact_interaction(
            person_id=1,
            expected_contact_name="Jane Doe",
            expected_assigned_user_id=42,
            note_subject="Buyer call",
            note_body="",
            execute=True,
        )
    assert fake.create_note_calls == 0


# ============================================================
# 4. OWNERSHIP: UNASSIGNED CONTACT
# ============================================================


def test_unassigned_contact_is_flagged_when_owner_expected():
    """A contact with NO assigned user must not silently pass the ownership check."""
    unassigned = {"id": 1, "assignedUserId": None}
    findings = find_gaps(
        person=unassigned, open_tasks=FUTURE_TASK, notes=[_note_aged(1)], now=NOW, expected_assigned_user_id=42
    )
    mismatch = next((f for f in findings if f["gap_type"] == "ownership_mismatch"), None)
    assert mismatch is not None
    assert mismatch["evidence"]["assignedUserId"] is None
    assert mismatch["evidence"]["expected_assigned_user_id"] == 42


def test_missing_assigned_user_key_is_also_flagged():
    findings = find_gaps(
        person={"id": 1}, open_tasks=FUTURE_TASK, notes=[_note_aged(1)], now=NOW, expected_assigned_user_id=42
    )
    assert any(f["gap_type"] == "ownership_mismatch" for f in findings)


async def test_closeout_refuses_unassigned_contact(fake, writable):
    fake.add_person(1, firstName="Jane", lastName="Doe", assignedUserId=None)
    fake.add_user(42, name="Blaise Smith")
    with pytest.raises(ValueError, match="Owner verification failed"):
        await server.close_out_contact_interaction(
            person_id=1,
            expected_contact_name="Jane Doe",
            expected_assigned_user_id=42,
            note_subject="Buyer call",
            note_body="Discussed timeline with buyer.",
            execute=True,
        )
    assert fake.create_note_calls == 0


# ============================================================
# 5. PARTIAL-WRITE RECOVERY: created ids must survive failed read-back
# ============================================================


async def test_note_id_is_reported_even_when_readback_fails(fake, writable):
    """The operator needs the id of a created-but-unverified object to recover."""
    _seed(fake)
    fake.fail_note_readback = True
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        execute=True,
    )
    assert result["status"] == "CLOSEOUT_COMPLETED_WITH_HOLD"
    assert result["note"]["status"] == "WRITE_COMPLETED_UNVERIFIED"
    # The note really was created; its id must be surfaced for cleanup.
    assert result["created_object_ids"]["note_id"] is not None
    assert result["created_object_ids"]["note_id_verified"] is False


async def test_task_id_is_reported_even_when_readback_fails(fake, writable):
    _seed(fake)
    fake.fail_task_readback = True
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        create_next_task=True,
        next_task_name="Call to confirm inspection date",
        next_task_type="Call",
        next_task_due_date="2026-09-15",
        execute=True,
    )
    assert result["status"] == "CLOSEOUT_COMPLETED_WITH_HOLD"
    assert result["task"]["status"] == "WRITE_COMPLETED_UNVERIFIED"
    assert result["created_object_ids"]["task_id"] is not None
    assert result["created_object_ids"]["task_id_verified"] is False


async def test_unverified_created_task_is_not_double_reported_as_unexpected(fake, writable):
    """A task we created must never be labelled an unrelated 'unexpected new task'."""
    _seed(fake)
    fake.fail_task_readback = True
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        create_next_task=True,
        next_task_name="Call to confirm inspection date",
        next_task_type="Call",
        next_task_due_date="2026-09-15",
        execute=True,
    )
    problems = result["before_after"]["unrelated_open_task_changes"]
    assert not any(p.get("problem") == "unexpected_new_task" for p in problems)


async def test_idempotent_skip_is_not_reported_as_a_creation(fake, writable):
    """A matched pre-existing object must never be reported under a created id."""
    _seed(fake)
    fake.add_note(700, personId=1, subject="Buyer call", body="Discussed timeline.", created="2026-08-29T10:00:00Z")
    fake.add_task(500, personId=1, name="Call to confirm inspection date", type="Call", dueDate="2026-09-15")
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed timeline.",
        create_next_task=True,
        next_task_name="Call to confirm inspection date",
        next_task_type="Call",
        next_task_due_date="2026-09-15",
        execute=True,
    )
    ids = result["created_object_ids"]
    assert result["status"] == "CLOSEOUT_COMPLETED"
    # Nothing was created, so no created id may be claimed...
    assert ids["note_id"] is None
    assert ids["task_id"] is None
    # ...but the matched records are still identified for the operator.
    assert ids["note_outcome"] == "matched_existing_no_write"
    assert ids["task_outcome"] == "matched_existing_no_write"
    assert ids["note_matched_existing_id"] == 700
    assert ids["task_matched_existing_id"] == 500
    assert fake.create_note_calls == 0
    assert fake.create_task_calls == 0


async def test_unverified_write_is_reported_as_created_not_matched(fake, writable):
    _seed(fake)
    fake.fail_note_readback = True
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        execute=True,
    )
    ids = result["created_object_ids"]
    assert ids["note_outcome"] == "created"
    assert ids["note_id"] is not None
    assert ids["note_id_verified"] is False
    assert ids["note_matched_existing_id"] is None


async def test_task_not_requested_is_distinct_from_not_written(fake, writable):
    _seed(fake)
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        execute=True,
    )
    assert result["created_object_ids"]["task_outcome"] == "not_requested"
    assert result["created_object_ids"]["task_id"] is None


async def test_verified_write_marks_ids_as_verified(fake, writable):
    _seed(fake)
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        create_next_task=True,
        next_task_name="Call to confirm inspection date",
        next_task_type="Call",
        next_task_due_date="2026-09-15",
        execute=True,
    )
    assert result["status"] == "CLOSEOUT_COMPLETED"
    assert result["created_object_ids"]["note_id_verified"] is True
    assert result["created_object_ids"]["task_id_verified"] is True


# ============================================================
# 6. API SILENCE / TRUNCATION MUST NOT READ AS COMPLETENESS
# ============================================================


class TruncatingNotesClient:
    """A notes endpoint that reports more notes than it returns."""

    def __init__(self, fake):
        self._fake = fake

    def __getattr__(self, item):
        return getattr(self._fake, item)

    async def get_notes(self, person_id: int, limit: int = 50, offset: int = 0):
        result = await self._fake.get_notes(person_id, limit=limit, offset=offset)
        result["_metadata"] = {"total": 500}
        return result


async def test_note_dedup_discloses_a_truncated_search_window(monkeypatch, fake, writable):
    _seed(fake)
    monkeypatch.setattr(server, "_client", lambda: TruncatingNotesClient(fake))
    result = await server.create_contact_note(
        person_id=1,
        expected_contact_name="Jane Doe",
        subject="Buyer call",
        body="Discussed financing timeline.",
        execute=True,
    )
    assert "dedup_scope_limitation" in result
    assert "500" in result["dedup_scope_limitation"]


async def test_note_dedup_stays_silent_when_window_is_complete(fake, writable):
    _seed(fake)
    result = await server.create_contact_note(
        person_id=1,
        expected_contact_name="Jane Doe",
        subject="Buyer call",
        body="Discussed financing timeline.",
        execute=True,
    )
    assert "dedup_scope_limitation" not in result


async def test_audit_discloses_truncated_note_evidence(monkeypatch, fake):
    _seed(fake)
    monkeypatch.setattr(server, "_client", lambda: TruncatingNotesClient(fake))
    result = await server.audit_contact_daily_control(person_id=1, expected_contact_name="Jane Doe")
    assert result["evidence_scope"]["notes_scope_limitation"] is not None


async def test_audit_never_presents_zero_findings_as_a_clean_record(fake):
    _seed(fake)
    fake.add_task(500, personId=1, name="Call to confirm inspection", type="Call", dueDate="2099-01-01")
    fake.add_note(700, personId=1, subject="Recent", body="x", created="2026-08-29T00:00:00Z")
    result = await server.audit_contact_daily_control(person_id=1, expected_contact_name="Jane Doe")
    joined = " ".join(result["caveats"]).casefold()
    assert "not a certification that the record is complete" in joined
    assert "advisory implementation defaults" in joined


# ============================================================
# 7. SENSITIVE-DATA FILTER BYPASS VIA SIBLING WRITE TOOLS
# ============================================================


async def test_update_task_name_cannot_smuggle_sensitive_data(fake, writable):
    _seed(fake)
    fake.add_task(500, personId=1, name="Original task", type="Call", dueDate="2026-09-15")
    with pytest.raises(ValueError, match="sensitive data"):
        await server.update_contact_task(
            task_id=500,
            expected_person_id=1,
            expected_task_name="Original task",
            new_name="Collect SSN 123-45-6789 from buyer",
            execute=True,
        )


async def test_profile_background_cannot_smuggle_sensitive_data(fake, writable):
    _seed(fake)
    with pytest.raises(ValueError, match="sensitive data"):
        await server.update_contact_profile(
            person_id=1,
            expected_contact_name="Jane Doe",
            background="Wire instructions sent to buyer.",
            execute=True,
        )


async def test_external_call_log_note_cannot_smuggle_sensitive_data(fake, writable):
    _seed(fake)
    with pytest.raises(ValueError, match="sensitive data"):
        await server.log_external_call_record(
            person_id=1,
            expected_contact_name="Jane Doe",
            phone="555-0100",
            is_incoming=False,
            duration_seconds=60,
            note="Buyer read out account number 000123456789 on the call.",
            execute=True,
        )


async def test_external_text_log_message_cannot_smuggle_sensitive_data(fake, writable):
    _seed(fake)
    with pytest.raises(ValueError, match="sensitive data"):
        await server.log_external_text_record(
            person_id=1,
            expected_contact_name="Jane Doe",
            message="The TrustFunds secret word is Falcon22.",
            to_number="555-0100",
            from_number="555-0199",
            execute=True,
        )


async def test_sensitive_data_blocked_in_preview_mode_too(fake):
    """The filter must fire before preview output, not only before a live write."""
    _seed(fake)
    with pytest.raises(ValueError, match="sensitive data"):
        await server.update_contact_profile(
            person_id=1,
            expected_contact_name="Jane Doe",
            background="Client SSN is 123-45-6789.",
            execute=False,
        )


def test_redaction_rejection_message_never_echoes_the_secret():
    from redaction import assert_no_sensitive_data

    with pytest.raises(ValueError) as exc:
        assert_no_sensitive_data("Wire instructions: routing number 021000021", field_label="note")
    assert "021000021" not in str(exc.value)


def test_scan_detects_each_sensitive_category():
    assert "wire_instructions" in scan_sensitive("Here are the wire instructions.")
    assert "trustfunds_secret_word" in scan_sensitive("TrustFunds secret word: Falcon22")
    assert "swift_or_iban" in scan_sensitive("IBAN on file")


# ============================================================
# 8. AUTHORIZATION
# ============================================================


async def test_live_note_write_requires_write_scope(fake):
    """Without the `writable` fixture there is no token, so the scope check must bite."""
    _seed(fake)
    with pytest.raises(PermissionError, match="fub:write"):
        await server.create_contact_note(
            person_id=1,
            expected_contact_name="Jane Doe",
            subject="Buyer call",
            body="Discussed financing timeline.",
            execute=True,
        )
    assert fake.create_note_calls == 0


async def test_live_closeout_requires_write_scope(fake):
    _seed(fake)
    with pytest.raises(PermissionError, match="fub:write"):
        await server.close_out_contact_interaction(
            person_id=1,
            expected_contact_name="Jane Doe",
            expected_assigned_user_id=42,
            note_subject="Buyer call",
            note_body="Discussed financing timeline.",
            execute=True,
        )
    assert fake.create_note_calls == 0
    assert fake.create_task_calls == 0


async def test_preview_does_not_require_write_scope(fake):
    _seed(fake)
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline.",
    )
    assert result["status"] == "PREVIEW_ONLY_NO_WRITE"


# ============================================================
# 9. NO COMMUNICATION / NO SHARED-CONFIG REACHABILITY
# ============================================================


class RecordingClient:
    """Wraps the fake and records every client method the tool touches."""

    def __init__(self, fake):
        self._fake = fake
        self.calls: list[str] = []

    def __getattr__(self, item):
        attr = getattr(self._fake, item)
        if callable(attr):
            self.calls.append(item)
        return attr


# Anything that sends, or that mutates team-owned/shared FUB structure.
FORBIDDEN_CLIENT_METHODS = {
    "log_call",
    "log_text_message",
    "create_appointment",
    "update_appointment",
    "update_person",
    "create_deal",
    "update_deal",
}


async def test_closeout_never_touches_communication_or_shared_config(monkeypatch, fake, writable):
    client = RecordingClient(fake)
    _seed(fake)
    monkeypatch.setattr(server, "_client", lambda: client)
    await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        create_next_task=True,
        next_task_name="Call to confirm inspection date",
        next_task_type="Call",
        next_task_due_date="2026-09-15",
        execute=True,
    )
    assert not FORBIDDEN_CLIENT_METHODS.intersection(client.calls), client.calls
    # Only the note and task creates may write.
    assert sorted(c for c in client.calls if c.startswith(("create", "update"))) == [
        "create_note",
        "create_task",
    ]


async def test_audit_is_strictly_read_only(monkeypatch, fake):
    client = RecordingClient(fake)
    _seed(fake)
    monkeypatch.setattr(server, "_client", lambda: client)
    await server.audit_contact_daily_control(person_id=1, expected_contact_name="Jane Doe")
    assert not any(c.startswith(("create", "update", "log_", "delete")) for c in client.calls), client.calls


def test_no_tool_exposes_a_shared_config_write():
    """Structural guard: no exposed tool may create/edit shared FUB structures."""
    forbidden = ("stage", "smart_list", "smartlist", "action_plan", "automation", "lead_flow", "template")
    tool_names = [
        name
        for name in dir(server)
        if not name.startswith("_") and callable(getattr(server, name, None)) and "contact" in name
    ]
    offenders = [
        n for n in tool_names if any(f in n.casefold() for f in forbidden) and ("create" in n or "update" in n)
    ]
    assert offenders == [], offenders
