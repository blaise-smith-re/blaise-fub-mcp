# Blaise FUB MCP v5.1 — Full Operator + Safe CRM Closeout

One comprehensive FUB connector bundle so routine capabilities do not require repeated code patches.

## Reads
Contacts/search, events, notes, calls, texts, tasks, appointments, deals, stages, users,
timeframes, contact/deal custom fields, pipelines, appointment types/outcomes.

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
