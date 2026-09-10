# OAuth investigation — 2026-09-10

**Current result: full MCP login, rotating refresh issuance/renewal, new-process
tools and bounded reads verified. Historical Google 401 cause remains unresolved.**
This is separate infrastructure work. Lead Engine PR #6 and its review package are
unchanged. Controlled logins reused an existing application; no DCR registration,
Auth0 application creation, FUB write or CRM scan occurred. After explicit owner
approval, API offline access and native-client refresh settings were changed.
Credential verification used local encrypted storage in memory; no credential
value, plaintext backup or browser token was exported or printed.

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
had been performed at that initial stage. Subsequent acceptance is recorded below.
No credential-store body was inspected or copied.

## DCR sprawl: mechanism established

With no configured client ID, Codex Auto cannot select CIMD because this tenant
does not advertise it; DCR is advertised and is the fallback. The user reported
repeated `Codex Generic` registrations exhausted tenant capacity. Client count and
historical registration logs were initially unavailable. Subsequent dashboard
inspection confirmed two recent DCR registrations at 21:31:37 and 21:39:48 UTC on
September 10, and two visible Codex Generic clients. The creation UI reports a
10-entity quota; the application list contains five visible rows. No client was
created or deleted by this recovery task.

The final proposed configuration reuses the existing public native client instead
of importing another application. Its configured ID skips DCR even if discovery
changes. Tenant CIMD registration is OFF, DCR ON, and Resource Parameter
Compatibility Profile ON. No feature flags were changed. CIMD remains a supported
future option rather than a required dependency for this recovery.

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
resembles Auth0's shared connection path. Later tenant logs independently confirmed
Google development-key use, including warnings at 21:31:40, 21:39:54 and 21:40:30
UTC. That warning identifies a production limitation, not a malformed parameter.
Do not substitute a browser-account explanation, change Google credentials, or
rewrite OAuth URLs without provider evidence. No raw authorization URL, session
state, authorization code, token, cookie or client secret is retained in this report.

The owner subsequently authenticated to the dashboard with the correct account.
That resolves dashboard access, but does not establish an account-selection cause
for the historical FUB failure. The earlier September 8 logs also show resource
type and callback mismatch failures; those are separate dated failures, not proof
of the September 10 Google 401.

## Existing client and controlled request evidence

- Existing application: Blaise Codex FUB MCP, public ID
  `zVnhfzFBR7aX6np3JSAXf0Cnohu8fWuH`, Native application type.
- Allowed callbacks visually verified: loopback 127.0.0.1 ports 57185 and 10230,
  both with path `/callback/Msr2-imGFcgW`. No wildcard added.
- Google and Username-Password connections enabled. Full MCP API access shows
  2/2 delegated permissions; machine-to-machine access denied by API policy.
- Historical successful Google login and authorization-code exchange at
  September 10 19:05:37 UTC belong to this existing application. They are not a
  substitute for current full-scope validation.
- First controlled 0.154 request using this client and callback selected generic
  OIDC discovery scopes, omitting `fub:read` and `fub:write`. It was terminated
  before opening its authorization URL. No registration was requested.
- Added explicit server scopes. Versioned Codex CLI source verifies configured
  scopes suppress discovery. The next request contained exactly `fub:read
  fub:write`, one resource equal to the full MCP URL, the allowed 57185 callback,
  configured client ID and PKCE S256. No secret-based client authentication.
- Corrected request reached Google's account chooser. No account was selected by
  the operator. The transaction timed out awaiting the owner's human sign-in;
  no callback success, token exchange or exact FUB read is claimed. A subsequent
  continuation must generate a fresh transaction, never reuse the expired URL.

The scope defect is established independently of Google 401. Its correction is
covered in the separate OS config PR and diagnostic scope-mismatch regression.
Auth0's development-key limitations and precise Google error remain outstanding;
no consequential Google connection change has been made.

## Successful live acceptance after owner sign-in

The owner completed Google sign-in. A fresh configured-client transaction returned
`Successfully logged in` from Codex 0.154.0. Auth0 independently recorded a successful
authorization-code exchange at **22:46:43.811 UTC** for the existing native app.
The earlier timed-out browser showed a refused loopback connection; it was not
replayed as the basis for this successful new transaction.

- A separate `codex mcp list` process reported the enabled full server with OAuth.
- A new 0.154 app-server process in the trusted OS project initialized and returned
  all 38 configured full-server tools without authentication or scope errors.
- One exact `find_contact`, approved name and limit 3, succeeded with zero returned
  records. No second search, pagination, write or broad scan was made. The private
  task response holds the target/match result; no CRM body is persisted here.
- The direct read ran through Codex's own MCP client in an ephemeral diagnostic
  session restricted to `find_contact` / `get_contact`, with no model turn or
  persistent task creation. It did not extract or transport credentials itself.
- A repeat login around 22:49 UTC reused the same client and succeeded. Another
  fresh app-server process again enumerated all 38 tools. No FUB read was repeated.
- Dashboard inventory afterward contained the same five visible applications,
  including the same two existing Codex Generic rows. No application growth.

