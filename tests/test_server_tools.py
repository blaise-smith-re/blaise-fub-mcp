"""Integration-level tests for the MCP tool functions in server.py.

Uses FakeFUBClient (no network, no real credentials) wired in via the
`fake` fixture (see conftest.py). The `writable` fixture bypasses the OAuth
fub:write scope check so execute=True paths can be exercised directly.
"""

from __future__ import annotations

import pytest
from fake_fub import FakeFUBClient

import server


def _seed_basic_contact(fake: FakeFUBClient, *, person_id: int = 1, owner_id: int = 42) -> None:
    fake.add_person(person_id, firstName="Jane", lastName="Doe", assignedUserId=owner_id)
    fake.add_user(owner_id, name="Blaise Smith")


# ---------- exact targeting / ambiguous rejection ----------


async def test_exact_targeting_preview_succeeds(fake):
    _seed_basic_contact(fake)
    result = await server.create_contact_note(
        person_id=1, expected_contact_name="Jane Doe", subject="Buyer call", body="Discussed timeline."
    )
    assert result["status"] == "PREVIEW_ONLY_NO_WRITE"
    assert fake.create_note_calls == 0


async def test_ambiguous_or_wrong_name_rejected(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="Exact contact-name check failed"):
        await server.create_contact_note(person_id=1, expected_contact_name="Jane Smith", subject="x", body="y")
    assert fake.create_note_calls == 0


async def test_ambiguous_name_rejected_in_closeout(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="Exact contact-name check failed"):
        await server.close_out_contact_interaction(
            person_id=1,
            expected_contact_name="Someone Else",
            expected_assigned_user_id=42,
            note_subject="Call",
            note_body="Discussed timeline with client.",
        )
    assert fake.create_note_calls == 0
    assert fake.create_task_calls == 0


# ---------- owner verification ----------


async def test_owner_verification_passes_when_matching(fake, writable):
    _seed_basic_contact(fake)
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        execute=True,
    )
    assert result["status"] == "CLOSEOUT_COMPLETED"


async def test_owner_mismatch_rejected_before_any_write(fake):
    _seed_basic_contact(fake, owner_id=42)
    with pytest.raises(ValueError, match="Owner verification failed"):
        await server.close_out_contact_interaction(
            person_id=1,
            expected_contact_name="Jane Doe",
            expected_assigned_user_id=99,
            note_subject="Buyer call",
            note_body="Discussed financing timeline with buyer.",
            execute=True,
        )
    assert fake.create_note_calls == 0
    assert fake.create_task_calls == 0


async def test_ownership_mismatch_surfaced_by_audit(fake):
    _seed_basic_contact(fake, owner_id=42)
    result = await server.audit_contact_daily_control(
        person_id=1, expected_contact_name="Jane Doe", expected_assigned_user_id=7
    )
    gap_types = {f["gap_type"] for f in result["findings"]}
    assert "ownership_mismatch" in gap_types


# ---------- preview causes zero writes ----------


async def test_preview_causes_zero_writes_note(fake):
    _seed_basic_contact(fake)
    await server.create_contact_note(person_id=1, expected_contact_name="Jane Doe", subject="s", body="b")
    assert fake.create_note_calls == 0
    assert len(fake.notes) == 0


async def test_preview_causes_zero_writes_task(fake):
    _seed_basic_contact(fake)
    await server.create_contact_task(
        person_id=1,
        expected_contact_name="Jane Doe",
        assigned_user_id=42,
        name="Call to confirm inspection date",
        task_type="Call",
        due_date="2026-09-15",
    )
    assert fake.create_task_calls == 0
    assert len(fake.tasks) == 0


async def test_preview_causes_zero_writes_closeout(fake):
    _seed_basic_contact(fake)
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
    )
    assert result["status"] == "PREVIEW_ONLY_NO_WRITE"
    assert fake.create_note_calls == 0
    assert fake.create_task_calls == 0


# ---------- duplicate prevention / idempotent retry ----------


