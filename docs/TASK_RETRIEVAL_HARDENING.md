# Task-retrieval hardening (`search_tasks`, `get_open_tasks`)

## The defect (FUB 06 v1.6, verified Aug 30, 2026)

> "The FUB MCP search_tasks due keyword/date filtering is not reliable
> enough for unattended daily control: due=today missed a real due-today
> task and tomorrow/specific-date inputs could be silently ignored. The
> current search surface can also return fewer open tasks than the reported
> total and exposes no pagination control."

Two independent failure modes, both silent:

1. **Date filtering.** `search_tasks(due="today")` — passed straight through
   to FUB's own `GET /tasks?due=today` — did not reliably return a task
   whose raw `dueDate` was actually that day. `due="tomorrow"` and exact-date
   inputs could be dropped by FUB's own server-side matching with no error.
2. **Pagination.** Neither `search_tasks` nor `get_open_tasks` exposed
   `limit`/`offset`. FUB applied its own undisclosed default page size;
   in the verified run this returned 21 of 22 actual open tasks with
   nothing in the response indicating truncation.

Both are dangerous specifically because they're *silent* — a caller has no
signal that the result is wrong or incomplete, which is exactly what
"unattended" (the Daily Revenue Command Center) can't tolerate.

## The fix

**Never trust FUB's own `due=` keyword filtering for correctness again.**
`fub_client.FUBClient.search_tasks_all` pages through the complete matching
set (`limit`/`offset`, tracking FUB's own `_metadata.total`, de-duplicated
by task id, bounded by `max_items`/`max_pages` so an unexpectedly large
result set fails safely rather than looping forever). Date filtering then
happens **client-side**, deterministically, in `task_dates.py`, against each
task's raw `dueDate`/`dueDateTime` — never against FUB's keyword filter.

### Deterministic, timezone-safe date filtering

`search_tasks` gained `due_on` (exact calendar date), `due_from`/`due_to`
(inclusive bounded range), and `due_timezone` (IANA name, default
`America/Chicago` — the business's actual timezone). All three:

- Accept **only** exact `YYYY-MM-DD` syntax. Anything else — `"tomorrow"`,
  `"08/30/2026"`, an empty string, a full datetime — raises `ValueError`
  immediately, before any FUB call, naming the offending field. This is the
  direct fix for "specific-date inputs could be silently ignored": there is
  no longer a silent path for bad input to take.
- Compare by **calendar date**, not by converting to a UTC instant. FUB's
  `dueDate` is a bare date with no time-of-day; treating it as UTC-midnight
  and comparing across a timezone boundary would misclassify a task due
  "today" as already overdue for several hours near midnight in
  America/Chicago. `dueDateTime` (an explicit instant) is converted into
  `due_timezone` and reduced to a calendar date the same way, so "due
  today" means the same thing regardless of which field a task carries.
  See `task_dates.py`'s module docstring and the boundary tests in
  `tests/test_task_dates.py` for the exact math.
- **Force complete retrieval** whenever used, regardless of `fetch_all`. A
  date filter evaluated against only page one of a truncated result could
  silently miss a match on a later page — precisely the failure this fix
  exists to close.
- Report `excluded_no_usable_due_date` — a task with no parseable due date
  never matches an exact/bounded filter, and is counted separately rather
  than being indistinguishable from "checked and didn't match."

The legacy `due` keyword parameter is **still accepted and still passed
through to FUB** for backward compatibility, but any response built using it
now carries a `due_keyword_caveat` naming it unreliable and pointing at
`due_on`/`due_from`/`due_to` instead. It is never used internally by this
connector's own logic (daily-control audit, closeout duplicate checks) —
those never depended on it and are unaffected.

### Pagination and completeness

- `fetch_all=True` on `search_tasks` retrieves the complete matching set
  in one call.
- Every response — single-page or complete — carries a `_completeness`
  block: `returned_count`, `total_count` (from FUB's own metadata, `None`
  if undisclosed), `has_more`, `capped`, `pages_fetched`. A caller can never
  mistake a partial result for a complete one again.
- `get_open_tasks(person_id)` — unchanged signature — now **always**
  retrieves the complete set internally. Per-contact open-task counts are
  always small in practice, so this is cheap and removes the exact defect
  class at the one call site most directly tied to the Daily Control Audit
  and Safe Closeout duplicate-detection logic.

### Internal call sites fixed, not just the exposed tools

`create_contact_task`'s duplicate check, `audit_contact_daily_control`, and
`close_out_contact_interaction` (before *and* after snapshots) all called
`client.search_tasks(personId=..., isCompleted=False)` directly — the exact
single-page pattern the defect describes. All four now go through
`_get_all_open_tasks`, the same complete-retrieval helper `get_open_tasks`
uses. This is a pure internal fix: none of these tools' signatures or
response shapes changed, and the full existing certified test suite (153
pre-existing tests) passes unchanged, since realistic per-contact task
counts stay well under any pagination boundary. It closes a latent
correctness risk in the already-certified audit/closeout duplicate
detection for any contact whose open-task count happened to exceed FUB's
undisclosed single-page default — a scenario the existing certification
never exercised.

## Backward compatibility

- `search_tasks`'s existing five parameters are unchanged; every new
  parameter is optional with a default that preserves old single-page
  behavior when no date filter or `fetch_all` is requested.
- `get_open_tasks(person_id)` keeps its exact signature. Its response still
  contains `tasks`; `_metadata.total` and the new `_completeness` block are
  additive.
- The legacy `due` keyword still works exactly as before (passed through
  as-is) — it is now disclosed as unreliable rather than silently trusted.

## FUB API limitation discovered

FUB's `/tasks` list endpoint's own `due=<keyword>` server-side filtering is
independently confirmed unreliable (this is the root cause the fix works
around, not something this connector can repair — the filtering happens on
FUB's side). No FUB docs could be freshly consulted to determine whether
this is a documented limitation or a bug on FUB's end (`docs.followupboss.com`
is network-blocked from this environment); either way, the safe engineering
response is the same: don't rely on it. Separately, FUB's list-pagination
metadata (`_metadata.total`, `limit`, `offset`) behaves consistently with
the pattern already used elsewhere in this connector (notes, people, events)
and was not itself found unreliable — only the absence of pagination
parameters on the task-search tools was the gap.

## What did not change

No write authority or communication capability was added or broadened.
`search_tasks` and `get_open_tasks` remain read-only — no `execute` flag
exists on either, verified structurally in `tests/test_task_retrieval.py`.
No shared FUB stage, Smart List, tag definition, action plan, automation,
lead-flow rule, or team template is touched.
