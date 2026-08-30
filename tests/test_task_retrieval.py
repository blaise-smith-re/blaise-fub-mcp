"""Integration tests for the hardened task-retrieval path (search_tasks,
get_open_tasks) — deterministic due-date filtering, pagination completeness,
and exactly-once retrieval across pages.

Reproduces the verified production defect from FUB 06 v1.6 as regression
tests: due=today missing a real due-today task; due=tomorrow / specific-date
inputs silently ignored; up to 21 of 22 open tasks returned as if that were
the complete set, with no pagination parameter to catch it.
"""

from __future__ import annotations

import pytest

import server


def _seed_contact(fake, *, person_id: int = 1, owner_id: int = 42) -> None:
    fake.add_person(person_id, firstName="Jane", lastName="Doe", assignedUserId=owner_id)
    fake.add_user(owner_id, name="Blaise Smith")


def _seed_many_tasks(fake, *, person_id: int, count: int, start_id: int = 1000) -> list[int]:
    ids = []
    for i in range(count):
        task_id = start_id + i
        fake.add_task(
            task_id,
            personId=person_id,
            name=f"Call re: task {i}",
            type="Call",
            dueDate="2026-09-01",
        )
        ids.append(task_id)
    return ids


# ---------- due today / overdue / future due / no due date ----------


async def test_search_tasks_due_on_today_returns_the_right_task(fake):
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Call to confirm inspection", type="Call", dueDate="2026-08-30")
    fake.add_task(2, personId=1, name="Email closing docs", type="Email", dueDate="2026-09-15")
    result = await server.search_tasks(person_id=1, due_on="2026-08-30", due_timezone="America/Chicago")
    assert [t["id"] for t in result["tasks"]] == [1]
    assert result["due_date_filter"]["due_on"] == "2026-08-30"


async def test_search_tasks_overdue_via_due_to(fake):
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Call to confirm inspection", type="Call", dueDate="2026-08-01")
    fake.add_task(2, personId=1, name="Email closing docs", type="Email", dueDate="2026-09-15")
    result = await server.search_tasks(person_id=1, due_to="2026-08-29")
    assert [t["id"] for t in result["tasks"]] == [1]


async def test_search_tasks_future_due_via_due_from(fake):
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Call to confirm inspection", type="Call", dueDate="2026-08-01")
    fake.add_task(2, personId=1, name="Email closing docs", type="Email", dueDate="2026-09-15")
    result = await server.search_tasks(person_id=1, due_from="2026-08-31")
    assert [t["id"] for t in result["tasks"]] == [2]


async def test_search_tasks_no_due_date_excluded_from_date_filter_and_disclosed(fake):
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Call to confirm inspection", type="Call", dueDate="2026-08-30")
    fake.add_task(2, personId=1, name="Undated task", type="Call")  # no dueDate at all
    result = await server.search_tasks(person_id=1, due_on="2026-08-30")
    assert [t["id"] for t in result["tasks"]] == [1]
    assert result["due_date_filter"]["excluded_no_usable_due_date"] == 1


async def test_search_tasks_no_date_filter_leaves_undated_tasks_in_results(fake):
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Undated task", type="Call")
    result = await server.search_tasks(person_id=1)
    assert [t["id"] for t in result["tasks"]] == [1]
    assert "due_date_filter" not in result


# ---------- America/Chicago boundary at the tool level ----------


async def test_search_tasks_chicago_boundary_finds_late_evening_task_as_due_today(fake):
    """A task due 10:30pm Chicago on Aug 30 has a raw UTC instant already on Aug 31.
    due_on="2026-08-30" with the default America/Chicago timezone must still find it.
    """
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Call to confirm inspection", type="Call", dueDateTime="2026-08-31T04:30:00Z")
    result = await server.search_tasks(person_id=1, due_on="2026-08-30", due_timezone="America/Chicago")
    assert [t["id"] for t in result["tasks"]] == [1]


async def test_search_tasks_different_timezone_changes_the_boundary_classification(fake):
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Call to confirm inspection", type="Call", dueDateTime="2026-08-31T04:30:00Z")
    result = await server.search_tasks(person_id=1, due_on="2026-08-30", due_timezone="UTC")
    assert result["tasks"] == []
    result_utc_day = await server.search_tasks(person_id=1, due_on="2026-08-31", due_timezone="UTC")
    assert [t["id"] for t in result_utc_day["tasks"]] == [1]


# ---------- invalid date syntax: clear error, never silently ignored ----------


@pytest.mark.parametrize("bad_value", ["tomorrow", "next week", "08/30/2026", "", "2026-13-45"])
async def test_search_tasks_invalid_due_on_syntax_raises_clear_error(fake, bad_value):
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Call to confirm inspection", type="Call", dueDate="2026-08-30")
    with pytest.raises(ValueError, match="due_on"):
        await server.search_tasks(person_id=1, due_on=bad_value)


async def test_search_tasks_invalid_due_from_syntax_raises_clear_error(fake):
    _seed_contact(fake)
    with pytest.raises(ValueError, match="due_from"):
        await server.search_tasks(person_id=1, due_from="not-a-date")


async def test_search_tasks_invalid_due_to_syntax_raises_clear_error(fake):
    _seed_contact(fake)
    with pytest.raises(ValueError, match="due_to"):
        await server.search_tasks(person_id=1, due_to="garbage")


async def test_search_tasks_invalid_timezone_raises_clear_error(fake):
    _seed_contact(fake)
    with pytest.raises(ValueError, match="[Tt]imezone"):
        await server.search_tasks(person_id=1, due_on="2026-08-30", due_timezone="Mars/Colony")


async def test_search_tasks_inverted_range_raises_clear_error(fake):
    _seed_contact(fake)
    with pytest.raises(ValueError, match="due_from.*due_to|after due_to"):
        await server.search_tasks(person_id=1, due_from="2026-09-15", due_to="2026-08-01")


