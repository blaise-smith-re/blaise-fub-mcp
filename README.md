# Blaise FUB MCP v5.2 — Full Operator + Communication Coverage

One comprehensive FUB connector bundle so routine capabilities do not require repeated code patches.

## Enforced user-33 record scope

The shared FUB client enforces Blaise's fixed user ID 33 for every exposed
contact and related-record request. Searches inject the owner filter and
validate returned records; direct IDs do not bypass authorization. Tasks must
also belong to user 33, and deals/appointments must include user 33 and link
only to assigned contacts. Missing, conflicting or out-of-scope ownership
fails closed. Account configuration remains readable but cannot be mutated.

Before each mutation, the boundary rereads current ownership. Contact/lender
reassignment and changed deal/appointment ownership or contact links are
blocked. Read checks are reused only within a single collection page, never
across calls or writes. FUB does not provide an atomic ownership-conditioned
write here: a concurrent upstream reassignment between the final check and
write cannot be eliminated by this connector. Existing independent readback
and uncertain-write reconciliation remain required.

Mixed-owner upstream pages are filtered without returning excluded records;
task pagination continues using raw page sizes, with scoped completeness.
The regression suite exercises the real transport boundary using synthetic
offline records. OAuth, credentials, endpoint URLs and MCP tool signatures
are unchanged. No additional server or recurring task is introduced.

## Render memory recovery

Python is pinned in `.python-version`; the FUB transport reuses one verified TLS
trust store while continuing to close each request client. See the
[October 31 memory incident and verification record](docs/CONNECTOR_AUDIT.md#2026-10-31-render-memory-incident)
for the evidence, loopback probe and production verification limits.

## Full MCP OAuth recovery

The owner-selected connection is `blaise_fub_full`. See
[OAuth recovery and future-computer connection](docs/OAUTH-RECOVERY.md) for the
public native CIMD proposal, registration-sprawl prevention, credential-free
preflight and exact live acceptance requirements. This proposal is not a claim
that Auth0 recovery or deployment has completed.

## Historical read-only Real Estate OS pilot endpoint — retired

Retired by owner instruction on 2026-09-10. The following implementation and
certification history is retained as evidence, not a new-computer setup dependency.

`readonly_server.py` provides a separately deployable least-privilege surface for live OS certification. It registers
exactly six read tools, requires only `fub:read`, and contains no write, send, delete, scheduling, or configuration
tools. See `docs/READONLY_OS_ENDPOINT.md` for deployment and certification requirements.

The endpoint is an activation boundary, not a permanent limit on OS automation. Broader operations move through
their own certification gates instead of exposing the full write surface during initial live verification.

## Reads
Contacts/search, events, notes, calls, texts, tasks, appointments, deals, stages, users,
timeframes, contact/deal custom fields, pipelines, appointment types/outcomes.

Text reads now follow bounded exact-person cursor pages and explicitly distinguish readable
content from FUB-restricted bodies. The separately attributed latest communication field may
provide useful recent content; it is not full history. Call logs are distinguished from audio
and personal-text containers. See [Communication coverage](docs/COMMUNICATION_COVERAGE.md).
These are active-request reads, not a background listener or a new phone integration.

`find_contact` returns at most 25 records per call. To continue an authorized scoped search,
repeat the same filters and limit with `next_token` set to the prior response's `_metadata.next`.
Stop when no next token remains; disclose incomplete coverage if a page fails or a run budget
is reached. A cursor or limit alone does not authorize a search. The tool preserves the existing
raw response and metadata, performs one GET per call, and does not automatically sweep the account.
See the [FUB pagination reference](https://docs.followupboss.com/reference/pagination).

## Daily control audit (read-only)
`audit_contact_daily_control` / `audit_contacts_daily_control_batch` inspect specifically
authorized contacts for evidence-supported control gaps (no future task, overdue tasks,
exact-duplicate open tasks, conflicting next actions, stale/missing interaction notes,
ownership mismatch) without ever treating missing API activity as proof nothing happened.
See `docs/DAILY_CONTROL_AUDIT.md`.

## Writes
- Create notes — now with independent read-back verification and idempotent-retry protection
- Create/update/complete/reschedule tasks — task creation now checks for an exact-duplicate
  open task before writing and rejects bare placeholder names (e.g. "Follow Up")
- `close_out_contact_interaction` — safe, preview-first closeout: one note + at most one
  dated next task, with owner verification, duplicate/conflict checks, independent
  read-back of every write, and a before/after diff that flags anything unrelated that
  changed. See `docs/SAFE_CLOSEOUT.md`.
- Update selected contact profile fields
- Replace email/phone lists with stale-state protection
- Merge tags only when team approval is explicitly confirmed
- Create/update appointments; invitation sending requires explicit send authorization
- Create/update deals
- Log externally made calls/texts (LOG ONLY; does not call/text)

## Intentionally NOT exposed
- Delete contact/task/deal/appointment
- Create/edit shared FUB stages, Smart Lists, tag definitions, action plans, automations, lead-flow rules
- Create/edit global custom-field definitions or pipeline definitions
- Actual SMS/email sending or phone dialing
- Bulk destructive operations or any account-wide contact sweep

Those exclusions are deliberate business-control boundaries, not missing API coverage.

## Security
All writes require `fub:write`, exact record checks, and support preview mode.
FUB credentials remain server-side in Render. Note/task/closeout content is screened
for apparent secrets (passwords, SSNs, account/routing numbers, wire instructions,
TrustFunds secret words) before any write — see `redaction.py` and `SECURITY.md`.

## Tool inventory, gaps, and certification status
See `docs/CONNECTOR_AUDIT.md` for the full tool-by-tool audit and
`docs/CERTIFICATION_PLAN.md` for what a human-supervised live pass should
confirm before the new note/task closeout write classes are relied on
operationally.

## Development
```
uv sync --group dev
uv run pytest         # tests
uv run ruff check .   # lint
uv run ruff format .  # format
uv run mypy .         # typecheck
uv build               # build check
```
