"""Attachment links use the registered-system API, without modifying deal fields."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import server
from fub_client import FUBClient


@pytest.fixture
def attachments(monkeypatch):
    deal = {"id": 90, "name": "Example deal", "people": [{"id": 12}], "commissionValue": 9000}
    saved = {
        "id": 55,
        "dealId": 90,
        "uri": "https://drive.google.com/file/d/example/view",
        "fileName": "Executed agreement.pdf",
        "fileSize": 123,
    }
    client = SimpleNamespace(
        get_deal=AsyncMock(side_effect=lambda _: deepcopy(deal)),
        create_deal_attachment=AsyncMock(return_value=deepcopy(saved)),
        get_deal_attachment=AsyncMock(return_value=deepcopy(saved)),
        update_deal=AsyncMock(),
    )
    monkeypatch.setattr(server, "_client", lambda: client)
    return client, deal


ARGS = {
    "deal_id": 90,
    "expected_deal_name": "Example deal",
    "expected_person_id": 12,
    "attachment_uri": "https://drive.google.com/file/d/example/view",
    "attachment_file_name": "Executed agreement.pdf",
    "attachment_file_size": 123,
}


async def test_preview_has_no_write(attachments):
    client, _ = attachments
    result = await server.update_contact_deal(**ARGS)
    assert result["status"] == "PREVIEW_ONLY_NO_WRITE"
    client.create_deal_attachment.assert_not_called()


async def test_attachment_is_verified_without_putting_deal(attachments, writable):
    client, _ = attachments
    result = await server.update_contact_deal(**ARGS, execute=True)
    assert result["status"] == "ATTACHMENT_CREATED_AND_RE_READ"
    assert result["attachment_type"] == "EXTERNAL_FILE_LINK"
    client.get_deal_attachment.assert_awaited_once_with(55)
    client.update_deal.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"expected_person_id": 99},
        {"expected_deal_name": "Wrong deal"},
        {"price": 300000},
        {"attachment_uri": "http://localhost/private"},
        {"attachment_uri": "https://drive.google.com/file/d/example/view?token=secret"},
        {"attachment_file_name": "../private.pdf"},
        {"attachment_file_size": -1},
        {"attachment_uri": None},
        {"attachment_file_name": ""},
    ],
)
async def test_invalid_target_or_file_rejected(attachments, writable, change):
    client, _ = attachments
    with pytest.raises(ValueError):
        await server.update_contact_deal(**(ARGS | change), execute=True)
    client.create_deal_attachment.assert_not_called()


async def test_write_scope_required(attachments, monkeypatch):
    client, _ = attachments
    monkeypatch.setattr(server, "get_access_token", lambda: None)
    with pytest.raises(PermissionError):
        await server.update_contact_deal(**ARGS, execute=True)
    client.create_deal_attachment.assert_not_called()


async def test_wrong_attachment_readback_fails(attachments, writable):
    client, _ = attachments
    client.get_deal_attachment.return_value["dealId"] = 99
    result = await server.update_contact_deal(**ARGS, execute=True)
    assert result["status"] == "ATTACHMENT_VERIFICATION_FAILED"


async def test_deal_mutation_is_reported(attachments, writable):
    client, deal = attachments
    client.get_deal.side_effect = [deepcopy(deal), deal | {"commissionValue": 0}]
    result = await server.update_contact_deal(**ARGS, execute=True)
    assert result["status"] == "ATTACHMENT_VERIFICATION_FAILED"
    assert result["unexpected_deal_changes"] == ["commissionValue"]


async def test_missing_id_does_not_retry(attachments, writable):
    client, _ = attachments
    client.create_deal_attachment.return_value = {}
    result = await server.update_contact_deal(**ARGS, execute=True)
    assert result["status"] == "ATTACHMENT_VERIFICATION_FAILED"
    client.create_deal_attachment.assert_awaited_once()


async def test_http_adapter_paths(monkeypatch):
    client = FUBClient()
    post, get = AsyncMock(return_value={"id": 55}), AsyncMock(return_value={"id": 55})
    monkeypatch.setattr(client, "_post", post)
    monkeypatch.setattr(client, "_get", get)
    body = {"dealId": 90, "uri": ARGS["attachment_uri"], "fileName": "Example.pdf"}
    await client.create_deal_attachment(body)
    await client.get_deal_attachment(55)
    post.assert_awaited_once_with("/dealAttachments", body)
    get.assert_awaited_once_with("/dealAttachments/55")
