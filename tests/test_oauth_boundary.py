"""Preserve JWT and full-server scope controls while changing client registration."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import server
from auth0_verifier import Auth0TokenVerifier


@pytest.fixture
def verifier(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    checker = Auth0TokenVerifier()
    monkeypatch.setattr(checker.jwks, "get_signing_key_from_jwt", lambda token: SimpleNamespace(key=key.public_key()))
    now = int(time.time())
    claims = {
        "iss": checker.issuer,
        "aud": checker.audience,
        "iat": now,
        "exp": now + 300,
        "scope": "fub:read fub:write",
        "sub": "synthetic-user",
        "azp": "https://chatgpt.com/oauth/codex/Msr2-imGFcgW/client.json",
    }
    return checker, key, claims


async def test_cimd_url_client_identity_is_accepted_without_secrets(verifier):
    checker, key, claims = verifier
    result = await checker.verify_token(jwt.encode(claims, key, algorithm="RS256"))
    assert result is not None
    assert result.client_id == claims["azp"]
    assert result.resource == checker.audience
    assert result.scopes == ["fub:read", "fub:write"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "https://other-issuer.invalid/"),
        ("aud", "https://other-resource.invalid/mcp"),
        ("exp", 1),
    ],
)
async def test_registration_change_does_not_relax_token_checks(verifier, field, value):
    checker, key, claims = verifier
    claims[field] = value
    assert await checker.verify_token(jwt.encode(claims, key, algorithm="RS256")) is None


async def test_wrong_signature_rejected(verifier):
    checker, _, claims = verifier
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert await checker.verify_token(jwt.encode(claims, other, algorithm="RS256")) is None


def test_full_server_retains_existing_scope_boundary(monkeypatch):
    assert server.mcp.settings.auth is not None
    assert server.mcp.settings.auth.required_scopes == ["fub:read", "fub:write"]
    monkeypatch.setattr(server, "get_access_token", lambda: SimpleNamespace(scopes=["fub:read"]))
    with pytest.raises(PermissionError, match="fub:write"):
        server._require_write_scope()
