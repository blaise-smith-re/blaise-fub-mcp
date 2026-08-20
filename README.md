# Blaise FUB MCP v5 — Full Operator

One comprehensive FUB connector bundle so routine capabilities do not require repeated code patches.

## Reads
Contacts/search, events, notes, calls, texts, tasks, appointments, deals, stages, users,
timeframes, contact/deal custom fields, pipelines, appointment types/outcomes.

## Writes
- Create notes
- Create/update/complete/reschedule tasks
- Update selected contact profile fields
- Replace email/phone lists with stale-state protection
- Merge tags only when team approval is explicitly confirmed
- Create/update appointments; invitation sending requires explicit send authorization
- Create/update deals
- Log externally made calls/texts (LOG ONLY; does not call/text)

## Intentionally NOT exposed
- Delete contact/task/deal/appointment
- Create/edit shared FUB stages, Smart Lists, action plans, automations, lead-flow rules
- Create/edit global custom-field definitions or pipeline definitions
- Actual SMS/email sending or phone dialing
- Bulk destructive operations

Those exclusions are deliberate business-control boundaries, not missing API coverage.

## Security
All writes require `fub:write`, exact record checks, and support preview mode.
FUB credentials remain server-side in Render.
