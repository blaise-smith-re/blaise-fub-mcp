"""Exercise the real shared client boundary with an offline FUB transport."""

from copy import deepcopy

import pytest

import server
from fub_client import FUBClient


@pytest.fixture
def scoped(monkeypatch):
    records = {
        "/people/1": {"id": 1, "name": "Assigned Client", "assignedUserId": 33, "price": 100},
        "/people/2": {"id": 2, "name": "Other Client", "assignedUserId": 7},
        "/tasks/10": {"id": 10, "personId": 1, "assignedUserId": 33, "name": "Real commitment"},
        "/tasks/11": {"id": 11, "personId": 1, "assignedUserId": 7, "name": "Other task"},
        "/tasks/12": {"id": 12, "personId": 2, "assignedUserId": 33, "name": "Other contact task"},
        "/deals/20": {"id": 20, "name": "Assigned deal", "people": [{"id": 1}], "users": [{"id": 33}]},
        "/deals/21": {"id": 21, "peopleIds": [2], "userIds": [33]},
        "/deals/22": {"id": 22, "peopleIds": [1], "userIds": [7]},
        "/appointments/30": {"id": 30, "invitees": [{"personId": 1}, {"userId": 33}]},
        "/appointments/31": {"id": 31, "invitees": [{"personId": 2}, {"userId": 33}]},
        "/appointments/32": {"id": 32, "invitees": [{"personId": 1}, {"userId": 7}]},
        "/dealAttachments/40": {"id": 40, "dealId": 20},
        "/dealAttachments/41": {"id": 41, "dealId": 21},
    }
    calls = []
    pages = {}

    async def raw(method, path, *, params=None, json_body=None):
        calls.append((method, path, deepcopy(params), deepcopy(json_body)))
        if method == "GET":
            if path in pages:
                return deepcopy(pages[path][(params or {}).get("offset", 0)])
            return deepcopy(records[path])
        if method == "PUT":
            records[path].update(json_body)
            return deepcopy(records[path])
        return {"id": 90, **deepcopy(json_body)}

    client = FUBClient()
    monkeypatch.setattr(client, "_raw_request", raw)
    monkeypatch.setattr(server, "_client", lambda: client)
    return client, records, calls, pages


@pytest.mark.parametrize(
    "path",
    [
        "/people/2",
        "/tasks/11",
        "/tasks/12",
        "/deals/21",
        "/deals/22",
        "/appointments/31",
        "/appointments/32",
        "/dealAttachments/41",
    ],
)
async def test_direct_id_denies_other_owner_without_disclosing_record(scoped, path):
    client, _, calls, _ = scoped
    with pytest.raises(PermissionError, match="record must be assigned to user 33") as error:
        await client._get(path)
    assert "Other" not in str(error.value)
    assert all(call[0] == "GET" for call in calls)


@pytest.mark.parametrize("path", ["/people/1", "/tasks/10", "/deals/20", "/appointments/30", "/dealAttachments/40"])
async def test_assigned_record_reads_still_work(scoped, path):
    client, records, _, _ = scoped
    assert await client._get(path) == records[path]


@pytest.mark.parametrize("collection", ["events", "notes", "calls", "textMessages", "appointments"])
async def test_activity_denied_before_fetching_other_contacts_history(scoped, collection):
    client, _, calls, _ = scoped
    with pytest.raises(PermissionError):
        await client._get(f"/{collection}", {"personId": 2, "next": "opaque-cursor"})
    assert [call[1] for call in calls] == ["/people/2"]


@pytest.mark.parametrize("owner", [7, "7", 0, -1, True, "33,7", "33.0"])
@pytest.mark.parametrize(
    "path,field", [("/people", "assignedUserId"), ("/tasks", "assignedUserId"), ("/deals", "userId")]
)
async def test_search_cannot_override_owner_even_with_cursor(scoped, owner, path, field):
    client, _, calls, _ = scoped
    with pytest.raises(PermissionError):
        await client._get(path, {field: owner, "next": "opaque"})
    assert calls == []


async def test_missing_owner_filter_is_injected_and_mixed_results_are_filtered(scoped):
    client, records, calls, pages = scoped
    pages["/people"] = {
        0: {"people": [records["/people/2"], records["/people/1"]], "_metadata": {"next": "c", "total": 2}}
    }
    result = await client.find_people(name="Client", next="existing-cursor")
    assert [row["id"] for row in result["people"]] == [1]
    assert calls[0][2]["assignedUserId"] == 33
    assert calls[0][2]["next"] == "existing-cursor"
    assert result["_metadata"] == {"next": "c", "total": None}


async def test_filtered_full_task_page_does_not_hide_later_authorized_tasks(scoped):
    client, records, calls, pages = scoped
    pages["/tasks"] = {
        0: {"tasks": [records["/tasks/11"], records["/tasks/12"]], "_metadata": {"total": 3}},
        2: {"tasks": [records["/tasks/10"]], "_metadata": {"total": 3}},
    }
    rows, completeness = await client.search_tasks_all(page_size=2)
    assert [row["id"] for row in rows] == [10]
    assert completeness["has_more"] is False
    assert completeness["total_count"] is None
    assert [call[2]["offset"] for call in calls if call[1] == "/tasks"] == [0, 2]
    assert all(call[2]["assignedUserId"] == 33 for call in calls if call[1] == "/tasks")


