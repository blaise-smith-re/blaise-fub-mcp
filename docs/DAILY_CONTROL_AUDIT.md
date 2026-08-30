# Daily Control Audit (read-only)

Tools: `audit_contact_daily_control`, `audit_contacts_daily_control_batch`
(server.py, logic in `daily_control.py`).

## What it does

Given an exact, caller-authorized contact (`person_id` + `expected_contact_name`,
verified via the same exact-match guard every write tool uses), it reads:

- the contact record (`GET /people/{id}`)
- open tasks (`GET /tasks?personId=&isCompleted=false`)
- notes (`GET /notes?personId=`)
- events (`GET /events?personId=`, read but never used to conclude absence)

and reports evidence-supported findings:

| Finding | Meaning | Evidence returned |
|---|---|---|
| `no_future_task` | No open task, or every open task is overdue | The open task list (if any) |
| `overdue_tasks` | One or more open tasks past due | The overdue tasks |
| `exact_duplicate_open_tasks` | Two or more open tasks with identical name+type+due | The duplicate groups |
| `conflicting_next_actions` | Two or more non-duplicate open tasks due the same day | The tasks (marked as a heuristic requiring human confirmation) |
| `no_recent_interaction_note` | No notes at all, notes that cannot be dated, or a latest note older than `stale_note_days` | Notes checked, undateable count, latest note id/date/age, threshold used |
| `ownership_mismatch` | Only checked when the caller supplies `expected_assigned_user_id`. Fires both when the wrong user owns the contact **and when nobody owns it** | Actual vs. expected assigned user |

## The stale-note threshold is an advisory default, not policy

`stale_note_days` defaults to **21**, which is an **engineering default chosen
for this connector**. FUB 05 defines no note-staleness interval — its only
numeric review interval is "Qualify leads older than seven days," a different
rule about a different object. To keep that distinction impossible to lose
downstream, every threshold-derived finding carries:

- `threshold_basis: "implementation_default"` — a structured field, so a
  report generator cannot silently render the finding as policy;
- an `advisory` string stating in words that this is not FUB business policy
  and that `stale_note_days` should be tuned per relationship;
- `evidence.stale_note_days_threshold` — the exact threshold actually applied.

**Boundary:** age is computed in fractional days and compared strictly
(`age > threshold`). A note exactly 21.0 days old is *not* flagged; 21.1 days
*is*. An earlier truncating day-count made the effective boundary 22 days —
a day later than the stated threshold.

**Future-dated notes** (clock skew) produce a negative age and are never
flagged as stale.

## Notes that exist but cannot be dated

If the Notes API returns notes whose timestamps cannot be parsed, the finding
says so explicitly and reports `notes_with_unusable_dates`. It does **not**
claim the API returned no notes — that earlier wording contradicted its own
evidence (a nonzero `notes_checked` alongside "returned no notes") and could
have been read as evidence of missing interaction rather than a data-quality
limit.

## Evidence-scope disclosure

Notes are read in a bounded window (most recent 50). When FUB's
`_metadata.total` indicates more notes exist than were returned,
`evidence_scope.notes_scope_limitation` says so, so a partial read is never
presented as a complete one.

An **empty findings list is not a clean bill of health** — it means no gap was
detected by these specific checks at their configured thresholds. That
statement ships in the `caveats` of every audit result.

## What it deliberately does not do

- **Does not scan the account.** `audit_contacts_daily_control_batch` only
  reads the exact contacts passed in — no `find_contact` sweep, no paging
  through all people.
- **Does not conclude "no interaction occurred" from an empty result.**
  Every finding tied to absence (no notes, no events) carries a `caveat`
  field saying so explicitly. Calls and text messages are read elsewhere in
  the connector but are intentionally **not** used by this audit's
  "no interaction" logic, because `get_contact_text_messages` is documented
  (FUB 06) to under-report Inbox App Messages and API-restricted history.
- **Does not rank contacts by activity volume.** No count of calls/texts
  made is computed or surfaced — the audit reports control gaps, not
  busywork metrics.
- **Never writes anything.** No FUB API call in this path is anything but a
  GET.

## Known limitation

The `conflicting_next_actions` and `no_future_task`/`overdue_tasks` findings
are as accurate as the FUB API's own due-date data; a task with no due date
at all is currently treated as "not overdue" (it has no date to be overdue
against) but does count toward "an open task exists." This matches FUB's own
task model — undated tasks aren't creatable through `create_contact_task`
in this connector, but may exist from other sources (FUB UI, other
integrations, or before this control was added).
