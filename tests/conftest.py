"""Test environment setup.

server.py reads several environment variables at import time (MCP public
URL, Auth0 domain, FUB credentials). Set safe placeholder values before any
test module imports it, so the whole suite runs with no real credentials and
no network access.
"""

from __future__ import annotations

import os

os.environ.setdefault("FUB_API_KEY", "test-fub-api-key")
os.environ.setdefault("FUB_X_SYSTEM", "test-system")
os.environ.setdefault("FUB_X_SYSTEM_KEY", "test-system-key")
os.environ.setdefault("FUB_BASE_URL", "https://api.followupboss.com/v1")
os.environ.setdefault("MCP_PUBLIC_URL", "https://blaise-fub-mcp.invalid.test")
os.environ.setdefault("AUTH0_DOMAIN", "test-tenant.us.auth0.test")

import pytest  # noqa: E402
from fake_fub import FakeFUBClient  # noqa: E402

import server  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    """A FakeFUBClient wired in as server._client()'s return value."""
    client = FakeFUBClient()
    monkeypatch.setattr(server, "_client", lambda: client)
    return client


@pytest.fixture
def writable(monkeypatch):
    """Bypass the OAuth fub:write scope check for tests exercising execute=True."""
    monkeypatch.setattr(server, "_require_write_scope", lambda: None)
