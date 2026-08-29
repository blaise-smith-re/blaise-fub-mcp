# Safe Interaction Closeout

Tool: `close_out_contact_interaction` (server.py; helpers in `closeout.py`).

## Flow

1. **Resolve the exact contact.** `GET /people/{id}`, checked against
   `expected_contact_name` (same guard as every other write tool).
2. **Verify the owner.** The contact's current `assignedUserId` must equal
   the caller-supplied `expected_assigned_user_id`, or the call raises
   before any read of tasks/notes and before any write.
3. **Retrieve context for conflict checking.** Open tasks
   (`GET /tasks?personId=&isCompleted=false`) and notes
   (`GET /notes?personId=`), read once and reused for both the duplicate
   checks and the `context` surfaced in the preview.
4. **Check for exact duplicates.** A note with the same subject+body, or a
   task with the same name+type+due date, already present is treated as
   "already done" and skipped rather than rewritten.
5. **Default to preview.** `execute=False` (the default) returns
   `PREVIEW_ONLY_NO_WRITE` with the full intended write, the relationship
   context, and a `next_commitment_advisory` when the closeout as specified
   would leave the contact with no open task at all. No FUB write call is
   reachable on this path.
6. **On `execute=True`:** create the note and (if requested) the task,
   independently re-reading each via a fresh GET and confirming both the
   object id and the content match what was requested. A note or task
   whose creation, read-back, or content check fails is reported as
   `WRITE_FAILED` / `WRITE_COMPLETED_UNVERIFIED` / `WRITE_COMPLETED_CONTENT_MISMATCH`
   rather than silently treated as success — and does not stop the other
   write from being attempted or reported.
7. **Diff before/after.** Re-reads the contact and its open tasks after
   writing, and flags: any contact field that changed outside the
   server-controlled touch/activity timestamps; any pre-existing open task
   that changed or disappeared; any new task beyond the one this call
   created.
8. **Report.** Returns `created_object_ids` (note id, task id — `None` when
   not created), the full before/after diff, and an `unresolved` list that
   is empty only when every write succeeded, verified clean, and nothing
   unrelated changed. Overall `status` is `CLOSEOUT_COMPLETED` only when
   `unresolved` is empty; otherwise `CLOSEOUT_COMPLETED_WITH_HOLD`.

## Guardrails specific to this tool

- **Vague-task rejection.** A bare placeholder task name ("Follow Up",
  "Call", "Touch base", ...) is rejected — the next action must name the
  actual commitment.
- **Sensitive-data rejection.** `note_subject`, `note_body`, and
  `next_task_name` are scanned before anything else runs; a match raises
  before any read or write happens.
- **Exactly one note, at most one task, per call.** There is no loop, no
  batch-write path, and no way to pass a list of notes/tasks — this
  structurally guarantees "every intended write appears exactly once" per
  invocation; idempotent retries are additionally guarded by the exact-
  duplicate check in step 4.

## Known limitations (see also `docs/CONNECTOR_AUDIT.md`)

- **No confirmed single-item `GET /notes/{id}`.** Read-back for notes is
  done by re-listing the contact's notes and matching on id. If FUB's API
  does expose a single-item note GET, live certification should confirm it
  and this can be simplified — but the current mechanism is already a
  genuine independent read-back, not a rubber stamp.
- **No server-side idempotency key.** Neither notes nor tasks in the FUB
  API accept a client-supplied idempotency token. Duplicate prevention here
  is content-based (exact subject+body / exact name+type+due) and closes
  the retry-after-timeout gap, but does **not** protect against two
  concurrent closeout calls for the same contact racing each other between
  the duplicate-check read and the create call. Given this is a
  single-operator connector (not a high-concurrency multi-agent system),
  that residual race is treated as acceptable but should not be relied on
  under concurrent use of this tool against the same contact.
- **Owner is trusted from the FUB record at call time**, not from any
  separate roster; if `assignedUserId` on the contact is wrong in FUB
  itself, this tool will faithfully verify against the wrong value. That is
  a FUB data-quality issue, not something this tool can independently
  detect — the daily-control audit's `ownership_mismatch` finding is the
  intended way to surface that against an external expectation.
