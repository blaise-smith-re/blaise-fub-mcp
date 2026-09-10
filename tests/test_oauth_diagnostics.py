"""No live credentials, Auth0 registration, or FUB calls in regression tests."""

from __future__ import annotations

import json

import httpx
import pytest

from oauth_diagnostics import CALLBACK_ID, CIMD, ISSUER, PRM, RESOURCE, SCOPES, assess, fetch_json, probe


def documents():
    return (
        {"resource": RESOURCE, "authorization_servers": [ISSUER], "scopes_supported": SCOPES},
        {
            "issuer": ISSUER,
            "authorization_endpoint": ISSUER + "authorize",
            "token_endpoint": ISSUER + "oauth/token",
            "registration_endpoint": ISSUER + "oidc/register",
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "client_id_metadata_document_supported": True,
        },
        {
            "client_id": CIMD,
            "application_type": "native",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "redirect_uris": [f"http://127.0.0.1/callback/{CALLBACK_ID}"],
        },
    )


def test_cimd_callback_matches_codex_0154_complete_resource_hash():
    assert CALLBACK_ID == "Msr2-imGFcgW"
    assert assess(*documents())["auto_cimd_metadata_ready"] is True


def test_oidc_scope_discovery_does_not_replace_required_resource_permissions():
    prm, metadata, cimd = documents()
    metadata["scopes_supported"] = ["openid", "profile", "offline_access"]
    result = assess(prm, metadata, cimd)
    assert result["authorization_server_scopes_cover_fub"] is False
    assert result["required_explicit_codex_scopes"] == ["fub:read", "fub:write"]
    assert result["checks"]["full_scopes_advertised"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("client_id_metadata_document_supported", False),
        ("token_endpoint_auth_methods_supported", ["client_secret_post"]),
        ("code_challenge_methods_supported", ["plain"]),
        ("issuer", "https://wrong-issuer.invalid/"),
        ("token_endpoint", "https://wrong-token.invalid/token"),
    ],
)
def test_discovery_mismatch_never_reports_cimd_ready(field, value):
    prm, metadata, cimd = documents()
    metadata[field] = value
    assert assess(prm, metadata, cimd)["auto_cimd_metadata_ready"] is False


def test_wrong_resource_missing_scope_and_wrong_callback_are_rejected():
    prm, metadata, cimd = documents()
    prm.update(resource="https://retired.invalid/mcp", scopes_supported=["fub:read"])
    cimd["redirect_uris"] = ["http://127.0.0.1/callback"]
    checks = assess(prm, metadata, cimd)["checks"]
    assert not checks["resource_matches_full_mcp"]
    assert not checks["full_scopes_advertised"]
    assert not checks["cimd_redirect_matches"]


def test_probe_is_get_only_bounded_and_does_not_echo_secret_fields():
    prm, metadata, cimd = documents()
    metadata["client_secret"] = "DO-NOT-PRINT"
    metadata["error_description"] = "DO-NOT-PRINT"
    destinations = []

    def handler(request):
        assert request.method == "GET"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        url = str(request.url)
        destinations.append(url)
        if url == RESOURCE:
            return httpx.Response(401, headers={"WWW-Authenticate": f'Bearer resource_metadata="{PRM}"'})
        if url == PRM:
            return httpx.Response(200, json=prm)
        if url == CIMD:
            return httpx.Response(200, json=cimd)
        assert url in {ISSUER + ".well-known/oauth-authorization-server", ISSUER + ".well-known/openid-configuration"}
        return httpx.Response(200, json=metadata)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        report = probe(client)
    assert len(destinations) == 5
    assert report["auto_cimd_metadata_ready"] is True
    assert "DO-NOT-PRINT" not in json.dumps(report)
    assert report["authentication_and_fub_access"].startswith("NOT_TESTED")


@pytest.mark.parametrize("response", [httpx.Response(302), httpx.Response(200, text="x" * 65537)])
def test_redirects_and_oversized_responses_fail_closed(response):
    with httpx.Client(transport=httpx.MockTransport(lambda request: response), follow_redirects=False) as client:
        with pytest.raises(ValueError):
            fetch_json(client, PRM)
