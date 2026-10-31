"""Transport allocation regressions without network access or real credentials."""

import asyncio
import ssl

import httpx
import pytest

import fub_client


@pytest.fixture(autouse=True)
def reset_context():
    fub_client._tls_context.cache_clear()
    yield
    fub_client._tls_context.cache_clear()


@pytest.mark.parametrize(
    "cert_file,cert_dir,expected",
    [
        (None, None, "default"),
        ("custom.pem", "custom-dir", "file"),
        (None, "custom-dir", "dir"),
    ],
)
def test_one_verified_context_preserves_httpx_ca_selection(monkeypatch, cert_file, cert_dir, expected):
    for name, value in [("SSL_CERT_FILE", cert_file), ("SSL_CERT_DIR", cert_dir)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    calls = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def create(**kwargs):
        calls.append(kwargs)
        return context

    monkeypatch.setattr(fub_client.ssl, "create_default_context", create)
    for _ in range(100):
        assert fub_client._tls_context() is context
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    argument = {"file": "cafile", "dir": "capath", "default": "cafile"}[expected]
    value = {"file": cert_file, "dir": cert_dir, "default": fub_client.certifi.where()}[expected]
    assert calls == [{argument: value}]  # exactly one CA-store allocation


@pytest.mark.parametrize("outcome", ["ok", "http_error", "cancel"])
async def test_requests_share_only_tls_context_and_close_clients(monkeypatch, outcome):
    original_client = httpx.AsyncClient
    clients, contexts, requests = [], [], []

    async def handler(request):
        requests.append(request)
        if outcome == "cancel":
            raise asyncio.CancelledError()
        return httpx.Response(503 if outcome == "http_error" else 200, json={"id": 33})

    def client_factory(**kwargs):
        contexts.append(kwargs["verify"])
        client = original_client(**kwargs, transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    monkeypatch.setattr(fub_client.httpx, "AsyncClient", client_factory)
    for _ in range(3):
        client = fub_client.FUBClient()
        if outcome == "ok":
            assert await client._get("/users/33") == {"id": 33}
        else:
            with pytest.raises(asyncio.CancelledError if outcome == "cancel" else httpx.HTTPStatusError):
                await client._get("/users/33")
    assert len(requests) == 3  # fresh read each time; no response cache or automatic retry
    assert len({id(context) for context in contexts}) == 1
    assert all(client.is_closed for client in clients)
    assert all(request.headers["X-System"] == "test-system" for request in requests)
    assert all(request.headers["Authorization"].startswith("Basic ") for request in requests)
