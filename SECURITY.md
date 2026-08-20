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
