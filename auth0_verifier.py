from __future__ import annotations

import os
from typing import Any

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier


class Auth0TokenVerifier(TokenVerifier):
    """Validate Auth0-issued JWT access tokens for the MCP resource server."""

    def __init__(self) -> None:
        domain = os.environ["AUTH0_DOMAIN"].strip().rstrip("/")
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        self.issuer = f"{domain}/"
        self.audience = os.environ["MCP_PUBLIC_URL"].rstrip("/") + "/mcp"
        self.jwks = PyJWKClient(f"{domain}/.well-known/jwks.json")

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = self.jwks.get_signing_key_from_jwt(token).key
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except Exception:
            return None

        raw_scope = claims.get("scope", "")
        scopes = raw_scope.split() if isinstance(raw_scope, str) else list(raw_scope or [])
        client_id = str(claims.get("azp") or claims.get("client_id") or "claude")
        expires_at = int(claims["exp"]) if claims.get("exp") is not None else None
        subject = str(claims["sub"]) if claims.get("sub") is not None else None

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=expires_at,
            resource=self.audience,
            subject=subject,
            claims={"iss": claims.get("iss")},
        )
