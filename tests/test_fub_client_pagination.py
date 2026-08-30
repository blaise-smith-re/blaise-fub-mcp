"""Client-layer tests for FUBClient.search_tasks_all's pagination algorithm
itself — safety cap behavior and tolerance of a FUB response that omits
_metadata entirely, both exercised directly (not through the MCP tool layer,
which doesn't expose max_items/page_size).
"""

from __future__ import annotations

from fake_fub import FakeFUBClient


async def test_capped_when_max_items_exceeded_and_disclosed():
    fake = FakeFUBClient()
    for i in range(250):
        fake.add_task(i, personId=1, name=f"Task {i}", type="Call", dueDate="2026-09-01")
    tasks, completeness = await fake.search_tasks_all(personId=1, page_size=50, max_items=120)
    assert len(tasks) <= 120 + 49  # may overshoot by up to one page before the cap check
    assert completeness["capped"] is True
    assert completeness["has_more"] is True


async def test_no_duplicates_even_when_capped():
    fake = FakeFUBClient()
    for i in range(250):
        fake.add_task(i, personId=1, name=f"Task {i}", type="Call", dueDate="2026-09-01")
    tasks, _completeness = await fake.search_tasks_all(personId=1, page_size=50, max_items=120)
    ids = [t["id"] for t in tasks]
    assert len(ids) == len(set(ids))


async def test_small_result_set_is_not_capped():
    fake = FakeFUBClient()
    for i in range(5):
        fake.add_task(i, personId=1, name=f"Task {i}", type="Call", dueDate="2026-09-01")
    tasks, completeness = await fake.search_tasks_all(personId=1, page_size=50, max_items=1000)
    assert len(tasks) == 5
    assert completeness["capped"] is False
    assert completeness["has_more"] is False
    assert completeness["pages_fetched"] == 1


async def test_empty_result_set():
    fake = FakeFUBClient()
    tasks, completeness = await fake.search_tasks_all(personId=999)
    assert tasks == []
    assert completeness["returned_count"] == 0
    assert completeness["has_more"] is False


class NoMetadataClient(FakeFUBClient):
    """Simulates a FUB response that omits _metadata entirely."""

    async def search_tasks(self, **params):
        result = await super().search_tasks(**params)
        result.pop("_metadata", None)
        return result


async def test_missing_metadata_total_reports_none_not_a_crash():
    client = NoMetadataClient()
    for i in range(5):
        client.add_task(i, personId=1, name=f"Task {i}", type="Call", dueDate="2026-09-01")
    tasks, completeness = await client.search_tasks_all(personId=1)
    assert len(tasks) == 5
    assert completeness["total_count"] is None
    # With no disclosed total, has_more can only reflect whether we hit a cap.
    assert completeness["has_more"] is False


async def test_page_size_is_clamped_to_a_sane_range():
    fake = FakeFUBClient()
    for i in range(5):
        fake.add_task(i, personId=1, name=f"Task {i}", type="Call", dueDate="2026-09-01")
    # page_size <= 0 or absurdly large must not break pagination.
    tasks_low, _ = await fake.search_tasks_all(personId=1, page_size=0)
    tasks_high, _ = await fake.search_tasks_all(personId=1, page_size=10_000)
    assert {t["id"] for t in tasks_low} == {0, 1, 2, 3, 4}
    assert {t["id"] for t in tasks_high} == {0, 1, 2, 3, 4}
