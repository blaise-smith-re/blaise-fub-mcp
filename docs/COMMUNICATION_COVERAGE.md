# Communication coverage — technical contract

This is connector engineering documentation, not a business SOP or a second client database.
Current policy remains in the canonical Drive Manual and FUB/AI Runbooks.

## Exact-person text reads

The existing get_contact_text_messages tool keeps person_id as its only required argument.
A legacy person-only call follows at most five API pages. Optional limit (1–100), next_token,
fetch_all and max_pages allow a bounded read/resume. Only FUB's returned cursor is passed as
a query parameter with the same person filter; arbitrary nextLink URLs are never followed.
No account sweep, send, write, credential change or persistence is introduced.

Raw textmessages are retained. Deduplication across pages is by source message ID. The returned
_completeness reports counts, page exhaustion, changed totals, page cap, repeated cursor,
missing metadata, a safe partial error and a resume cursor. Terminal API pagination is not a
claim of complete communication history. A first-page failure remains an error, never an empty
conversation.

_coverage separates readable, restricted and unavailable bodies in each direction. FUB's privacy
placeholder stays a placeholder; no header/credential workaround attempts to reveal it.
latest_communication is separately attributed to the existing person.lastCommunication field:
it can contain useful latest outgoing text/Inbox content while the SMS endpoint hides bodies.
It is one latest field, not a complete thread or guaranteed untruncated body.

The response also identifies the deployed feature and RENDER_GIT_COMMIT when supplied by Render.
This distinguishes tested source from an observed running revision without exposing secrets.

## Calls, emails and attachments

get_contact_calls retains its existing page/offset behavior and raw logs. _coverage says whether
log notes and recording URL fields were returned. Audio and transcripts are not fetched. A note
explicitly saying "not a phone call" is identified so an external personal-text container is not
mistaken for an actual phone conversation.

There is no general FUB email-body tool in this connector. Use the existing authorized Gmail
connection for original MIME bodies, relevant received/sent messages and attachments. Search
results are discovery, not send proof: inspect the parent message's actual SENT/DRAFT labels,
sender, date and MIME parts. An outbound lender/partner email may concern a client who is not a
recipient, so it needs exact case association instead of assuming it appears on that client's
FUB timeline. Do not duplicate a native communication merely to preserve a useful missing outcome.

Read supported attachments by their actual parent message/attachment ID. If inline extraction
is truncated, use the returned full extraction or original file; never call a preview complete.
FUB's registered-system attachment API has its separate system-ownership restriction; it is
not an account-wide Files reader. Preserve original source references rather than copying private
documents or full communications into public code or routine CRM notes.

## Personal-phone coverage

The connector does not observe an iPhone's Messages database. Owner reports, selected screenshots
or exports can supply evidence during an active task, with honest dates and direction. A Mac or
Windows phone utility alone does not connect that evidence to ChatGPT or FUB.

A prospective Mac bridge requires separate installation/access and live acceptance. Prefer a
read-only, client-allowlisted reader with no send/mark-read/delete tools, private authenticated
transport, stable source IDs, deduplication and a recoverable checkpoint. Keep Apple security
protections enabled. No Apple ID, full-phone database, family chat or credential belongs in this
repository. No personal-message bridge or unattended worker is deployed by this connector patch.

## Primary references

- FUB SMS API restricted results:
  https://docs.followupboss.com/reference/textmessages-get
- FUB call API restricted results:
  https://docs.followupboss.com/reference/calls-get
- FUB's explanation of third-party SMS-content/call-recording restrictions:
  https://help.followupboss.com/hc/en-us/articles/32129566205207-HouseWhisper
- FUB attachment ownership:
  https://docs.followupboss.com/reference/dealattachments-id-get

## Verification

Offline regressions cover the original ten-of-thirteen pagination loss, inbound/outbound
restriction counts, a separately readable latest excerpt, page failure/resume, missing metadata,
changed/incorrect totals, repeated cursors, bounded pages, exact-person rejection and unchanged
tool name/required arguments. Live validation must name the running revision and actual source
coverage; a passing suite or pushed commit alone is not deployment or unattended-run proof.

