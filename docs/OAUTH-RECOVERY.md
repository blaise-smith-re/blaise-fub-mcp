# Full MCP OAuth recovery and future-computer connection

Status: engineering proposal; live Auth0 recovery is not yet proven. No deployment,
tenant setting, client registration, business-policy change or FUB write follows
from this document. Preserve the original full-server tool and write controls.

## Architecture

Use one `blaise_fub_full` remote MCP at `https://blaise-fub-mcp.onrender.com/mcp`.
Auth0 issues audience-bound JWTs; Render validates them and retains all FUB
credentials. Codex stores its own OAuth credentials locally. A full-server
`fub:write` scope does not authorize a workflow to write. Lead Engine's existing
facade remains limited to `find_contact` / `get_contact` on source-backed shortlists.

The separate `blaise_fub_read_only` lane was retired by owner instruction on
2026-09-10. Its source, tests and earlier certification evidence remain historical;
do not recreate that Auth0 application or make new computers depend on it.

The preferred recovery is one administrator-imported **public native CIMD client**,
reused across computers. It is not a client-secret scheme. The exact document for
this MCP URL is:

`https://chatgpt.com/oauth/codex/Msr2-imGFcgW/client.json`

Auth0 supports manual CIMD registration. The native document uses PKCE and token
endpoint authentication `none`. Codex 0.154.0 supports it; its release-tag source
derives `Msr2-imGFcgW` from the full MCP URL. The document returned HTTP 200 during
this investigation and advertises native, `none`, authorization code/refresh token
grants and the matching portless loopback callbacks. Live Auth0 import, grant and
variable-port acceptance still require verification.

After tenant provisioning is verified, pin that **public URL** as
`mcp_servers.blaise_fub_full.oauth.client_id` in OS config. A configured client ID
takes precedence and skips client registration, so loss of CIMD advertisement
cannot silently fall back to DCR and create another application. All machines use
the same identity; their own OAuth tokens remain separate. The subordinate OS PR
must remain a proposal until the tenant can resolve this client.

For unpinned Codex Auto selection, the tenant metadata must advertise both
`client_id_metadata_document_supported: true` and token auth method `none`, with a
supported loopback callback. The deployed tenant currently omits the CIMD flag.
Do not add a fake flag to the Render resource metadata or proxy the issuer. Auth0
must implement and advertise its own capability.

## Tenant setup to review once dashboard access is available

1. Inspect existing apps and reuse an already imported matching CIMD, if present.
   Otherwise review one import of the exact URL above as a native third-party
   client. Do not create another `Codex Generic` DCR application.
2. Verify user-delegated access to the existing full MCP API, exact API identifier
   equal to the MCP URL, and `fub:read` / `fub:write` scope availability. Preserve
   user restrictions, consent and existing authorization controls. Do not grant
   machine-to-machine access, wildcard clients, or broad default third-party grants.
3. Review Auth0's Client ID Metadata Document Registration setting and Resource
   Parameter Compatibility Profile. The latter consumes RFC 8707 `resource` as
   audience instead of forwarding it upstream. Public discovery cannot prove its
   current private value. Review before changing either tenant-wide setting.
4. Inspect the actual Google social connection and sanitized failed-login details:
   provider client identity, callback allowlist, enabled connection/app mapping and
   development-key/custom-key mode. Never reveal or copy a client secret. Changing
   Google credentials is a human credential-entry operation, not an agent log step.
5. Verify native loopback port handling against the hosted document. Auth0 must
   accept the listener's variable port while matching host/path. Do not broaden
   callbacks with wildcards or disable issuer, PKCE, audience or state checks.

If this tenant cannot support the native CIMD document, the supported fallback is
one reusable, pre-registered **public native client** (`none`, PKCE S256) with a
non-secret client ID in Codex config. Inspect and reuse a suitable existing app;
review any necessary conversion or new registration first. If fixed callbacks are
required, register one exact server-specific URI and configure **both** callback URL
and listener port. Never invent a Codex `client_secret` option. A confidential
secret-based app is not this fallback. No cleanup scheduler or periodic client deletion.

## Operator-run connection procedure

The operator executes commands; Blaise only completes human authentication or
approves consequential tenant changes. Do not send him back to PowerShell.

1. Resolve the executable and invoke `--version` by absolute path. This machine has
   0.154.0 at `%LOCALAPPDATA%/Programs/OpenAI/Codex/bin/codex.exe`; the desktop task's
   inherited PATH initially selected bundled 0.153.0. Do not overwrite the app's
   bundled binary. Use the verified 0.154.0 path for acceptance checks.
2. Open the trusted OS checkout. Confirm the full endpoint and expected allowlist;
   disable the retired read-only entry. Apply the reviewed public-client config only
   after tenant provisioning. Keep credentials out of Git, Drive, transcripts and screenshots.
3. Run `python oauth_diagnostics.py` from this repository. It issues only five public
   GETs: MCP challenge, protected-resource metadata, two Auth0 discovery documents
   and the public CIMD. Exit 1 means Auto CIMD metadata is not ready; it is not proof
   the configured public client cannot work. Exit 2 means a bounded retrieval failed.
   It does not inspect tenant permissions, create applications or prove FUB access.
4. Preserve working credentials. Only when the operator is ready for the controlled
   clean-state acceptance, run the supported `codex mcp logout blaise_fub_full`
   if relevant state must be cleared, then `codex mcp login blaise_fub_full` once.
   Capture only allowlisted, sanitized request facts; never save a raw auth URL or token.
   An expired callback needs a fresh transaction, not replay of an old link.
5. Restart a Codex process in the trusted project. Check `codex mcp list` and actual
   MCP initialization/tool enumeration. `o_auth` in the list alone is not a live
   authentication or tool-usability certificate.
6. Perform one exact `find_contact` read: the approved named target, limit 3. Do not
   scan stages, geography, the full CRM or create a contact. Record minimal success
   and match status privately; no CRM body in Git or this diagnostic report.
7. Repeat restart/reconnect and one controlled login with the same public client;
   independently compare the Auth0 application inventory before/after. No application
   growth and unchanged public client identity are required. Also verify credential
   persistence and refresh behavior; a callback success alone is insufficient.

## Evidence required before calling this fixed

- Exact Google/Auth0 failure cause from provider error/request evidence; distinguish
  unknowns from verified facts. A generic 401 is not a diagnosis.
- Successful clean login, separate-process reconnect and expected tool inventory.
- One exact read, zero FUB writes and no broad discovery.
- No new client on repeat login, verified by Auth0 readback.
- Tenant changes, approvals and effective metadata independently read back.

The saved Lead Engine checkpoint is outside this repository and PR #6 is untouched.
After authentication succeeds it can resume its prepared exact relationship lookup
without repeating Matrix. This infrastructure task's exact read can satisfy that
lookup if the same target, board identity and facade rules are reconciled; do not
claim the saved board was updated unless separately read back.

## Primary references

- [Codex MCP OAuth registration and callbacks](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [Codex 0.154.0 registration implementation](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/rmcp-client/src/oauth_client_registration.rs)
- [Codex configured-client implementation](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/rmcp-client/src/perform_oauth_login.rs)
- [Auth0 manual CIMD registration](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd)
- [Auth0 resource compatibility profile](https://auth0.com/ai/docs/mcp/guides/resource-param-compatibility-profile)
- [Native loopback redirects, RFC 8252 section 7.3](https://www.rfc-editor.org/rfc/rfc8252#section-7.3)