@pytest.mark.parametrize(
    "path,body",
    [
        ("/notes", {"personId": 2, "body": "unauthorized"}),
        ("/calls", {"personId": 2}),
        ("/textMessages", {"personId": 2}),
        ("/tasks", {"personId": 1, "assignedUserId": 7}),
        ("/tasks", {"personId": 2, "assignedUserId": 33}),
        ("/deals", {"peopleIds": [2], "userIds": [33]}),
        ("/deals", {"peopleIds": [1], "userIds": [33, 7]}),
        ("/appointments", {"invitees": [{"personId": 2}, {"userId": 33}]}),
        ("/appointments", {"invitees": [{"personId": 1}, {"userId": 7}]}),
        ("/dealAttachments", {"dealId": 21}),
    ],
)
async def test_creation_rejects_out_of_scope_links_and_owners(scoped, path, body):
    client, _, calls, _ = scoped
    with pytest.raises(PermissionError):
        await client._post(path, body)
    assert not any(call[0] == "POST" for call in calls)


@pytest.mark.parametrize(
    "path,body",
    [
        ("/people/2", {"price": 200}),
        ("/people/1", {"assignedUserId": 7}),
        ("/people/1", {"assignedLenderId": 7}),
        ("/people/1", {"assignedTo": "Other agent"}),
        ("/tasks/11", {"isCompleted": True}),
        ("/tasks/12", {"isCompleted": True}),
        ("/tasks/10", {"personId": 2}),
        ("/tasks/10", {"assignedUserId": 7}),
        ("/deals/21", {"price": 200}),
        ("/deals/20", {"userIds": [7]}),
        ("/deals/20", {"peopleIds": [2]}),
        ("/appointments/31", {"title": "Changed"}),
        ("/appointments/30", {"invitees": [{"personId": 1}, {"userId": 7}]}),
    ],
)
async def test_updates_fail_before_any_mutation(scoped, path, body):
    client, _, calls, _ = scoped
    with pytest.raises(PermissionError):
        await client._put(path, body)
    assert not any(call[0] == "PUT" for call in calls)


@pytest.mark.parametrize(
    "path,body",
    [
        ("/notes", {"personId": 1, "subject": "Real source", "body": "Recorded outcome"}),
        ("/tasks", {"personId": 1, "assignedUserId": 33, "name": "Confirm actual appointment"}),
        ("/deals", {"peopleIds": [1], "userIds": [33], "price": 200}),
        ("/appointments", {"invitees": [{"personId": 1}, {"userId": 33}]}),
        ("/dealAttachments", {"dealId": 20}),
        ("/calls", {"personId": 1}),
        ("/textMessages", {"personId": 1}),
    ],
)
async def test_authorized_creation_preserves_existing_payload(scoped, path, body):
    client, _, calls, _ = scoped
    assert await client._post(path, body) == {"id": 90, **body}
    assert calls[-1] == ("POST", path, None, body)


async def test_real_tool_preview_and_write_then_reassignment_denial(scoped, writable):
    _, records, calls, _ = scoped
    args = {"person_id": 1, "expected_contact_name": "Assigned Client", "price": 200}
    result = await server.update_contact_profile(**args)
    assert result["status"] == "PREVIEW_ONLY_NO_WRITE"
    assert not any(call[0] != "GET" for call in calls)
    result = await server.update_contact_profile(**args, execute=True)
    assert result["status"] == "WRITE_COMPLETED_AND_RE_READ"
    assert records["/people/1"]["price"] == 200
    records["/people/1"]["assignedUserId"] = 7
    count = len(calls)
    with pytest.raises(PermissionError):
        await server.update_contact_profile(**args, execute=True)
    assert all(call[0] == "GET" for call in calls[count:])


@pytest.mark.parametrize("value", [None, 7, True, "", "33,7"])
async def test_missing_or_invalid_ownership_is_fail_closed(scoped, value):
    client, records, _, _ = scoped
    records["/people/1"]["assignedUserId"] = value
    with pytest.raises(PermissionError):
        await client.get_person(1)


@pytest.mark.parametrize("path", ["/people/1/../2", "/people/1?fields=allFields", "/people/-1", "/actionPlans"])
async def test_unrecognized_paths_and_destructive_actions_are_not_allowed(scoped, path):
    client, _, calls, _ = scoped
    with pytest.raises(PermissionError):
        await client._request("DELETE", path)
    assert calls == []


async def test_conflicting_expanded_and_legacy_links_fail_closed(scoped):
    client, records, _, _ = scoped
    records["/deals/20"]["peopleIds"] = [2]
    with pytest.raises(PermissionError):
        await client.get_deal(20)


async def test_parent_check_reused_only_inside_one_collection_read(scoped):
    client, records, calls, pages = scoped
    pages["/tasks"] = {0: {"tasks": [records["/tasks/10"], {**records["/tasks/10"], "id": 13}]}}
    assert len((await client.search_tasks())["tasks"]) == 2
    assert len([call for call in calls if call[1] == "/people/1"]) == 1
    records["/people/1"]["assignedUserId"] = 7
    assert (await client.search_tasks())["tasks"] == []


@pytest.mark.parametrize("path", ["/people", "/events"])
async def test_unexposed_creation_is_not_implicitly_authorized(scoped, path):
    client, _, calls, _ = scoped
    with pytest.raises(PermissionError):
        await client._post(path, {"assignedUserId": 33, "personId": 1})
    assert calls == []
