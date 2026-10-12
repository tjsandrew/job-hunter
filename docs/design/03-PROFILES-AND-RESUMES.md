# 03 — Profiles and resume processing

**Current delivery scope:** [local application first; AWS-native services later](../deployment/DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

**Portability requirement:** follow [LOCAL-TO-AWS.md](../deployment/LOCAL-TO-AWS.md). Keep this component’s logic shared between local Docker execution and AWS; record adapter differences and unverified cloud checks in its handoff.

Read [README](README.md) and [contracts](CONTRACTS.md). Own `profiles/`, resume extraction handlers and associated API services; coordinate migrations with 02.

## User flow and scope

User uploads a resume → background extraction → user reviews/corrects facts → explicitly confirms → embedding becomes ready for matching. Support text-based PDF initially, maximum 10 MiB and 20 pages. Reject unsupported/encrypted/corrupt files clearly. Scanned PDFs can return `OCR_REQUIRED`; OCR and DOCX input are optional later enhancements. Let users enter profile facts manually so an unsupported resume does not block the whole journey.

Structured profile fields: display/contact details, summary, skills, experience (employer, role, dates, achievements), projects and education. Give every experience/project/achievement a stable fact ID. Preserve source page/text evidence for extracted content and distinguish user-entered facts. Do not infer employers, dates, certifications, salaries or achievements that were not supplied.

## Implementation

1. API creates an owned upload record and constrained presigned POST with key/type/size restrictions and short expiry (default five minutes).
2. Browser uploads directly to private S3. Completion checks ownership and object metadata, then captures its S3 VersionId. Enable bucket versioning so reuse of an upload URL cannot change the bytes an accepted task processes. Local storage adapter must emulate immutable content references.
3. Extraction worker downloads the captured version, verifies byte signature/type/limits, extracts bounded text, and optionally uses the text model to map it into the profile schema. Treat PDF links/embedded instructions as data; do not fetch URLs or execute embedded material.
4. Persist extraction as a draft. If the user has already edited a newer draft, retain extraction as a reviewable candidate rather than overwriting their edits. Save the task result's expected draft revision and use a compare-and-set update.
5. Confirmation creates an immutable version containing stable fact IDs, then enqueues `EMBED_PROFILE_VERSION`. The active confirmed version can be shown while its embedding is pending; keyword recommendations remain available with a visible notice.
6. Construct embedding text from role history, relevant skills/projects and summary, excluding contact/address fields. Use the model/preprocessing version from shared configuration. Store its hash and embedding provenance.
7. Return user-understandable parse/model errors through task status. Log IDs/counts/timings, not extracted resume text or contact details.

Profile confirmation is an explicit user action. A generated CV must use a confirmed version and must not silently modify the user's source profile.

## Interfaces and fixtures

Implement `extract_resume(storage_ref) -> ProfileDraft`, `confirm_profile(user_id, expected_revision) -> ProfileVersion`, and `embed_profile_version(version_id)`. Models/adapters remain injectable. API services use the paths in CONTRACTS.

Include synthetic fixtures: normal PDF, multi-page PDF, empty/scanned-like PDF, corrupt PDF, misleading embedded instruction text and missing dates. Never commit a real teammate's resume without their permission.

## Unit tests required during implementation

Use pytest for upload filename/type/size/page-count validation, object-version selection, extracted-profile schema validation, missing-field handling, stable fact IDs, draft revision conflict decisions, confirmation rules and embedding-text construction. Test that contact fields are excluded from embedding text and late extraction cannot replace a newer draft. Mock storage/model boundaries; include malformed model responses and unsupported/corrupt document cases. Use small synthetic PDF fixtures for parser tests and label tests involving the real parser as component tests where appropriate.

## Acceptance

- Upload bypasses API payload limits; foreign upload IDs and arbitrary keys fail.
- Reusing an upload URL cannot change the frozen object version being extracted.
- Text extraction yields editable facts with evidence; unsupported documents give actionable messages and manual-entry fallback.
- Late extraction cannot overwrite a newer user draft.
- Editing a draft does not change confirmed versions; confirmation/embedding retries do not create duplicate active versions.
- Job/profile embeddings share model/dimension/preprocessing configuration.
- Contact details remain out of ranking text/logs; private file download requires ownership.
- An uploaded original can be deleted through the API after extraction; document the separate lifetime of confirmed facts and backups.

Deliver a handoff note with supported formats/limits, prompt/schema versions, fixture results and unverified cloud behaviour.
