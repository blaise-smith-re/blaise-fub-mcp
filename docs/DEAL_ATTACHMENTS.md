# Files-section attachment links

FUB's registered-system API supports externally hosted file attachments in the
deal's Files section. It does not support uploading file bytes: omitting `uri`
returns 403. This connector links existing canonical Drive originals and never
changes their sharing permissions. Users opening them still need Drive access.

Use `update_contact_deal` with the exact deal ID, expected name and contact ID,
plus `attachment_uri`, `attachment_file_name`, optional `attachment_file_size`
(bytes), and `execute=False` to preview. Execute only when authorized. Do not
combine an attachment with deal-field edits. Each creation is independently read
back by attachment ID and the deal is checked for unintended changes.

Only durable canonical `https://drive.google.com/file/d/FILE_ID/view` links are
accepted. Local paths, temporary signed links and credential-bearing URLs are not
stored. No binary upload, public sharing, deletion or archival is implemented.

Read-back is limited by FUB to attachments created by this registered system.
Check existing Files before creating an attachment. There is no documented list
endpoint and no claim of automatic deduplication. Retain returned attachment IDs;
`get_deal_attachment` can check them. Never retry an ambiguous creation failure
blindly, because it may already have created the attachment.

Sources:
- https://docs.followupboss.com/reference/dealattachments-post
- https://docs.followupboss.com/reference/dealattachments-id-get

Deployment acceptance requires an authorized live attachment creation and
independent read-back, with no changes to the deal's financial or date fields.
Automated tests use synthetic data and no live credentials or client documents.
