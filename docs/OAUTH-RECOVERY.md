# Full MCP OAuth recovery and future-computer connection

Status: fresh login, refresh issuance/rotation/renewal, new-process tools and a
bounded read verified. Owner-approved API offline access and native-client refresh
protection are applied. No application, Render deployment, business policy or FUB
record was created or changed. Historical Google 401 cause remains unresolved.
Lead Engine PR #6 is untouched. The evidence ledger is
[OAUTH-INVESTIGATION-2026-09-10.md](OAUTH-INVESTIGATION-2026-09-10.md).

## Selected architecture

Use one `blaise_fub_full` remote MCP. Auth0 issues audience-bound JWTs; Render
validates them and retains the FUB credentials. Codex stores OAuth credentials
locally. A `fub:write` scope grants server capability, not workflow authorization.
Lead Engine retains its exact shortlist-only `find_contact` / `get_contact` facade.
The owner retired the separate read-only OAuth lane on 2026-09-10; its source,
tests and historical certification remain preserved.

Reuse the existing **Blaise Codex FUB MCP public native application**. Codex
0.154.0 explicitly supports a configured public client ID without a client secret;
it skips registration entirely. New computers reuse the identity and receive their
own tokens. This prevents DCR growth without periodic client deletion.

```toml
[mcp_servers.blaise_fub_full]
url = "https://blaise-fub-mcp.onrender.com/mcp"
scopes = ["fub:read", "fub:write", "offline_access"]
# Retain the OS's existing enabled_tools and other server settings.

[mcp_servers.blaise_fub_full.oauth]
client_id = "zVnhfzFBR7aX6np3JSAXf0Cnohu8fWuH"
callback_url = "http://127.0.0.1:57185/callback/Msr2-imGFcgW"
callback_port = 57185
```

The dashboard verified native type, Google enabled, both full-MCP delegated
permissions and this exact callback. Both callback URL and listener port must be
configured. If occupied, identify the process; do not kill unrelated processes or
randomize the callback. The second existing allowed URI uses port 10230 with the
same path; switching requires changing both port settings consistently.

Explicit scopes are essential on Codex 0.154.0. A controlled request without them
selected the generic OIDC discovery scopes and omitted both FUB permissions. It
was stopped before browser navigation. The corrected request contained exactly
`fub:read fub:write`, one full-MCP resource value and PKCE S256. This verified scope
defect is separate from the earlier Google 401, whose precise cause is unresolved.
The owner subsequently approved adding only `offline_access`. The full API now
has Allow Offline Access ON, with the same 86,400-second access-token lifetime.
The existing native client already supported the refresh grant. Rotation is ON,
idle expiration is 604,800 seconds (7 days), maximum expiration is 2,592,000 seconds
(30 days), and overlap is 5 seconds for network retries. Reuse detection applies
outside that narrow overlap. No MRRT, new FUB permission or client secret was added.

Refresh issuance was verified without printing credentials. A controlled local
cache-expiry test then caused Codex's own OAuth client to exchange the refresh
token: both access and refresh tokens changed, scopes/client remained the same,
the new expiry was in the future, and Auth0 recorded the refresh exchange.
This was a real renewal with local cached expiry made due, not a 24-hour elapsed
test. Neither the server lifetime, access-token contents nor system clock changed.

Durable authentication is bounded, not permanent immunity from sign-in. Expect
fresh human login after seven days of refresh inactivity, the thirty-day family
maximum, revocation or other provider security events. Reuse the same pinned
client for that login; never create another client to repair expired credentials.

## CIMD evaluation

Codex Auto supports CIMD when the authorization server advertises
`client_id_metadata_document_supported: true`, public token auth `none`, and a
compatible native loopback callback. Auth0 documents manual CIMD import. The
public document for this exact resource returned HTTP 200 with native/none,
authorization-code and refresh-token grants, and matching portless callbacks:

`https://chatgpt.com/oauth/codex/Msr2-imGFcgW/client.json`

This tenant's CIMD registration flag is OFF and discovery omits it. DCR is ON.
Resource Parameter Compatibility Profile is already ON. The application list
showed five visible rows, including two Codex Generic clients, while the creation
UI reported the limit of ten applications and SSO integrations. No matching CIMD
client was visible. These are different counts; do not equate visible apps with
all quota entities.

Reusing the existing native client avoids a new import, capacity change or
tenant-wide feature change. This does not establish that Auth0 is incompatible
with CIMD. A future reviewed migration could import the public document, verify
grants and variable-port callback handling, then pin its public URL. Never fake a
CIMD flag in resource metadata or add an issuer proxy to imply unsupported behavior.

