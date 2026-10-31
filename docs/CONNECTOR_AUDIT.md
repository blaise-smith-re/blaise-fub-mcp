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
| search_tasks | `search_tasks` / `search_tasks_all` → `GET /tasks` | **NOT CERTIFIED as of FUB 06 v1.6** — production defect verified Aug 30 2026: `due=today` missed a real due-today task, `due`/date-keyword inputs could be silently ignored, and the tool returned 21 of 22 reported open tasks with no pagination parameter. Hardened this pass — see `docs/TASK_RETRIEVAL_HARDENING.md`; re-certification pending. | n/a |
| get_open_tasks | `search_tasks_all(isCompleted=False)` | Hardened this pass to always retrieve the complete set (was previously a single unpaginated page — the same defect as `search_tasks`). Re-certification pending. | n/a |
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

## 2026-10-31 Render memory incident

This dated technical addendum does not recertify the historical business-tool
matrix above. It records transport recovery for `blaise-fub-mcp` only.

### Evidence and diagnosis

- Render service `srv-da376tqjnfac73bsdnh0`, Starter / 512 MiB / one instance,
  reported OOM kills at 2026-10-29 23:24:00Z and 2026-10-31 13:41:10Z
  (October 31 08:41:10 America/Chicago). The latter event is
  `evt-dbiuvtgjo6nc73bp21dg`. No capacity or account change was needed.
- The affected revision was `d40707c0f6d1b9ffe2c3adffbac768b1995f9ebd`.
  Its build selected Render's creation-date default, Python 3.14.3, with MCP
  1.30.0 and HTTPX 0.28.1. Memory reached 536,129,540 bytes at 13:40Z against
  a 536,870,912-byte limit; automatic restart restored reads but did not repair
  the allocation path. Memory was already about 206 MiB again at 14:59Z.
- The supported cause is delayed SSL/native-memory reclamation in the affected
  Python runtime, amplified by a fresh HTTPX client and CA context for every
  FUB request. [CPython's SSL investigation](https://github.com/python/cpython/issues/142516)
  and [3.14 GC release notes](https://docs.python.org/3.14/whatsnew/3.14.html#garbage-collection)
  document the problem and correction from 3.14.5 onward. This is a strong
  causal diagnosis supported by a local reproduction, not a production heap dump.
- Existing pagination guards, sequential contact-batch processing and per-request
  client closure were present. No unbounded application response cache was found.
  MCP 1.30.0 has stateless transport cleanup; 500 synthetic MCP requests showed
  no accumulating sessions/tasks in the local isolation check. No arbitrary
  result truncation, concurrency restriction or restart schedule was added.

### Repair and offline verification

Revision `28b6a3f7cbfda3893014632f6d50201b75e57df1` pins Python 3.14.10 and
reuses one certificate-verifying SSLContext per process (`maxsize=1`). It preserves
HTTPX's SSL_CERT_FILE / SSL_CERT_DIR / certifi precedence. Trust-store changes
require a process restart. Credentials, response bodies and sockets are not cached;
requests still close on success, HTTP failure and cancellation. OAuth issuer,
audience, scopes, callbacks, tool schemas and all existing action boundaries are unchanged.

The loopback-only probe `scripts/probe_http_memory.py` uses an ephemeral test
certificate and synthetic records: 800 HTTPS requests, eight concurrent, no
forced collection until the final diagnostic sample. On Windows:

| Runtime / allocation strategy | RSS at request 800 | Live SSL contexts | After forced GC |
|---|---:|---:|---:|
| Python 3.14.3 / fresh context | 160.54 MiB | 137 | 57.70 MiB / 1 context |
| Python 3.14.10 / fresh context | 80.79 MiB | 17 | 59.44 MiB / 1 context |
| Python 3.14.10 / reused context | 58.90 MiB | 2 | 57.73 MiB / 2 contexts |

The reused-context run stayed between 58.59 and 59.59 MiB after warm-up. The two
contexts are the local TLS server and shared client. These are diagnostic local
measurements, not a prediction of Linux production RSS or a long-term soak test.

Python 3.14.10 validation: 309 tests passed, Ruff passed, mypy passed, wheel built.
The six added regressions cover trust-store selection/reuse and client cleanup
on success/error/cancellation. For type checking after a wheel build, exclude
`build/` (generated duplicate modules). Windows test environments also need
`tzdata`; Render Linux already has the system timezone database.

To repeat the probe in an isolated environment with `httpx`, `cryptography` and
`psutil` installed, run `python scripts/probe_http_memory.py`, then run a separate
process with `--reuse-context`. It connects only to 127.0.0.1 and never loads
FUB credentials, contacts FUB, or saves real client records.

### Production verification

Render deployment `dep-dbj0a0p5efls73dg25ug` became live at
2026-10-31 15:11:50Z, running the repair revision above. Build logs explicitly
confirm Python 3.14.10 from `.python-version`; instance
`srv-da376tqjnfac73bsdnh0-w44tj` completed application startup.
The authenticated `get_user` read of the existing operator account succeeded;
new-instance logs show the upstream GET and MCP response both returning HTTP 200
at 15:12:28Z. No live CRM writes were made for this verification.

Five reads were verified in the new-instance logs, including four requested
concurrently; all upstream and MCP responses were HTTP 200. A direct unauthenticated
MCP request still returned HTTP 401 with its authentication challenge. No application
errors or new service-failure events appeared during the verification window.

Render's new-instance samples from 15:12:30Z through 15:14:30Z ranged from
88,064,000 to 89,063,420 bytes (83.98-84.94 MiB), with the latter value unchanged
across the final two samples. This is about 17% of the existing 512 MiB limit.
Ignore pre-start samples and the old instance's lingering metric series when
comparing the deployment. The measured window is only two minutes after warm-up.

Long-term stability requires ordinary workload observation; a live deployment,
successful read, or restart alone is not that evidence. Keep the existing plan.
If memory resumes sustained growth, compare the new instance's memory curve with
request volume and inspect native allocations before proposing paid capacity.
