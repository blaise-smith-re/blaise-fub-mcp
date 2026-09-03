# Read-Only Real Estate OS Endpoint

## Purpose

`readonly_server.py` is the live-certification surface for the Real Estate OS. It is deliberately separate from
the full operator server so the client can be given exactly six FUB read tools and only the `fub:read` OAuth scope.
This is an activation boundary, not the final automation ceiling.

## Exposed tools

1. `get_contact`
2. `get_contact_events`
3. `get_contact_notes`
4. `get_contact_appointments`
5. `search_tasks`
6. `get_open_tasks`

No mutation, message sending, deletion, scheduling, or account-configuration tool is registered on this endpoint.

## Deployment

Deploy the same private repository as a second web service with:

- Build command: `pip install .`
- Start command: `python readonly_server.py`
- Health/resource path: `/mcp`

Set these environment variables in the hosting control plane; do not commit their values:

- `FUB_API_KEY`
- `FUB_X_SYSTEM`
- `FUB_X_SYSTEM_KEY`
- `FUB_BASE_URL`
- `MCP_PUBLIC_URL` — the public base URL of the read-only service
- `AUTH0_DOMAIN`
- `AUTH0_AUDIENCE` — optional; set this to the existing Auth0 API audience to reuse its access-token audience

Authorize the client for `fub:read` only. Never grant `fub:write` to this endpoint.

## Live certification

Use synthetic or explicitly approved records and verify all of the following before marking the OS adapter live:

- The advertised inventory is exactly the six tools above.
- A token with `fub:read` can call each tool.
- A token without `fub:read` is rejected.
- Exact person IDs bind contact, event, note, appointment, and open-task results to the intended record.
- Task search refuses unbounded or partial retrieval and uses `America/Chicago` calendar dates.
- Completeness metadata reports no omitted matching task pages.
- Before-and-after evidence shows zero FUB effects after the full six-operation pass.

Until every item passes, keep the Real Estate OS adapter staged and its live status on HOLD.

