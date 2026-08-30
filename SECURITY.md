# Security / Operating Controls

- Never commit FUB or Auth0 secrets to GitHub.
- Exact person/task/deal/appointment targeting is required before write.
- Prefer preview (`execute=false`) before novel or consequential writes.
- No delete tools are exposed.
- No global shared FUB structure-management tools are exposed.
- Shared tag changes require explicit confirmation that Brent/team approval exists.
- Appointment invitations can cause email/SMS side effects and require explicit send authorization.
- `log_external_call_record` and `log_external_text_record` only log externally completed activity.
- Contact email/phone updates overwrite the entire FUB list; the tool requires expected-current-state matching.
- Missing API-visible activity does not prove no activity occurred in FUB UI or another system.
  The daily control audit and the closeout workflow both encode this explicitly — see
  `docs/DAILY_CONTROL_AUDIT.md`.
- `close_out_contact_interaction` additionally requires assigned-owner verification before
  any write, checks for exact-duplicate notes/tasks before writing, independently re-reads
  every write it makes, and diffs the contact and its other open tasks before vs. after to
  catch anything unrelated that changed. See `docs/SAFE_CLOSEOUT.md`.
- Data minimization: note/task/closeout text is screened before any write or log for
  apparent passwords, SSNs, account/routing numbers, wire instructions, and TrustFunds
  secret words (`redaction.py`); a match is rejected, never stored, and never echoed back
  in the rejection message.
- The daily control audit never scans the account on its own — it only reads the exact,
  caller-supplied contacts it is given.
- No new tool in this connector creates or edits a shared FUB stage, Smart List, tag
  definition, action plan, automation, lead-flow rule, or team template.
