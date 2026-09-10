"""Credential-free, GET-only preflight for the deployed FUB OAuth chain.

This is an operator diagnostic, not an authorization proxy or a login retry loop.
It never reads credential stores, registers clients, or calls a FUB tool.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

RESOURCE = "https://blaise-fub-mcp.onrender.com/mcp"
ISSUER = "https://dev-46mx1synzdk7ancf.us.auth0.com/"
PRM = "https://blaise-fub-mcp.onrender.com/.well-known/oauth-protected-resource/mcp"
CALLBACK_ID = base64.urlsafe_b64encode(hashlib.sha256(RESOURCE.encode()).digest()[:9]).decode()
CIMD = f"https://chatgpt.com/oauth/codex/{CALLBACK_ID}/client.json"
SCOPES = ["fub:read", "fub:write"]
CODEX_SCOPES = [*SCOPES, "offline_access"]
METADATA_FIELDS = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "registration_endpoint",
    "scopes_supported",
    "token_endpoint_auth_methods_supported",
    "code_challenge_methods_supported",
    "client_id_metadata_document_supported",
    "authorization_response_iss_parameter_supported",
)


def public_url(value: Any) -> bool:
    """Only simple public HTTPS URLs can enter the diagnostic report."""
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not any((parsed.username, parsed.password, parsed.query, parsed.fragment))
    )


def project_metadata(document: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in METADATA_FIELDS:
        if key not in document:
            continue
        value = document[key]
        if key == "issuer" or key.endswith("_endpoint"):
            result[key] = value if public_url(value) else "INVALID_PUBLIC_URL"
        elif isinstance(value, bool):
            result[key] = value
        elif isinstance(value, list):
            result[key] = [v for v in value if isinstance(v, str) and re.fullmatch(r"[a-zA-Z0-9_:.-]{1,80}", v)]
    return result


def assess(prm: dict[str, Any], metadata: dict[str, Any], cimd: dict[str, Any]) -> dict[str, Any]:
    expected_redirect = f"http://127.0.0.1/callback/{CALLBACK_ID}"
    checks = {
        "resource_matches_full_mcp": prm.get("resource") == RESOURCE,
        "authorization_server_matches": prm.get("authorization_servers") == [ISSUER],
        "full_scopes_advertised": set(SCOPES).issubset(prm.get("scopes_supported", [])),
        "issuer_matches": metadata.get("issuer") == ISSUER,
        "authorization_endpoint_matches": metadata.get("authorization_endpoint") == ISSUER + "authorize",
        "token_endpoint_matches": metadata.get("token_endpoint") == ISSUER + "oauth/token",
        "pkce_s256_supported": "S256" in metadata.get("code_challenge_methods_supported", []),
        "public_client_auth_supported": "none" in metadata.get("token_endpoint_auth_methods_supported", []),
        "cimd_advertised": metadata.get("client_id_metadata_document_supported") is True,
        "cimd_identity_matches": cimd.get("client_id") == CIMD,
        "cimd_native_public_pkce_client": (
            cimd.get("application_type") == "native"
            and cimd.get("token_endpoint_auth_method") == "none"
            and "authorization_code" in cimd.get("grant_types", [])
        ),
        "cimd_redirect_matches": expected_redirect in cimd.get("redirect_uris", []),
    }
    return {
        "checks": checks,
        "auto_cimd_metadata_ready": all(checks.values()),
        "configured_client_skips_registration": True,
        # Codex 0.154's discovered AS scopes can differ from this resource's
        # permissions. Pin resource scopes in the server configuration instead.
        "required_explicit_codex_scopes": CODEX_SCOPES.copy(),
        "authorization_server_scopes_cover_fub": set(SCOPES).issubset(metadata.get("scopes_supported", [])),
        "expected_cimd_client_id": CIMD,
        "expected_loopback_callback_without_port": expected_redirect,
        "dcr_endpoint_present": public_url(metadata.get("registration_endpoint")),
        "tenant_registration_grant_connection_and_resource_profile": "NOT_VERIFIED_BY_PUBLIC_METADATA",
        "authentication_and_fub_access": "NOT_TESTED_BY_THIS_GET_ONLY_PREFLIGHT",
    }


def fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
    # All destinations are fixed public discovery documents. Never follow redirects,
    # forward cookies/Authorization, or print arbitrary response bodies/errors.
    with client.stream("GET", url) as response:
        if response.status_code != 200:
            raise ValueError("public_metadata_http_failure")
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > 65536:
                raise ValueError("public_metadata_too_large")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("public_metadata_not_object")
    return data


def probe(client: httpx.Client) -> dict[str, Any]:
    with client.stream("GET", RESOURCE) as response:
        status = response.status_code
        challenge = response.headers.get("www-authenticate", "")
    prm = fetch_json(client, PRM)
    metadata = fetch_json(client, ISSUER + ".well-known/oauth-authorization-server")
    oidc = fetch_json(client, ISSUER + ".well-known/openid-configuration")
    cimd = fetch_json(client, CIMD)
    result = assess(prm, metadata, cimd)
    result["checks"]["unauthenticated_mcp_is_401"] = status == 401
    result["checks"]["challenge_points_to_expected_metadata"] = f'resource_metadata="{PRM}"' in challenge
    result["checks"]["oauth_and_oidc_metadata_agree"] = project_metadata(metadata) == project_metadata(oidc)
    result["auto_cimd_metadata_ready"] = all(result["checks"].values())
    return {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "mode": "PUBLIC_GET_ONLY_NO_REGISTRATION_NO_FUB_CALL",
        "mcp_status": status,
        "protected_resource_metadata_url": PRM,
        "authorization_server_metadata": project_metadata(metadata),
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            report = probe(client)
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "PREFLIGHT_FAILED", "detail": "No response body or credentials logged."}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["auto_cimd_metadata_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