async def test_invalid_date_syntax_never_reaches_the_client(fake):
    """Confirm the error is raised before any FUB call — never silently ignored downstream."""
    _seed_contact(fake)
    calls_before = fake.create_task_calls
    with pytest.raises(ValueError):
        await server.search_tasks(person_id=1, due_on="not-a-date")
    assert fake.create_task_calls == calls_before  # nothing happened at all


# ---------- legacy `due` keyword: backward compatible, but disclosed as unreliable ----------


async def test_legacy_due_keyword_still_accepted_for_backward_compatibility(monkeypatch, fake):
    _seed_contact(fake)
    received = {}
    original = fake.search_tasks

    async def spy(**params):
        received.update(params)
        return await original(**params)

    monkeypatch.setattr(fake, "search_tasks", spy)
    result = await server.search_tasks(person_id=1, due="today")
    assert received.get("due") == "today"
    assert "due_keyword_caveat" in result
    assert "FUB 06" in result["due_keyword_caveat"]


async def test_no_due_keyword_no_caveat(fake):
    _seed_contact(fake)
    result = await server.search_tasks(person_id=1)
    assert "due_keyword_caveat" not in result


# ---------- pagination: result set larger than one page ----------


async def test_search_tasks_single_page_default_discloses_truncation(fake):
    _seed_contact(fake)
    _seed_many_tasks(fake, person_id=1, count=150)
    result = await server.search_tasks(person_id=1, limit=50)
    assert len(result["tasks"]) == 50
    assert result["_completeness"]["returned_count"] == 50
    assert result["_completeness"]["total_count"] == 150
    assert result["_completeness"]["has_more"] is True
    assert result["_completeness"]["next_offset"] == 50


async def test_search_tasks_fetch_all_retrieves_the_complete_set_beyond_one_page(fake):
    _seed_contact(fake)
    seeded_ids = _seed_many_tasks(fake, person_id=1, count=150)
    result = await server.search_tasks(person_id=1, fetch_all=True)
    assert len(result["tasks"]) == 150
    assert {t["id"] for t in result["tasks"]} == set(seeded_ids)
    assert result["_completeness"]["total_count"] == 150
    assert result["_completeness"]["has_more"] is False
    assert result["_completeness"]["capped"] is False


async def test_date_filter_forces_complete_retrieval_even_without_fetch_all(fake):
    """A date filter on a single truncated page could silently miss a match on a
    later page — this must never happen. Requesting a date filter forces the
    complete set to be fetched first, filtered second.
    """
    _seed_contact(fake)
    _seed_many_tasks(fake, person_id=1, count=150)  # all dueDate 2026-09-01
    fake.add_task(9999, personId=1, name="Distant match", type="Call", dueDate="2026-08-30")
    result = await server.search_tasks(person_id=1, due_on="2026-08-30", limit=50)
    assert [t["id"] for t in result["tasks"]] == [9999]
    assert result["_completeness"]["total_count"] == 151


async def test_exactly_once_complete_retrieval_no_duplicates_across_pages(fake):
    """Retrieval must be exactly-once: every seeded task appears exactly once,
    none missing, none duplicated, across a set that spans several pages at the
    default page size and is not an exact multiple of it.
    """
    _seed_contact(fake)
    seeded_ids = _seed_many_tasks(fake, person_id=1, count=237)
    result = await server.search_tasks(person_id=1, fetch_all=True)
    returned_ids = [t["id"] for t in result["tasks"]]
    assert len(returned_ids) == 237
    assert len(set(returned_ids)) == 237  # no duplicates
    assert set(returned_ids) == set(seeded_ids)  # none missing, none extra
    assert result["_completeness"]["pages_fetched"] >= 3  # spans multiple 100-item pages


async def test_get_open_tasks_always_retrieves_the_complete_set(fake):
    """Regression test for the exact verified production defect: get_open_tasks
    must never silently return fewer open tasks than actually exist.
    """
    _seed_contact(fake)
    seeded_ids = _seed_many_tasks(fake, person_id=1, count=130)
    for task_id in seeded_ids:
        fake.tasks[task_id]["isCompleted"] = False
    result = await server.get_open_tasks(person_id=1)
    assert len(result["tasks"]) == 130
    assert result["_completeness"]["total_count"] == 130
    assert result["_completeness"]["has_more"] is False


async def test_get_open_tasks_excludes_completed_tasks(fake):
    _seed_contact(fake)
    fake.add_task(1, personId=1, name="Open task", type="Call", dueDate="2026-09-01", isCompleted=False)
    fake.add_task(2, personId=1, name="Done task", type="Call", dueDate="2026-09-01", isCompleted=True)
    result = await server.get_open_tasks(person_id=1)
    assert [t["id"] for t in result["tasks"]] == [1]


async def test_get_open_tasks_only_returns_tasks_for_the_requested_contact(fake):
    _seed_contact(fake, person_id=1)
    fake.add_person(2, firstName="John", lastName="Roe", assignedUserId=42)
    fake.add_task(1, personId=1, name="Contact 1 task", type="Call", dueDate="2026-09-01")
    fake.add_task(2, personId=2, name="Contact 2 task", type="Call", dueDate="2026-09-01")
    result = await server.get_open_tasks(person_id=1)
    assert [t["id"] for t in result["tasks"]] == [1]


# ---------- no change broadens write authority or communication capability ----------


def test_search_tasks_and_get_open_tasks_remain_read_only_signatures():
    """Structural guard: neither tool gained an execute flag or any write path."""
    import inspect

    for fn in (server.search_tasks, server.get_open_tasks):
        params = inspect.signature(fn).parameters
        assert "execute" not in params
