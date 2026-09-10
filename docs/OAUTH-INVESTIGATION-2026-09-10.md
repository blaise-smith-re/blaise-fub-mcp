# OAuth investigation — 2026-09-10

**Current result: tenant-authentication blocker; permanent recovery not yet proven.**
This is separate infrastructure work. Lead Engine PR #6 and its review package are
unchanged. No login/DCR retry, Auth0 application creation, tenant mutation, FUB write,
CRM scan or secret extraction was performed during this investigation.

## Direct observations

Public GET preflight at 22:05 UTC:

| Surface | Observed |
|---|---|
| Full MCP unauthenticated request | HTTP 401; Bearer `invalid_token`, authentication required |
| Challenge resource metadata | `https://blaise-fub-mcp.onrender.com/.well-known/oauth-protected-resource/mcp` |
| Protected resource | `https://blaise-fub-mcp.onrender.com/mcp` |
| Protected-resource scopes | `fub:read`, `fub:write` |
| Issuer | `https://dev-46mx1synzdk7ancf.us.auth0.com/` |
| Authorization endpoint | Issuer + `authorize` |
| Token endpoint | Issuer + `oauth/token` |
| Registration endpoint | Issuer + `oidc/register` |
| Token auth methods | `client_secret_basic`, `client_secret_post`, `private_key_jwt`, `tls_client_auth`, `self_signed_tls_client_auth`, `none` |
| PKCE methods | `S256`, `plain`; Codex uses S256 |
| CIMD advertisement | Absent in both OAuth authorization-server and OpenID discovery |
| Authorization-response issuer advertisement | Absent; Codex uses server-specific callback binding |
| OAuth / OpenID discovery comparison | Matching selected fields |
| Public Codex CIMD | HTTP 200, native, `none`, correct client ID and callbacks |

Authorization-server scopes are its OIDC set (`openid`, `profile`, `offline_access`,
name/profile/email/identity/phone/address claims); the resource metadata separately
supplies the full MCP's two application scopes. These two lists need not be identical.
No token endpoint request or registration POST was made by the preflight.

Verified local executables:

- Desktop-inherited `%LOCALAPPDATA%/OpenAI/Codex/bin/9ba750cce02d5e5c/codex.exe`: 0.153.0.
- `%LOCALAPPDATA%/Programs/OpenAI/Codex/bin/codex.exe`: **0.154.0**, used for this task's
  subsequent CLI checks. User/system PATH and both executables were inspected locally.
- The 0.154.0 official release-tag source confirms Auto's CIMD conditions, stable
  URL-derived callback ID, and configured-client precedence without client-secret support.

`codex mcp list` returned `o_auth` for full MCP before the proposed pin. This reports
stored OAuth state, not successful resource access. A bounded app-server status
attempt timed out without a usable full-server tool result. No exact contact lookup
has been performed. No credential-store body was inspected or copied.

## DCR sprawl: mechanism established

With no configured client ID, Codex Auto cannot select CIMD because this tenant
does not advertise it; DCR is advertised and is the fallback. The user reported
repeated `Codex Generic` registrations exhausted tenant capacity. Client count and
historical registration logs are not independently available until dashboard login.

The proposed fix is one manually imported native CIMD client plus the same public
client ID pinned on each computer. That skips DCR even if discovery later changes.
Do not mark this installed until Auth0 import/grants and live login are verified.

## Google 401: exact cause remains unresolved

The existing failed FUB social handoff's browser navigation evidence showed:

- Google authorization request: response type `code`, scope `email profile`.
- Google redirect: `https://login.us.auth0.com/login/callback`.
- No `resource` query parameter in the observed Google account-chooser request.
- The request reached Google's consent path and displayed generic HTTP 401:
  the request was malformed, without a parameter-specific error explanation.

A separate fresh attempt to sign into **Auth0's own administration dashboard** with
the owner-identified Google account produced the same generic Google 401. That
request used a different Google client and
`https://auth0.auth0.com/login/callback`, with `code` / `email profile`, also without
`resource`. It was not a Codex/FUB authorization request and created no MCP client.

This evidence does **not** identify a malformed parameter. It also does not support
blaming the FUB loopback URI or RFC 8707 resource alone. The FUB Google callback
resembles Auth0's shared connection path, but private connection settings have not
been inspected, so development-key configuration is not asserted as verified.
Do not substitute a browser-account explanation, change Google credentials, or
rewrite OAuth URLs without provider evidence. No raw authorization URL, session
state, authorization code, token, cookie or client secret is retained in this report.

The single human-only step requested is signing into the opened Auth0 Dashboard
using the existing working sign-in method. After that, the operator will inspect
the tenant's failed-login details and Google connection configuration, establish
the actual cause and prepare any consequential configuration change for approval.

## Validation and acceptance ledger

| Check | Result |
|---|---|
| Python regression suite | 251 passed, including 16 new discovery/JWT/scope tests |
| Ruff | Passed |
| Full typecheck (excluding generated build directory) | Passed |
| Python wheel build | Passed; includes diagnostic module and CLI entrypoint |
| Public chain / CIMD document | Read and compared; CIMD advertisement missing |
| Clean relevant OAuth login | Pending dashboard recovery / reviewed provisioning |
| Restart / expected live tool inventory | Not proven |
| One exact `find_contact` read | Not run |
| Repeat login without client growth | Not run; requires Auth0 before/after inventory |
| Tenant settings or Render deployment | Unchanged |
| Secrets or FUB writes in validation | None |

Windows test setup required the `tzdata` package because this Python installation
does not ship an IANA timezone database. This was an environment prerequisite,
not an OAuth server change. Existing SDK resource-validation deprecation warnings
were observed; JWT audience and issuer enforcement remain covered by regression tests.

Source references and the operator-run recovery procedure are in
[OAUTH-RECOVERY.md](OAUTH-RECOVERY.md).
