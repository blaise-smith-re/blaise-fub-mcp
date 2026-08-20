from __future__ import annotations

import os
from typing import Any

from pydantic import AnyHttpUrl
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from auth0_verifier import Auth0TokenVerifier
from fub_client import FUBClient


PUBLIC_BASE = os.environ["MCP_PUBLIC_URL"].rstrip("/")
AUTH0_DOMAIN = os.environ["AUTH0_DOMAIN"].strip().rstrip("/")
if not AUTH0_DOMAIN.startswith("http"):
    AUTH0_DOMAIN = f"https://{AUTH0_DOMAIN}"

mcp = FastMCP(
    "Blaise FUB Read-Only",
    stateless_http=True,
    json_response=True,
    instructions=(
        "Read-only access to Blaise Smith's Follow Up Boss account. "
        "Never infer that a write occurred. Never expose credentials. "
        "Target exact records before returning CRM facts."
    ),
    token_verifier=Auth0TokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(f"{AUTH0_DOMAIN}/"),
        resource_server_url=AnyHttpUrl(f"{PUBLIC_BASE}/mcp"),
        required_scopes=["fub:read"],
    ),
)


def _client() -> FUBClient:
    return FUBClient()


@mcp.tool()
async def find_contact(
    email: str | None = None,
    phone: str | None = None,
    name: str | None = None,
    stage: str | None = None,
    assigned_user_id: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find FUB contacts using one or more explicit search criteria. Read-only."""
    return await _client().find_people(
        email=email,
        phone=phone,
        name=name,
        stage=stage,
        assigned_user_id=assigned_user_id,
        limit=limit,
    )


@mcp.tool()
async def get_contact(person_id: int) -> dict[str, Any]:
    """Retrieve one FUB person by exact numeric person ID. Read-only."""
    return await _client().get_person(person_id)


@mcp.tool()
async def get_contact_events(person_id: int, limit: int = 50, next_token: str | None = None) -> dict[str, Any]:
    """Retrieve API-visible FUB events for one exact person ID. Read-only."""
    return await _client().get_events(person_id, limit=limit, next_token=next_token)


@mcp.tool()
async def get_open_tasks(person_id: int) -> dict[str, Any]:
    """Retrieve incomplete FUB tasks for one exact person ID. Read-only."""
    return await _client().get_open_tasks(person_id)


@mcp.tool()
async def get_stages() -> dict[str, Any]:
    """Retrieve the account's current FUB stage definitions. Read-only."""
    return await _client().get_stages()


@mcp.tool()
async def get_active_deals(person_id: int) -> dict[str, Any]:
    """Retrieve active FUB deals for one exact person ID. Read-only."""
    return await _client().get_deals(person_id)


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    main()
