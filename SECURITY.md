# Security controls

## FUB upstream secrets
- FUB_API_KEY: server-side secret only.
- FUB_X_SYSTEM_KEY: server-side secret only.
- Never log Authorization headers or secret values.

## MCP boundary
- Remote MCP access requires an OAuth Bearer token.
- Tokens are validated against the configured Auth0 issuer and the exact MCP resource audience.
- `fub:read` is required for every MCP call.
- The public MCP endpoint must never be deployed without the OAuth verifier enabled.

## Read-only v2
No FUB create/update/delete tool exists.

## Exact targeting
Record-specific reads require an explicit numeric person ID. Search returns a small result set first.

## No false completion
The connector must never claim a FUB write occurred because v2 contains no write tool.
