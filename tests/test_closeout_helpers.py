from closeout import (
    diff_person_snapshot,
    find_duplicate_note,
    find_exact_duplicate_task,
    find_unexpected_task_changes,
    is_vague_task_name,
    summarize_recent_notes,
)


def test_find_exact_duplicate_task_matches_name_type_due():
    open_tasks = [{"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"}]
    dup = find_exact_duplicate_task(
        open_tasks, name="call to confirm inspection", task_type="Call", due_date="2026-09-15", due_date_time=None
    )
    assert dup is not None
    assert dup["id"] == 1


def test_find_exact_duplicate_task_no_match_on_different_due_date():
    open_tasks = [{"id": 1, "name": "Call to confirm inspection", "type": "Call", "dueDate": "2026-09-15"}]
    dup = find_exact_duplicate_task(
        open_tasks, name="Call to confirm inspection", task_type="Call", due_date="2026-09-16", due_date_time=None
    )
    assert dup is None


def test_find_duplicate_note_case_and_whitespace_insensitive():
    notes = [{"id": 1, "subject": "Buyer call", "body": "Discussed offer terms."}]
    dup = find_duplicate_note(notes, subject="  BUYER CALL  ", body="discussed offer terms.")
    assert dup is not None
    assert dup["id"] == 1


def test_find_duplicate_note_no_match_on_different_body():
    notes = [{"id": 1, "subject": "Buyer call", "body": "Discussed offer terms."}]
    dup = find_duplicate_note(notes, subject="Buyer call", body="Different content entirely.")
    assert dup is None


def test_diff_person_snapshot_ignores_volatile_fields():
    before = {"id": 1, "firstName": "Jane", "updated": "2026-08-01T00:00:00Z", "lastActivity": "2026-08-01"}
    after = {"id": 1, "firstName": "Jane", "updated": "2026-08-29T12:00:00Z", "lastActivity": "2026-08-29"}
    assert diff_person_snapshot(before, after) == {}


def test_diff_person_snapshot_flags_unexpected_field_change():
    before = {"id": 1, "stage": "Lead"}
    after = {"id": 1, "stage": "Under Contract"}
    diff = diff_person_snapshot(before, after)
    assert diff == {"stage": {"before": "Lead", "after": "Under Contract"}}


def test_find_unexpected_task_changes_none_when_only_new_allowed_task_added():
    before = [{"id": 1, "name": "Existing task", "type": "Call", "isCompleted": False}]
    after = [
        {"id": 1, "name": "Existing task", "type": "Call", "isCompleted": False},
        {"id": 2, "name": "New task", "type": "Call", "isCompleted": False},
    ]
    problems = find_unexpected_task_changes(before, after, allowed_new_task_ids=frozenset({2}))
    assert problems == []


def test_find_unexpected_task_changes_flags_unallowed_new_task():
    before = [{"id": 1, "name": "Existing task", "type": "Call", "isCompleted": False}]
    after = [
        {"id": 1, "name": "Existing task", "type": "Call", "isCompleted": False},
        {"id": 2, "name": "Surprise task", "type": "Call", "isCompleted": False},
    ]
    problems = find_unexpected_task_changes(before, after, allowed_new_task_ids=frozenset())
    assert len(problems) == 1
    assert problems[0]["problem"] == "unexpected_new_task"


def test_find_unexpected_task_changes_flags_altered_existing_task():
    before = [{"id": 1, "name": "Existing task", "type": "Call", "isCompleted": False}]
    after = [{"id": 1, "name": "Different name", "type": "Call", "isCompleted": False}]
    problems = find_unexpected_task_changes(before, after)
    assert len(problems) == 1
    assert problems[0]["problem"] == "changed"
    assert "name" in problems[0]["diff"]


def test_find_unexpected_task_changes_flags_disappeared_task():
    before = [{"id": 1, "name": "Existing task", "type": "Call", "isCompleted": False}]
    after: list[dict] = []
    problems = find_unexpected_task_changes(before, after)
    assert problems[0]["problem"] == "disappeared"


def test_is_vague_task_name_rejects_bare_placeholders():
    for name in ["Follow Up", "follow up", "  Call  ", "Touch base", "Check-In"]:
        assert is_vague_task_name(name), name


def test_is_vague_task_name_allows_specific_names():
    for name in [
        "Call to confirm inspection date",
        "Email closing docs to buyer",
        "Follow up on inspection repairs list",
    ]:
        assert not is_vague_task_name(name), name


def test_summarize_recent_notes_orders_by_recency_and_limits():
    notes = [
        {"id": 1, "subject": "Oldest", "created": "2026-01-01T00:00:00Z"},
        {"id": 2, "subject": "Newest", "created": "2026-08-01T00:00:00Z"},
        {"id": 3, "subject": "Middle", "created": "2026-04-01T00:00:00Z"},
        {"id": 4, "subject": "Also old", "created": "2026-02-01T00:00:00Z"},
    ]
    summary = summarize_recent_notes(notes, limit=2)
    assert [n["id"] for n in summary] == [2, 3]
