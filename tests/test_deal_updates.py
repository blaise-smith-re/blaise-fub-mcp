"""Regression coverage using FUB's expanded deal response, with synthetic records."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import server


@pytest.fixture
def deal_client(monkeypatch):
    record = {
        "id": 90,
        "name": "Example buyer deal",
        "people": [{"id": 12}],
        "users": [{"id": 7}],
        "price": None,
        "stageId": 18,
    }

    async def get_deal(_):
        return deepcopy(record)

    async def update_deal(_, payload):
        record.update(payload)

    client = SimpleNamespace(
        get_deal=AsyncMock(side_effect=get_deal),
        update_deal=AsyncMock(side_effect=update_deal),
        get_deal_custom_fields=AsyncMock(return_value={"dealCustomFields": []}),
    )
    monkeypatch.setattr(server, "_client", lambda: client)
    return client, record


ARGS = {"deal_id": 90, "expected_deal_name": "Example buyer deal", "expected_person_id": 12}


async def test_expanded_people_preview_and_live_update(deal_client, writable):
    client, record = deal_client
    fields = {
        "price": 300000,
        "commission_value": 9000,
        "agent_commission": 7200,
        "team_commission": 1800,
        "mutual_acceptance_date": "2026-09-01",
    }
    preview = await server.update_contact_deal(**ARGS, **fields)
    assert preview["status"] == "PREVIEW_ONLY_NO_WRITE"
    client.update_deal.assert_not_called()
    result = await server.update_contact_deal(**ARGS, **fields, execute=True)
    assert result["status"] == "WRITE_COMPLETED_AND_RE_READ"
    assert record["commissionValue"] == 9000
    assert record["agentCommission"] == 7200
    assert record["teamCommission"] == 1800
    assert record["people"] == [{"id": 12}]
    assert record["users"] == [{"id": 7}]
    assert record["stageId"] == 18


@pytest.mark.parametrize(
    "links", [{"people": [{"id": 99}]}, {"people": []}, {"people": [{"id": 12}], "peopleIds": [99]}]
)
async def test_missing_wrong_or_conflicting_contact_rejected(deal_client, writable, links):
    client, record = deal_client
    record.update(links)
    with pytest.raises(ValueError):
        await server.update_contact_deal(**ARGS, price=300000, execute=True)
    client.update_deal.assert_not_called()


async def test_legacy_ids_still_supported(deal_client):
    _, record = deal_client
    del record["people"]
    record["peopleIds"] = ["12"]
    assert (await server.update_contact_deal(**ARGS, price=300000))["status"] == "PREVIEW_ONLY_NO_WRITE"


@pytest.mark.parametrize("change", [{"id": 91}, {"name": "Different deal"}])
async def test_stale_identity_rejected(deal_client, writable, change):
    client, record = deal_client
    record.update(change)
    with pytest.raises(ValueError):
        await server.update_contact_deal(**ARGS, price=300000, execute=True)
    client.update_deal.assert_not_called()


@pytest.mark.parametrize("amount", [-1, 3.5, True])
async def test_invalid_commission_rejected(deal_client, writable, amount):
    client, _ = deal_client
    with pytest.raises(ValueError):
        await server.update_contact_deal(**ARGS, commission_value=amount, execute=True)
    client.update_deal.assert_not_called()


async def test_zero_commission_and_omitted_fields(deal_client, writable):
    client, record = deal_client
    record["teamCommission"] = 1800
    await server.update_contact_deal(**ARGS, agent_commission=0, execute=True)
    assert client.update_deal.call_args.args[1] == {"agentCommission": 0}
    assert record["teamCommission"] == 1800


async def test_ignored_api_field_is_not_reported_as_success(deal_client, writable):
    client, _ = deal_client
    client.update_deal.side_effect = None
    result = await server.update_contact_deal(**ARGS, commission_value=9000, execute=True)
    assert result["status"] == "WRITE_VERIFICATION_FAILED"
    assert "commissionValue" in result["mismatches"]


async def test_scope_still_required(deal_client, monkeypatch):
    client, _ = deal_client
    monkeypatch.setattr(server, "get_access_token", lambda: None)
    with pytest.raises(PermissionError):
        await server.update_contact_deal(**ARGS, price=300000, execute=True)
    client.update_deal.assert_not_called()


async def test_custom_fields_cannot_override_contact_links(deal_client, writable):
    client, _ = deal_client
    with pytest.raises(ValueError, match="Unknown deal custom field"):
        await server.update_contact_deal(**ARGS, custom_fields={"peopleIds": [99]}, execute=True)
    client.update_deal.assert_not_called()


async def test_datetime_readback_matches_calendar_date(deal_client, writable):
    client, record = deal_client

    async def update(_, payload):
        record.update(payload)
        record["mutualAcceptanceDate"] += "T00:00:00Z"

    client.update_deal.side_effect = update
    result = await server.update_contact_deal(**ARGS, mutual_acceptance_date="2026-09-01", execute=True)
    assert result["status"] == "WRITE_COMPLETED_AND_RE_READ"
