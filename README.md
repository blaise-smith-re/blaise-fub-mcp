# Blaise FUB MCP v2 — Read-Only + OAuth Protected

This version keeps the Follow Up Boss tool surface read-only and adds OAuth protection at the remote MCP boundary.

## Exposed tools
- `find_contact`
- `get_contact`
- `get_contact_events`
- `get_open_tasks`
- `get_stages`
- `get_active_deals`

## Security model

Claude -> OAuth access token -> protected MCP server -> server-side FUB credentials -> FUB API.

Claude never needs the FUB API key or FUB X-System-Key.

The server validates Auth0-issued RS256 access tokens and requires the `fub:read` scope. The Auth0 API/resource identifier must equal the final MCP resource URL exactly:

`https://YOUR-HOST/mcp`

Auth0's **Resource Parameter Compatibility Profile** must be enabled so MCP's RFC 8707 `resource` parameter maps to the API audience.

## Claude OAuth callbacks

Allow both of these callbacks in the Auth0 application:
- `https://claude.ai/api/mcp/auth_callback`
- `https://claude.com/api/mcp/auth_callback`

## Before deployment

1. Create Auth0 tenant.
2. Enable Auth0 Resource Parameter Compatibility Profile.
3. Deploy this server and obtain its final HTTPS origin.
4. In Auth0, create an API whose Identifier is the deployed MCP URL plus `/mcp`.
5. Add permission `fub:read` and enable offline access if using refresh tokens.
6. Create a Regular Web Application for Claude and allow the two Claude callback URLs.
7. Store all secrets only in the hosting platform's secret/environment manager.
8. Add the remote MCP URL to Claude Customize -> Connectors -> Add custom connector and use the Auth0 client ID/secret in Advanced settings.

## Production certification

Read-only first. Use one known FUB contact. Verify exact targeting before deeper reads. No write tools exist in v2.