async def test_duplicate_task_prevention_on_create_contact_task(fake, writable):
    _seed_basic_contact(fake)
    fake.add_task(500, personId=1, name="Call to confirm inspection date", type="Call", dueDate="2026-09-15")
    result = await server.create_contact_task(
        person_id=1,
        expected_contact_name="Jane Doe",
        assigned_user_id=42,
        name="Call to confirm inspection date",
        task_type="Call",
        due_date="2026-09-15",
        execute=True,
    )
    assert result["status"] == "SKIPPED_EXACT_DUPLICATE_EXISTS"
    assert fake.create_task_calls == 0


async def test_idempotent_retry_note_creates_once(fake, writable):
    _seed_basic_contact(fake)
    kwargs = dict(person_id=1, expected_contact_name="Jane Doe", subject="Buyer call", body="Discussed terms.")
    first = await server.create_contact_note(**kwargs, execute=True)
    second = await server.create_contact_note(**kwargs, execute=True)
    assert first["status"] == "WRITE_COMPLETED_AND_RE_READ"
    assert second["status"] == "SKIPPED_EXACT_DUPLICATE_EXISTS"
    assert fake.create_note_calls == 1


async def test_idempotent_retry_task_creates_once(fake, writable):
    _seed_basic_contact(fake)
    kwargs = dict(
        person_id=1,
        expected_contact_name="Jane Doe",
        assigned_user_id=42,
        name="Call to confirm inspection date",
        task_type="Call",
        due_date="2026-09-15",
    )
    first = await server.create_contact_task(**kwargs, execute=True)
    second = await server.create_contact_task(**kwargs, execute=True)
    assert first["status"] == "WRITE_COMPLETED_AND_RE_READ"
    assert second["status"] == "SKIPPED_EXACT_DUPLICATE_EXISTS"
    assert fake.create_task_calls == 1


async def test_existing_appropriate_next_action_skips_new_task_in_closeout(fake, writable):
    _seed_basic_contact(fake)
    fake.add_task(500, personId=1, name="Call to confirm inspection date", type="Call", dueDate="2026-09-15")
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
    assert result["task"]["status"] == "SKIPPED_EXACT_DUPLICATE_EXISTS"
    assert fake.create_task_calls == 0


# ---------- note / next-task validation ----------


async def test_note_validation_rejects_sensitive_data(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="sensitive data"):
        await server.create_contact_note(
            person_id=1,
            expected_contact_name="Jane Doe",
            subject="Financials",
            body="Client SSN is 123-45-6789.",
        )
    assert fake.create_note_calls == 0


async def test_next_task_requires_exactly_one_due_field(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="exactly one"):
        await server.create_contact_task(
            person_id=1,
            expected_contact_name="Jane Doe",
            assigned_user_id=42,
            name="Call to confirm inspection date",
            task_type="Call",
        )


async def test_next_task_rejects_unsupported_type(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="Unsupported task type"):
        await server.create_contact_task(
            person_id=1,
            expected_contact_name="Jane Doe",
            assigned_user_id=42,
            name="Call to confirm inspection date",
            task_type="Carrier Pigeon",
            due_date="2026-09-15",
        )


async def test_next_task_rejects_vague_name(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="placeholder"):
        await server.create_contact_task(
            person_id=1,
            expected_contact_name="Jane Doe",
            assigned_user_id=42,
            name="Follow Up",
            task_type="Call",
            due_date="2026-09-15",
        )


async def test_closeout_rejects_vague_next_task_name(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="placeholder"):
        await server.close_out_contact_interaction(
            person_id=1,
            expected_contact_name="Jane Doe",
            expected_assigned_user_id=42,
            note_subject="Buyer call",
            note_body="Discussed financing timeline with buyer.",
            create_next_task=True,
            next_task_name="Call",
            next_task_type="Call",
            next_task_due_date="2026-09-15",
        )


# ---------- API visibility limitations ----------


async def test_audit_no_notes_does_not_assert_no_interaction(fake):
    _seed_basic_contact(fake)
    fake.add_task(500, personId=1, name="Call to confirm inspection date", type="Call", dueDate="2026-09-15")
    result = await server.audit_contact_daily_control(person_id=1, expected_contact_name="Jane Doe")
    gap = next(f for f in result["findings"] if f["gap_type"] == "no_recent_interaction_note")
    assert "does not prove" in gap["caveat"]
    assert "Absence of API-visible communication" in result["caveats"][1]