The earlier app-server diagnostic timeout was a helper configuration error:
overrides for absent retired/plugin server entries created invalid transport
stubs. Removing those overrides restored initialization. It was not evidence of
an OAuth or FUB failure. No project transport or server safety check was weakened.

This proves current login, reconnect and bounded use, not an exact diagnosis of
the prior Google 401 or refresh across token expiration. Both successful logins
used the existing Google connection unchanged. Production development-key removal
requires a separately reviewed provider configuration change.

Before the owner's refresh approval, the full API settings showed maximum access-token lifetime 86,400
seconds and **Allow Offline Access OFF**. The earlier explicit scope set requested
no refresh token. Therefore restart persistence is verified, but renewal beyond
the token lifetime is not enabled by this patch. The existing native app's
Authorization Code and Refresh Token grants are already checked; Client
Credentials is disabled. Owner approval was requested for
enabling offline access on this existing API and requesting `offline_access` for
the existing native client. No setting was changed while that approval was pending.

## Owner-approved refresh recovery and live acceptance

The owner explicitly approved offline access on the existing full API and pinned
native client, retaining the two FUB scopes and the 24-hour access-token lifetime,
with bounded rotating refresh tokens. Applied and independently reloaded:

| Setting | Before | After |
|---|---|---|
| Full API Allow Offline Access | OFF | ON |
| Access-token maximum lifetime | 86,400 seconds | 86,400 seconds |
| Native client refresh rotation | OFF | ON |
| Idle refresh expiration | Unbounded | 604,800 seconds / 7 days |
| Maximum refresh expiration | Unbounded | 2,592,000 seconds / 30 days |
| Rotation overlap | 0 seconds | 5 seconds |
| Codex explicit scopes | fub:read, fub:write | fub:read, fub:write, offline_access |

Existing authorization-code/refresh grants were already enabled. No other grant,
API permission, client, secret, MCP endpoint, MRRT or access lifetime was added.

Fresh Codex 0.154 login used the same client, callback and one correct resource,
PKCE S256, and exactly those three scopes. Auth0 recorded the code exchange at
**23:04:41.431 UTC**. Local verification confirmed a refresh token was present;
only booleans, scope names and lifetime numbers were emitted.

The renewal test changed only this FUB connection's local `expires_at` cache
metadata to due. It acquired the existing connection refresh lock and aggregate
store lock, retained all credential values/other entries, and kept the store age
encrypted with its existing OS-keyring key. Atomic replacement retained the
existing ACL. No plaintext file, backup, token log, server lifetime change or clock
change was used. The test would restore unchanged cache metadata if renewal failed.

A fresh unmodified Codex 0.154 process performed the actual exchange and persisted
the rotated credential. Auth0 independently logged **Successful Refresh Token
exchange at 23:08:58.874 UTC**. Verification found changed access and refresh
tokens, a future expiry, unchanged client/scopes, a refresh credential still
present, and the same 86,400-second access-token lifetime. Credential values were
never printed. This tests actual renewal by forcing local cached expiry; it does
not claim that 24 hours elapsed or that reuse detection was deliberately tripped.

A subsequent new process loaded all 38 configured tools from the trusted OS
project. The newly authorized single bounded read (`find_contact`, named target,
limit 3) succeeded with zero matches. No FUB write or further discovery occurred.
Application inventory still showed the same five rows and the same client IDs;
no new application appeared. Google connection credentials remain unchanged.

The durable refresh path is ready for Work review. Historical Google 401 diagnosis
and replacement of Auth0 Google development keys remain separate limitations;
neither is represented as resolved by refresh success. Future login is expected
at idle/maximum refresh expiry, revocation or provider security events.

## Validation and acceptance ledger

| Check | Result |
|---|---|
| Python regression suite | 252 passed, including 17 new discovery/JWT/scope tests |
| Ruff | Passed |
| Full typecheck (excluding generated build directory) | Passed |
| Python wheel build | Passed; includes diagnostic module and CLI entrypoint |
| Public chain / CIMD document | Read and compared; CIMD advertisement missing |
| Fresh relevant OAuth login | Passed; explicit full scopes; existing configured client |
| Restart / expected live tool inventory | Passed in separate processes; 38 configured tools |
| One exact `find_contact` read | Passed; zero matches; no further search or write |
| Repeat login without client growth | Passed; same client, same five visible application rows |
| Refresh issuance and renewal | Passed: token present, real exchange, rotated token persisted; local cache-expiry trigger |
| Historical Google 401 malformed parameter | Not identified; did not recur in successful logins |
| Auth0 changes | Approved full-API offline access and native refresh bounds/rotation only |
| Render deployment / new applications | None |
| Secrets or FUB writes in validation | None |

Windows test setup required the `tzdata` package because this Python installation
does not ship an IANA timezone database. This was an environment prerequisite,
not an OAuth server change. Existing SDK resource-validation deprecation warnings
were observed; JWT audience and issuer enforcement remain covered by regression tests.

Source references and the operator-run recovery procedure are in
[OAUTH-RECOVERY.md](OAUTH-RECOVERY.md).
