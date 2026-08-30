from datetime import UTC, datetime

from daily_control import find_gaps

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
PERSON = {"id": 1, "assignedUserId": 42}


def test_no_open_tasks_flags_no_future_task():
    findings = find_gaps(person=PERSON, open_tasks=[], notes=[{"created": "2026-08-20T10:00:00Z"}], now=NOW)
    gap_types = [f["gap_type"] for f in findings]
    assert "no_future_task" in gap_types
    finding = next(f for f in findings if f["gap_type"] == "no_future_task")
    assert finding["evidence"]["open_task_count"] == 0


def test_only_overdue_tasks_flags_no_future_task_and_overdue():
    open_tasks = [{"id": 1, "name": "Call to discuss offer", "type": "Call", "dueDate": "2026-08-01"}]
    findings = find_gaps(person=PERSON, open_tasks=open_tasks, notes=[], now=NOW)
    gap_types = {f["gap_type"] for f in findings}
    assert "no_future_task" in gap_types
    assert "overdue_tasks" in gap_types


def test_future_task_present_no_gap_reported():
    open_tasks = [{"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"}]
    findings = find_gaps(person=PERSON, open_tasks=open_tasks, notes=[{"created": "2026-08-25T10:00:00Z"}], now=NOW)
    gap_types = {f["gap_type"] for f in findings}
    assert "no_future_task" not in gap_types
    assert "overdue_tasks" not in gap_types


def test_exact_duplicate_open_tasks_detected():
    open_tasks = [
        {"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"},
        {"id": 2, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"},
    ]
    findings = find_gaps(person=PERSON, open_tasks=open_tasks, notes=[], now=NOW)
    dup = next(f for f in findings if f["gap_type"] == "exact_duplicate_open_tasks")
    assert len(dup["evidence"]["groups"]) == 1
    assert len(dup["evidence"]["groups"][0]) == 2


def test_conflicting_next_actions_same_day_different_tasks():
    open_tasks = [
        {"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"},
        {"id": 2, "name": "Email closing documents", "type": "Email", "dueDate": "2026-09-15"},
    ]
    findings = find_gaps(person=PERSON, open_tasks=open_tasks, notes=[], now=NOW)
    conflict = next(f for f in findings if f["gap_type"] == "conflicting_next_actions")
    assert len(conflict["evidence"]["tasks"]) == 2
    assert "caveat" in conflict


def test_no_notes_flags_gap_with_caveat_not_a_proof_of_absence():
    open_tasks = [{"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"}]
    findings = find_gaps(person=PERSON, open_tasks=open_tasks, notes=[], now=NOW)
    gap = next(f for f in findings if f["gap_type"] == "no_recent_interaction_note")
    assert "does not prove" in gap["caveat"]


def test_stale_note_flags_gap_with_caveat():
    open_tasks = [{"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"}]
    notes = [{"id": 5, "created": "2026-06-01T10:00:00Z"}]
    findings = find_gaps(person=PERSON, open_tasks=open_tasks, notes=notes, now=NOW, stale_note_days=21)
    gap = next(f for f in findings if f["gap_type"] == "no_recent_interaction_note")
    assert gap["evidence"]["latest_note_id"] == 5
    assert "not proof" in gap["caveat"]


def test_recent_note_no_stale_gap():
    open_tasks = [{"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"}]
    notes = [{"id": 5, "created": "2026-08-25T10:00:00Z"}]
    findings = find_gaps(person=PERSON, open_tasks=open_tasks, notes=notes, now=NOW, stale_note_days=21)
    gap_types = {f["gap_type"] for f in findings}
    assert "no_recent_interaction_note" not in gap_types


def test_ownership_mismatch_flagged_only_when_expected_supplied():
    findings_no_expectation = find_gaps(person=PERSON, open_tasks=[], notes=[], now=NOW)
    assert all(f["gap_type"] != "ownership_mismatch" for f in findings_no_expectation)

    findings_mismatch = find_gaps(person=PERSON, open_tasks=[], notes=[], now=NOW, expected_assigned_user_id=99)
    mismatch = next(f for f in findings_mismatch if f["gap_type"] == "ownership_mismatch")
    assert mismatch["evidence"]["assignedUserId"] == 42
    assert mismatch["evidence"]["expected_assigned_user_id"] == 99


def test_ownership_match_no_gap():
    findings = find_gaps(person=PERSON, open_tasks=[], notes=[], now=NOW, expected_assigned_user_id=42)
    assert all(f["gap_type"] != "ownership_mismatch" for f in findings)


def test_events_argument_never_used_to_assert_no_interaction():
    # Passing a populated events list must not suppress or alter the
    # no-notes finding — events are accepted but never treated as proof.
    findings_with_events = find_gaps(
        person=PERSON,
        open_tasks=[],
        notes=[],
        events=[{"type": "call", "created": "2026-08-28T00:00:00Z"}],
        now=NOW,
    )
    findings_without_events = find_gaps(person=PERSON, open_tasks=[], notes=[], events=None, now=NOW)
    types_with = {f["gap_type"] for f in findings_with_events}
    types_without = {f["gap_type"] for f in findings_without_events}
    assert types_with == types_without
    assert "no_recent_interaction_note" in types_with
