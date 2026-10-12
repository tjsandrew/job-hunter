# 06 — Fit analysis, tailored documents and export

**Resume editor requirement:** [09-RESUME-EDITOR.md](09-RESUME-EDITOR.md) adds a core local resume editor, manual resume creation, template/layout controls, preview, autosave and PDF export. Its document/API extensions supersede assumptions that every resume requires AI generation or a job.

**Current delivery scope:** [local application first; AWS-native services later](../deployment/DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

**Portability requirement:** follow [LOCAL-TO-AWS.md](../deployment/LOCAL-TO-AWS.md). Keep this component’s logic shared between local Docker execution and AWS; record adapter differences and unverified cloud checks in its handoff.

Read [README](README.md) and [contracts](CONTRACTS.md). Own `preparation/` and personal-task handlers for analysis, resume, cover letter and export. The output is editable assistance grounded in the user's confirmed experience.

## Task inputs and output schemas

Inputs always pin `profile_version_id`, `job_version_id`, model/prompt/schema versions and user ownership. Reject unconfirmed profiles and unready job versions with actionable errors. Keep personal outputs private.

Fit analysis contains `strengths`, `gaps`, `uncertain_requirements`, and `requested_documents`. Each item includes job requirement evidence and supporting profile fact IDs where present. Phrase missing evidence as “not evidenced in this profile”, not an assertion that the person lacks the skill. Do not output hiring probabilities or a fabricated competitiveness percentage.

Resume draft contains sections and grounded bullet objects: `{text, source_fact_ids}`. Cover letter contains editable paragraphs with supporting fact IDs. Preserve actual names/employers/dates/qualifications. Prompts may reorder, select and rephrase facts, but may not invent numbers, experience or credentials. Only include application-document requirements actually stated in the listing; clearly separate optional suggestions.

## Implementation

1. Task creation uses 02's idempotency/quota transaction. Each monthly job slot allows the action kinds defined in CONTRACTS. Reuse successful existing output for identical requests.
2. Read captured versions, minimise personal data sent to the model, format untrusted content as quoted data, and invoke the configured Bedrock model with bounded tokens/timeouts.
3. Validate JSON structure and evidence references. A valid ID is necessary but not sufficient: perform deterministic checks for protected facts/numbers/dates and reject unsupported additions; manually evaluate grounding on labelled fixtures. Do not claim automated validation proves every paraphrase faithful.
4. Permit at most one bounded repair attempt for invalid structured output. Persist safe error codes/checkpoints so failed tasks do not consume a new action/allowance on retry.
5. Persist the successful analysis/draft and task/quota outcome atomically. Never overwrite a user's edited draft when a delayed duplicate finishes.
6. Editing increments document revision and resets reviewed status. Reviewing applies only to that exact revision. Export requires the reviewed revision and freezes it.
7. Render PDF deterministically from structured content; escape markup and support pagination/fonts. Generated or user text must not execute HTML/scripts. Store under the user's prefix and create an owned export record. Export requests are deduplicated by document ID/revision/format and do not invoke the LLM.
8. Return short-lived signed downloads only after checking export ownership. An edited document produces a new reviewed/exportable revision; an old export remains clearly labelled with its revision.

Use the same personal-task function for profile and document tasks initially, with type dispatch. Split queue/function only if observed document latency starves onboarding. Do not add Step Functions for a few sequential calls without a demonstrated orchestration need.

## Unit tests required during implementation

Use pytest for input readiness/version checks, prompt construction boundaries, response-schema validation, evidence-ID validation, protected fact/number/date checks, bounded repair policy, checkpoint reuse, edit/review revision transitions and export deduplication keys. Include fabricated claims, invalid JSON, provider timeouts and delayed duplicate completions using fake model/storage/repository adapters. Test that export uses the reviewed revision and never invokes the model.

Use deterministic synthetic documents for PDF renderer component tests; verify extracted content, pagination and representative visual output separately. Live Bedrock tests are opt-in integrations, not unit tests.

## Acceptance

- Every personal factual claim is grounded in confirmed input or visibly identified as a user edit; fabrication fixtures are rejected/flagged.
- Listing instructions cannot override generation policy or cause tool use.
- User can read fit evidence, edit both CV and cover letter, review and download a legible multi-page PDF.
- Stale profile/job versions are shown explicitly; changing inputs does not silently regenerate or bypass monthly action limits.
- Model timeout/schema failure returns recoverable status; retries do not double-charge the allowance or overwrite edits.
- Exported PDF matches the reviewed revision, including Unicode text and long sections, without clipping.
- Foreign draft/export/task IDs return 404 and cannot produce signed URLs.
- Inference counts, tokens where available and elapsed time are recorded without private content.

Handoff includes prompts/schemas, grounding limits, rendered synthetic examples, failure tests and model configuration actually tested.
