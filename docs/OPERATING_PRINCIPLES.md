# Operating principles behind the Daily Control Audit & Safe Closeout tools

Blaise's requested operating style (momentum/follow-through, relationship
care and discretion, a clear next commitment once earned, repeatability,
preparation and clarity, specificity, a referral mindset, simple human
communication, selective non-hype energy) is a **behavioral design input**
for this connector, not something these tools store, tag, or write into FUB.

**Hard rule: no style label, persona name, or coaching reference is ever
written to a FUB note, task, or any other field.** Note and task content
always comes directly from the caller (Blaise or the controlling workflow),
never from a template that could embed this framing. FUB notes stay
factual and source-grounded, per FUB 05.

What the style translates to, concretely, in code:

| Principle | Where it lives |
|---|---|
| Preserve useful relationship context | `close_out_contact_interaction` surfaces the most recent notes and current open tasks in its `context` field before any write, so the note being prepared doesn't contradict recent history. |
| Surface the best next commitment | The `next_commitment_advisory` field flags when a closeout would leave the contact with no open task at all. `audit_contact_daily_control`'s `no_future_task` finding does the same for a standing audit. |
| Prevent vague follow-up | `closeout.is_vague_task_name` rejects bare placeholder task names ("Follow Up", "Call", "Touch base") in both `create_contact_task` and `close_out_contact_interaction` — a task must name the actual next step. |
| Enforce dated next actions | Every task-creation path requires exactly one of `due_date`/`due_date_time`; there is no way to create an undated task through these tools. |
| Prioritize client care over activity counts | The daily-control audit never ranks or scores contacts by call/text volume — it only reports control gaps (missing/overdue/duplicate/conflicting next actions, stale notes, ownership mismatches), each with its evidence. |
| Surface stalled opportunities without creating spam | `audit_contact_daily_control` / `audit_contacts_daily_control_batch` are read-only and only inspect the exact, caller-authorized contacts passed in — no account-wide sweep, no message ever sent. Surfacing a gap is not the same as acting on it. |