# ---------- write failures ----------


async def test_note_write_failure_raises_and_leaves_no_partial_state(fake, writable):
    _seed_basic_contact(fake)
    fake.fail_create_note = True
    with pytest.raises(RuntimeError):
        await server.create_contact_note(
            person_id=1, expected_contact_name="Jane Doe", subject="s", body="b", execute=True
        )
    assert fake.create_note_calls == 1
    assert len(fake.notes) == 0


async def test_task_write_failure_raises_and_leaves_no_partial_state(fake, writable):
    _seed_basic_contact(fake)
    fake.fail_create_task = True
    with pytest.raises(RuntimeError):
        await server.create_contact_task(
            person_id=1,
            expected_contact_name="Jane Doe",
            assigned_user_id=42,
            name="Call to confirm inspection date",
            task_type="Call",
            due_date="2026-09-15",
            execute=True,
        )
    assert fake.create_task_calls == 1
    assert len(fake.tasks) == 0


# ---------- read-back failures ----------


async def test_note_readback_failure_reports_unverified_not_success(fake, writable):
    _seed_basic_contact(fake)
    fake.fail_note_readback = True
    result = await server.create_contact_note(
        person_id=1, expected_contact_name="Jane Doe", subject="s", body="b", execute=True
    )
    assert result["status"] == "WRITE_COMPLETED_UNVERIFIED"
    assert fake.create_note_calls == 1


async def test_task_readback_failure_reports_unverified_not_success(fake, writable):
    _seed_basic_contact(fake)
    fake.fail_task_readback = True
    result = await server.create_contact_task(
        person_id=1,
        expected_contact_name="Jane Doe",
        assigned_user_id=42,
        name="Call to confirm inspection date",
        task_type="Call",
        due_date="2026-09-15",
        execute=True,
    )
    assert result["status"] == "WRITE_COMPLETED_UNVERIFIED"
    assert fake.create_task_calls == 1


async def test_note_readback_content_mismatch_detected(fake, writable):
    _seed_basic_contact(fake)
    fake.corrupt_note_readback = True
    result = await server.create_contact_note(
        person_id=1, expected_contact_name="Jane Doe", subject="s", body="b", execute=True
    )
    assert result["status"] == "WRITE_COMPLETED_CONTENT_MISMATCH"


async def test_task_readback_content_mismatch_detected(fake, writable):
    _seed_basic_contact(fake)
    fake.corrupt_task_readback = True
    result = await server.create_contact_task(
        person_id=1,
        expected_contact_name="Jane Doe",
        assigned_user_id=42,
        name="Call to confirm inspection date",
        task_type="Call",
        due_date="2026-09-15",
        execute=True,
    )
    assert result["status"] == "WRITE_COMPLETED_CONTENT_MISMATCH"
    assert "name" in result["hold"]


# ---------- partial-write recovery / reporting ----------


async def test_closeout_partial_failure_reports_note_success_and_task_failure(fake, writable):
    _seed_basic_contact(fake)
    fake.fail_create_task = True
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
    assert result["note"]["status"] == "WRITE_COMPLETED_AND_RE_READ"
    assert result["task"]["status"] == "WRITE_FAILED"
    assert result["created_object_ids"]["note_id"] is not None
    assert result["created_object_ids"]["task_id"] is None
    assert any("Task write not fully verified" in u for u in result["unresolved"])


# ---------- unintended-change detection ----------


class DriftingPersonClient(FakeFUBClient):
    """Simulates an unrelated field changing on the person record mid-workflow."""

    def __init__(self) -> None:
        super().__init__()
        self._get_person_calls = 0

    async def get_person(self, person_id: int):
        self._get_person_calls += 1
        person = await super().get_person(person_id)
        if self._get_person_calls > 1:
            person["stage"] = "Trash"
        return person