## Operator-run procedure

The operator executes diagnostics and commands; Blaise only completes human
authentication or approves consequential tenant changes.

1. Resolve and verify Codex by absolute path. This Windows machine has 0.154.0 at
   `%LOCALAPPDATA%/Programs/OpenAI/Codex/bin/codex.exe`; the desktop task inherited
   bundled 0.153.0. Use the verified executable without replacing the bundled file.
2. Start from the trusted OS checkout and verify the single full server, pinned
   public client, exact callback/port, explicit scopes and retained tool allowlist.
   The OS configuration change is a separate review PR, not Lead Engine PR #6.
3. Run `python oauth_diagnostics.py`. It issues five bounded public GETs and never
   reads credentials, registers clients or calls FUB. Exit 1 means Auto CIMD is not
   ready, not that this configured native client cannot work. Exit 2 is retrieval
   failure. Inspect explicit-scope advice as well as metadata consistency.
4. Preserve working credentials. If clean relevant state is necessary, use the
   supported `codex mcp logout blaise_fub_full` only when ready, then run
   `codex mcp login blaise_fub_full` once. Capture sanitized request facts only.
   Never retain raw auth URLs, state, codes, tokens, cookies or secrets. Expired
   transactions need fresh login, never replay of an old authorization link.
5. Bring the Google account chooser forward. Auth0 dashboard administration and
   MCP user sign-in can use different identities; let Blaise select the right
   account. No browser token extraction or bypass of MFA/provider controls.
6. Restart a Codex process in the trusted project. Inspect `codex mcp list` plus
   live MCP initialization/tool enumeration. An `o_auth` label alone is not proof.
7. Perform one approved exact `find_contact`, limit 3. No stage/geography/CRM scan,
   writes or new contact. Keep record bodies out of Git and diagnostic reports.
8. Repeat reconnect and controlled login with the same client. Independently
   compare Auth0 inventory/logs: no new DCR client, same configured identity.
   Verify credential persistence and report refresh lifetime limitations honestly.
   For renewal acceptance, use a scoped credential-aware operator harness that
   changes only this connection's cached expiry under Codex's credential/store
   locks. Retain encrypted storage and ACLs, never write plaintext backups, and
   let Codex perform the actual exchange and persist the rotated credential.
   Do not replay a superseded refresh token as a live reuse-detection test.

## Google 401 evidence boundary

The generic Google 401 did not identify a malformed parameter. Historical FUB and
Auth0 dashboard handoffs used different Google clients/callbacks; neither observed
Google request included `resource`. Tenant logs now verify use of Auth0 Google
development keys, but that warning does not prove the 401 cause. Auth0 documents
development keys as test-only with limitations. Production Google credentials
require a separately reviewed change and human secret entry; no such change has
been made. Our actual native-client refresh test passed with this connection.
Do not blame account selection, loopback URI, resource or
development keys as the exact cause without provider evidence.

## Acceptance and checkpoint

Fresh login, real renewal with rotation, subsequent process restart, all 38 tools,
one bounded read and unchanged application inventory passed. This is ready for
Work review of durable native-client authentication. A claim that the historical
Google 401's exact malformed parameter was fixed is not supported. The unchanged
development-key connection is an explicit production-hardening limitation.

The saved Lead Engine checkpoint can resume its prepared Anthony Nguyen lookup
after authentication is proven without repeating Matrix. This task does not edit
the checkpoint or board. An exact read can satisfy the pending relationship check
only after target identity and the existing facade rules are reconciled.

## Primary references

- [Codex 0.154 registration selection](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/rmcp-client/src/oauth_client_registration.rs)
- [Codex configured-client login](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/rmcp-client/src/perform_oauth_login.rs)
- [Codex 0.154 CLI scope precedence](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/cli/src/mcp_cmd.rs)
- [Auth0 manual CIMD registration](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd)
- [Auth0 resource compatibility](https://auth0.com/ai/docs/mcp/guides/resource-param-compatibility-profile)
- [Auth0 development-key limitations](https://auth0.com/docs/authenticate/identity-providers/social-identity-providers/devkeys)
- [Auth0 refresh rotation and overlap](https://auth0.com/docs/secure/tokens/refresh-tokens/configure-refresh-token-rotation)
- [Auth0 bounded refresh expiration](https://auth0.com/docs/secure/tokens/refresh-tokens/configure-refresh-token-expiration)
- [Native loopback redirects](https://www.rfc-editor.org/rfc/rfc8252#section-7.3)
