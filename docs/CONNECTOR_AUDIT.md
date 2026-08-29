# Blaise FUB MCP — Connector Audit (v5 baseline)

Audit date: 2026-08-29. Scope: every tool exposed by `server.py` prior to this
engineering pass, checked against the deployed connector's own certification
record (**FUB 06 — Automation Map, Guardrails & Improvement Log**, v1.4) and
against the current `fub_client.py` implementation.

Network note: `docs.followupboss.com`, `help.followupboss.com`, and
`followupace.com` are unreachable from this engineering environment (egress
proxy blocks them). This audit is therefore based on (a) the already-deployed,
partially-certified `fub_client.py`/`server.py` implementation, whose HTTP
calls against `https://api.followupboss.com/v1` are the actual source of
truth for endpoint shape, and (b) FUB 06's own record of what has been
live-tested. Nothing below assumes an endpoint behavior that isn't already
exercised by existing, working code. Where a needed capability could not be
confirmed this way, it is marked HOLD rather than assumed.

Legend — **Certification status**: CERTIFIED (FUB 06 records a live test),
UNCERTIFIED (code exists, no live test recorded), N/A (read-only reference
call, not independently certified but low-risk).

## Read tools

| Tool | Impl. (FUBClient / endpoint) | Certification | Read-back applicable? |
|---|---|---|---|
| find_contact | `find_people` → `GET /people` | CERTIFIED | n/a (read) |
| get_contact | `get_person` → `GET /people/{id}` | CERTIFIED | n/a |
| get_contact_events | `get_events` → `GET /events?personId=` | CERTIFIED, with FUB06 caveat: absence of events is not proof no activity occurred | n/a |
| get_contact_notes | `get_notes` → `GET /notes?personId=` | CERTIFIED | n/a — also reused below as the note **read-back** mechanism |
| get_contact_calls | `get_calls` → `GET /calls?personId=` | CERTIFIED | n/a |
| get_contact_text_messages | `get_text_messages` → `GET /textMessages?personId=` | CERTIFIED, with FUB06 caveat: zero results ≠ no communication (Inbox App Messages / API-restricted history not exposed) | n/a |
| search_tasks | `search_tasks` → `GET /tasks` | CERTIFIED | n/a |
| get_open_tasks | `search_tasks(isCompleted=False)` | CERTIFIED (basis of the one live write test) | n/a |
| get_task | `get_task` → `GET /tasks/{id}` | CERTIFIED (used as task read-back) | n/a |
| get_contact_appointments, get_appointment | `search_appointments` / `get_appointment` | UNCERTIFIED | n/a |
| get_active_deals, search_deals, get_deal | `search_deals` / `get_deal` | UNCERTIFIED | n/a |
| get_stages | `GET /stages` | CERTIFIED (used to gate `update_contact_profile` stage moves to existing stages only) | n/a |
| get_users, get_user | `GET /users`, `GET /users/{id}` | CERTIFIED (owner verification) | n/a |
| get_timeframes, get_custom_fields, get_deal_custom_fields, get_pipelines, get_appointment_types, get_appointment_outcomes | reference GETs | UNCERTIFIED, low risk | n/a |

**Gap / recommendation:** none of the read tools change. They are the
evidence base for the new Daily Control Audit and Safe Closeout tools below.

## Write tools

| Tool | Read/Write | Implementation | Certification | Read-back available? | Gap / recommendation |
|---|---|---|---|---|---|
| create_contact_note | WRITE | `POST /notes` | UNCERTIFIED | **NO** — prior code returned the raw POST response only, no independent re-read | **GAP (fixed this pass):** harden with independent read-back via `GET /notes?personId=` matched by returned id/subject/body, since a single-item `GET /notes/{id}` endpoint is not confirmed reachable from this environment. If the match fails, the tool now reports `WRITE_COMPLETED_UNVERIFIED` rather than claiming success — this write class stays uncertified for autonomous use until a human confirms the read-back in a live pass. |
| create_contact_task | WRITE | `POST /tasks` → `GET /tasks/{id}` | **CERTIFIED** (FUB 06: task 29909 on Douglas H, person 18393) | YES | **GAP (fixed this pass):** the certified version had no duplicate/idempotency check before POST — a retry (network timeout, double-click) could create two tasks. Hardened to check `GET /tasks?personId=&isCompleted=false` for an exact case-insensitive name+type+due match before writing, and to treat a matching existing task as the idempotent result rather than writing again. |
| update_contact_task | WRITE | `PUT /tasks/{id}` → `GET /tasks/{id}` | UNCERTIFIED | YES | No change — reused as-is by the closeout workflow only when explicitly asked to reuse an existing task; not modified. |
| update_contact_profile | WRITE | `PUT /people/{id}` → `GET /people/{id}` | UNCERTIFIED | YES | Out of scope this pass. |
| replace_contact_channels | WRITE | `PUT /people/{id}` (full list replace) → `GET /people/{id}` | UNCERTIFIED | YES | Out of scope this pass; already has stale-state protection. |
| merge_contact_tags | WRITE | `PUT /people/{id}?mergeTags=true` | UNCERTIFIED, gated on `brent_approval_confirmed` | YES | Out of scope; not a tag-definition change (merges tag usage, not shared tag config), left untouched. |
| create_contact_appointment, update_contact_appointment | WRITE | `POST`/`PUT /appointments` | UNCERTIFIED | YES | Out of scope this pass; can trigger email/SMS invitations, already gated behind `explicit_send_authorization`. |
| create_contact_deal, update_contact_deal | WRITE | `POST`/`PUT /deals` | UNCERTIFIED | YES | Out of scope this pass. |
| log_external_call_record | WRITE | `POST /calls` | UNCERTIFIED | **NO** — no read-back implemented | Noted, not fixed this pass (out of scope: task goal is note + task closeout only). Flagged as a follow-up gap. |
| log_external_text_record | WRITE | `POST /textMessages` | UNCERTIFIED | **NO** — no read-back implemented | Noted, not fixed this pass; same reason. |

## New tools built this pass (not present before)

| Tool | Read/Write | Purpose |
|---|---|---|
| `audit_contact_daily_control` | READ-ONLY | Evidence-based control-gap audit for one specifically authorized contact (see `docs/DAILY_CONTROL_AUDIT.md`). |
| `audit_contacts_daily_control_batch` | READ-ONLY | Thin batch wrapper over the above for an explicit, caller-supplied list of authorized contacts. No account-wide sweep. |
| `preview_contact_closeout` / `execute_contact_closeout` (single tool, `execute` flag) | WRITE (defaults to preview) | Safe interaction closeout: one note + at most one next task, full pre-write verification and independent post-write read-back (see `docs/SAFE_CLOSEOUT.md`). |

No shared FUB stage, Smart List, tag definition, action plan, automation,
lead-flow rule, or team template is created, edited, or referenced for
editing by any of the above.
