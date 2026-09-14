# Deal field repair

The update tool previously checked only `peopleIds`. Live FUB deal reads return
expanded `people` objects, so a correctly linked contact was rejected. The repair
reads expanded objects, retains legacy ID-list support, and rejects inconsistent
representations. Exact deal ID, expected name, contact linkage and write scope
remain required.

Deal create/update now expose `commission_value`, `agent_commission` and
`team_commission` as nonnegative whole-dollar amounts, not percentage rates.
Omitting an amount preserves its current value; zero is an explicit amount.
Do not include brokerage fees in commission unless the controlling business
instructions require it. Compute splits from confirmed terms, not default ratios.

Update read-back now compares requested fields, contact links and deal users.
Ignored or mismatched values return `WRITE_VERIFICATION_FAILED`, never success.
Date read-back accepts FUB's midnight timestamp representation of a date.
Custom fields must match existing custom-field definitions; they cannot override
native contact links or ownership.

API references:
- https://docs.followupboss.com/reference/deals-post
- https://docs.followupboss.com/reference/deals-id-put

The public PUT reference spells the split fields inconsistently with POST and
GET responses. The implementation uses `agentCommission` and `teamCommission`
from POST and observed GET records; an authorized live write and independent
read-back must confirm these values before claiming deployment acceptance.

Deployment acceptance: deploy this commit to the existing full connector, refresh
its tool schema, preview an authorized existing deal update, execute only the
source-supported fields, and read back the exact values. Do not create a duplicate
deal or weaken OAuth/identity checks to test the repair. Local tests use synthetic
records and make no live CRM calls. The historical read-only service is unchanged.
