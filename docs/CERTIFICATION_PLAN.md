# Live Certification Plan — Daily Control Audit & Safe Closeout

This engineering pass is code + docs + tests only. **No live FUB write was
performed while building it.** The items below are what a human-supervised
live pass needs to check before these action classes move from
"implemented and tested against mocks" to "certified," in the same style
FUB 06 already uses to record `create_contact_task`'s one controlled live
write (task 29909 on contact 18393).

## Why this is a HOLD-eligible area, not an unconditional PASS

1. **Network access to FUB's own documentation was blocked** from this
   engineering environment (`docs.followupboss.com`, `help.followupboss.com`,
   `followupace.com` all returned `EGRESS_BLOCKED`). Endpoint shapes used
   here come from the already-certified, already-deployed `fub_client.py`
   code and from FUB 06's own record of what has been live-tested — not
   from a fresh read of current API docs. Nothing was invented, but nothing
   new was independently confirmed against the docs either.
2. **Note read-back has never been live-tested at all.** `create_contact_note`
   previously had no read-back of any kind. This pass adds one (list +
   match by id), but whether FUB's `/notes` list endpoint reliably reflects
   a just-created note immediately (no eventual-consistency lag) is
   untested against the real API.
3. **The hardened `create_contact_task` duplicate-check and the new
   `close_out_contact_interaction` tool have zero live-write history.**
   Everything below "mocked tests pass" is unverified against production
   Follow Up Boss.

## Certification steps (to run separately, with Blaise's authorization)

1. **Pick one test-authorized contact** the way FUB 06's existing
   certification did (a real but low-risk record Blaise names explicitly).
2. **Daily control audit, read-only:** run `audit_contact_daily_control`
   against that contact. Confirm the findings match what's actually true in
   the FUB UI (open tasks, notes, dates) — this has no write risk and can
   run first.
3. **Note write, single case:**
   - `create_contact_note(..., execute=False)` → confirm the preview is
     correct.
   - `create_contact_note(..., execute=True)` once → confirm the tool
     reports `WRITE_COMPLETED_AND_RE_READ` (not `_UNVERIFIED` or
     `_CONTENT_MISMATCH`).
   - Independently open the contact in the FUB UI and confirm the note is
     there, exactly once, with the exact subject/body.
   - Immediately retry the identical call → confirm it reports
     `SKIPPED_EXACT_DUPLICATE_EXISTS` and that FUB still shows only one
     note.
   - **If any of this doesn't hold, HOLD note-write certification** — do
     not treat `WRITE_COMPLETED_AND_RE_READ` as sufficient proof on its own
     until a human has independently confirmed it once in the live UI.
4. **Task write, single case:** same shape as the existing certified
   `create_contact_task` test, but now also confirm the new duplicate-check
   by retrying the identical call and confirming exactly one task exists.
5. **Full closeout, single case:** `close_out_contact_interaction` with
   `execute=True` on the same test contact, requesting both a note and a
   task. Confirm: exactly one new note, exactly one new task, both correct;
   no other field, task, note, stage, tag, deal, or communication changed
   (the tool's own `before_after` block should already report this — treat
   a human check of the FUB UI as the independent confirmation of that
   claim, not just the tool's self-report).
6. **Record the result in FUB 06** the same way the existing
   `create_contact_task` certification is recorded, including the object
   IDs created and confirmation that nothing unrelated changed.

## Other things a human should confirm before relying on this operationally

- The `stale_note_days` default (21) and the same-day
  `conflicting_next_actions` heuristic in the daily-control audit are
  reasonable defaults chosen for this pass, not values taken from FUB 05 —
  confirm they match Blaise's actual rhythm expectations, or pass a
  different `stale_note_days` per call.
- The vague-task-name blocklist (`closeout.py`) and the sensitive-data
  patterns (`redaction.py`) are heuristic. Both are deliberately narrow
  (exact-match blocklist; conservative regex) to minimize false positives,
  but a human should skim them once for anything Blaise's actual note
  style would trip that shouldn't be tripped, or anything it should catch
  that it doesn't.
- `close_out_contact_interaction` has no protection against two concurrent
  calls for the same contact racing each other (see
  `docs/SAFE_CLOSEOUT.md`, Known limitations). Acceptable for a
  single-operator workflow; do not run it concurrently against the same
  contact from multiple sessions.

## What is explicitly NOT part of this certification

`update_contact_task`, `update_contact_profile`, `replace_contact_channels`,
`merge_contact_tags`, `create_contact_appointment`, `update_contact_appointment`,
`create_contact_deal`, `update_contact_deal`, `log_external_call_record`,
`log_external_text_record` are unchanged by this pass and remain exactly as
certified/uncertified as documented in `docs/CONNECTOR_AUDIT.md`. This pass
neither expands nor narrows their status.