async def test_unintended_person_change_detected(monkeypatch, writable):
    client = DriftingPersonClient()
    _seed_basic_contact(client)
    monkeypatch.setattr(server, "_client", lambda: client)
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        execute=True,
    )
    assert result["status"] == "CLOSEOUT_COMPLETED_WITH_HOLD"
    assert "stage" in result["before_after"]["person_field_changes"]
    assert any("Unexpected contact field change" in u for u in result["unresolved"])


class DriftingTaskClient(FakeFUBClient):
    """Simulates a pre-existing open task changing mid-workflow (not caused by this write)."""

    def __init__(self) -> None:
        super().__init__()
        self._search_calls = 0

    async def search_tasks(self, **params):
        self._search_calls += 1
        result = await super().search_tasks(**params)
        if self._search_calls > 1:
            for t in result["tasks"]:
                if t.get("id") == 900:
                    t["name"] = "Mutated externally"
        return result


async def test_unrelated_task_change_detected(monkeypatch, writable):
    client = DriftingTaskClient()
    _seed_basic_contact(client)
    client.add_task(900, personId=1, name="Pre-existing task", type="Call", dueDate="2026-09-20")
    monkeypatch.setattr(server, "_client", lambda: client)
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed financing timeline with buyer.",
        execute=True,
    )
    assert result["status"] == "CLOSEOUT_COMPLETED_WITH_HOLD"
    assert result["before_after"]["unrelated_open_task_changes"]
    assert any("pre-existing open tasks" in u for u in result["unresolved"])


# ---------- sensitive-data rejection across closeout ----------


async def test_closeout_rejects_sensitive_data_in_note_body(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="sensitive data"):
        await server.close_out_contact_interaction(
            person_id=1,
            expected_contact_name="Jane Doe",
            expected_assigned_user_id=42,
            note_subject="Wire",
            note_body="TrustFunds secret word is Falcon22.",
        )
    assert fake.create_note_calls == 0
    assert fake.create_task_calls == 0


async def test_closeout_rejects_sensitive_data_in_task_name(fake):
    _seed_basic_contact(fake)
    with pytest.raises(ValueError, match="sensitive data"):
        await server.close_out_contact_interaction(
            person_id=1,
            expected_contact_name="Jane Doe",
            expected_assigned_user_id=42,
            note_subject="Buyer call",
            note_body="Discussed timeline with buyer.",
            create_next_task=True,
            next_task_name="Call about account number 000123456789",
            next_task_type="Call",
            next_task_due_date="2026-09-15",
        )
    assert fake.create_note_calls == 0


# ---------- batch audit ----------


async def test_batch_audit_one_bad_entry_does_not_abort_others(fake):
    _seed_basic_contact(fake, person_id=1, owner_id=42)
    fake.add_person(2, firstName="John", lastName="Roe", assignedUserId=42)
    result = await server.audit_contacts_daily_control_batch(
        contacts=[
            {"person_id": 1, "expected_contact_name": "Jane Doe"},
            {"person_id": 2, "expected_contact_name": "Wrong Name"},
        ]
    )
    assert result["status"] == "BATCH_AUDIT_COMPLETE"
    assert len(result["results"]) == 1
    assert len(result["errors"]) == 1
    assert result["results"][0]["personId"] == 1


# ---------- relationship-context / next-commitment advisory ----------


async def test_closeout_preview_surfaces_recent_notes_and_advisory(fake):
    _seed_basic_contact(fake)
    fake.add_note(700, personId=1, subject="Prior call", body="Discussed price.", created="2026-08-20T10:00:00Z")
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed inspection results with buyer.",
    )
    preview = result["preview"]
    assert preview["context"]["recent_notes"][0]["id"] == 700
    assert preview["next_commitment_advisory"] is not None
    assert "no dated next action" in preview["next_commitment_advisory"]


async def test_closeout_preview_no_advisory_when_open_task_exists(fake):
    _seed_basic_contact(fake)
    fake.add_task(500, personId=1, name="Call to confirm inspection date", type="Call", dueDate="2026-09-15")
    result = await server.close_out_contact_interaction(
        person_id=1,
        expected_contact_name="Jane Doe",
        expected_assigned_user_id=42,
        note_subject="Buyer call",
        note_body="Discussed inspection results with buyer.",
    )
    assert result["preview"]["next_commitment_advisory"] is None
