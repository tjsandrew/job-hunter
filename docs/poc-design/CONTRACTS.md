# Shared contracts: all components must follow these

**Resume editor requirement:** [09-RESUME-EDITOR.md](09-RESUME-EDITOR.md) adds a core local resume editor, manual resume creation, template/layout controls, preview, autosave and PDF export. Its document/API extensions supersede assumptions that every resume requires AI generation or a job.

**Current delivery scope:** [local application first; AWS-native services later](DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

Read [the main design](README.md) first. These are normative POC defaults. Change them deliberately and update dependent briefs/tests together.

All components must follow [LOCAL-TO-AWS.md](LOCAL-TO-AWS.md): share domain logic across local Docker and AWS, and switch infrastructure through explicit adapters.

## 1. Repository layout and ownership

```text
apps/web/                       # 07: React application
backend/src/job_hunter/
  api/                          # 02: routes/auth/HTTP adapter
  domain/                       # 02: common task/quota models; feature modules owned below
  profiles/                     # 03
  ingestion/                    # 04
  recommendations/              # 05
  preparation/                  # 06
  adapters/                     # PostgreSQL, storage, model and source implementations
  handlers/                     # AWS Lambda and local task entry points
backend/migrations/             # 02 coordinates all schema revisions
backend/tests/                  # unit and database integration tests
infra/                          # 01: CDK
contracts/                      # 02: OpenAPI export, event schemas and common fixtures
fixtures/                       # synthetic/permitted resumes, jobs and expected results
evaluation/                     # 08: scripts, labelled data, measurements and cost worksheet
docs/                           # runbooks, decisions and per-component handoff notes
```

Generate the TypeScript API client/types from committed OpenAPI. Commit JSON schemas for events and AI outputs. Do not independently invent API shapes in frontend mocks.

## 2. Identity, versions and storage

- Opaque UUIDs for domain IDs; UTC ISO-8601 timestamps; monetary amounts as decimal values with currency and period, never unlabelled floats.
- One job seeker is one tenant in this POC. Cognito `sub` maps to internal `users.id`. No organisations/team tenancy.
- Browser requests never select their own tenant via a body/header. Derive it from verified authorizer claims.
- Profile and job content versions are immutable. Each version stores content hash, creation time, schema version and model/prompt provenance where applicable.
- Tasks capture exact input version IDs. Editing a profile or updating a listing does not mutate an in-flight task's inputs.
- Private object prefix: `users/{user_id}/{resource_type}/{resource_id}/...`. Server chooses keys. Persist object keys/version IDs, not expiring signed URLs.
- Shared job records contain source listing data only; no resumes or private generated material.

## 3. Data model

These are logical tables; 02 writes concrete Alembic migrations, foreign keys, indexes and RLS policies. JSONB is appropriate for variable structured content, not a substitute for searchable status/ownership fields.

| Entity | Required data and constraints |
|---|---|
| `users` | UUID, unique `auth_subject`, plan, timestamps; plan is server-managed |
| `profiles` | user ID, current draft JSON, draft revision, active confirmed version ID |
| `profile_versions` | ID, user ID, confirmed structured facts with stable evidence IDs, content hash, embedding/vector metadata, processing status |
| `preferences` | user ID, revision, roles, locations, work modes, seniority, salary constraint with currency/period, unknown-value policy |
| `uploads` | ID, user ID, key, immutable S3 object version ID after completion, size/type/checksum, status, timestamps |
| `jobs` | ID, active version ID, open/closed status, canonical key, first/last seen |
| `job_versions` | ID, job ID, normalised source fields, cleaned text, content hash, extracted requirements/evidence, embedding metadata, readiness; unique `(job_id, content_hash)` |
| `job_sources` | ID, job ID, source name, external ID, URL, last seen, source content hash; unique `(source_name, external_id)` |
| `discovery_runs` | source, run ID, cursor/window, lease, counters, status, timestamps/error; checkpoint only committed progress |
| `job_reviews` | user ID, job ID, `saved`/`dismissed`, timestamps; unique `(user_id, job_id)` |
| `applications` | ID, user ID, job ID, status, notes, applied time, revision; unique `(user_id, job_id)` |
| `tasks` | ID, nullable user ID for system work, type, exact inputs/hash, state, attempts, lease expiry/token, result reference, error code, timestamps, deadline, unique dedupe key |
| `outbox` | ID, task ID, queue kind, payload version, send status, send lease, attempts, next attempt time; unique logical event key |
| `usage_months` | user ID, Singapore calendar month, allowance and counters; unique `(user_id, month)`; lock for reservations |
| `usage_jobs` | user ID, month, job ID, reservation/consumption state; unique tuple; records completed and pending actions |
| `analyses` | ID, user ID, task ID, job/profile version IDs, structured evidence-linked analysis; unique successful task result |
| `documents` | ID, user ID, task ID, kind, input version IDs, current editable JSON, revision, review status; unique task/kind |
| `document_exports` | ID, user ID, document ID/revision, object key/version, status, task ID |

Start with one embedding column `vector(512)` for both profile/job versions if the selected model supports that configuration. Store model ID, dimensions and preprocessing version; do not compare incompatible vectors. A model change requires a migration/backfill strategy.

## 4. HTTP contract

Base path `/v1`. JSON uses snake_case. Collection response: `{ "items": [], "next_cursor": null }`. Default page size 20, maximum 100. Error: `{ "error": { "code": "...", "message": "...", "request_id": "...", "details": {} } }`. Never expose stack traces or another user's resource existence.

| Method/path | Purpose and response |
|---|---|
| `GET /health` | Public minimal liveness only; no DB/secret details |
| `GET /me` | Current identity, plan and allowance summary; provision internal user idempotently |
| `POST /uploads` | `{filename, content_type, size_bytes}` → 201 `{upload_id, upload_url, fields, expires_at}` for constrained presigned POST |
| `POST /uploads/{id}/complete` | Validate object, freeze version → 202 `{task_id, status_url}` for resume extraction |
| `GET /profile` | Editable draft, revision, confirmed version and extraction state |
| `PUT /profile` | Save draft with expected revision; does not silently confirm it |
| `POST /profile/confirm` | Expected draft revision → new immutable confirmed version and 202 embedding task |
| `GET/PUT /preferences` | Read/update validated preferences, with revision checking |
| `GET /recommendations` | Ranked cards, evidence, ranking/profile/preference versions, cursor, degraded-mode flag |
| `GET /jobs/{id}` | Shared job details, source links, freshness and requirements |
| `PUT /jobs/{id}/review` | `{decision: saved\|dismissed\|none}`; `none` removes decision |
| `GET /applications` | Current user's tracked jobs |
| `PUT /applications/{job_id}` | Upsert status/notes/applied_at, revision check on existing record |
| `POST /jobs/{id}/analysis` | Capture confirmed profile/current ready job versions → 202 task or 200 existing result |
| `POST /jobs/{id}/documents` | `{kind: resume\|cover_letter}` → 202 task or 200 existing draft |
| `GET /tasks/{id}` | State, safe error, result reference, `retryable`; owned tasks only |
| `POST /tasks/{id}/retry` | Terminal retryable task only; starts a new attempt using captured inputs and existing quota reservation rules |
| `GET /analyses/{id}` | Owned structured fit analysis |
| `GET/PATCH /documents/{id}` | Read/edit draft; patch requires expected revision and schema-valid content |
| `POST /documents/{id}/review` | Mark exact revision reviewed |
| `POST /documents/{id}/exports` | Reviewed revision → 202 export task, or 200 cached export |
| `GET /exports/{id}` | Status and short-lived download URL if complete and owned |
| `DELETE /uploads/{id}` | Delete original object versions after dependent extraction finishes; keep confirmed facts unless explicitly deleted |

Application states: `saved`, `preparing`, `applied`, `interviewing`, `offer`, `rejected`, `withdrawn`. Saving a job ensures a `saved` application exists; dismissing a card never destroys tracking history. Allow corrections/backward transitions explicitly; do not infer submission from a click.

Use `Idempotency-Key` on task-creating POSTs. Persist `(user, route, key, request_hash, response)` transactionally, using a dedicated request table or equivalent unique records; mismatched reuse returns 409. Resource revision conflicts also return 409. Invalid data is 422; unknown/foreign private resources are 404; exhausted allowance is 403 `QUOTA_EXCEEDED`; rate limits are 429.

## 5. Tasks, queues and transaction boundaries

Two standard SQS queues: `job-processing` and `personal-tasks`, each with a DLQ. Queue payloads contain identifiers and version, never full resumes:

```json
{"schema_version":1,"event_id":"uuid","task_id":"uuid","task_type":"GENERATE_COVER_LETTER","user_id":"uuid-or-null","input_hash":"sha256","trace_id":"uuid"}
```

Types: `PROCESS_JOB_VERSION`, `EXTRACT_RESUME`, `EMBED_PROFILE_VERSION`, `ANALYSE_FIT`, `GENERATE_RESUME`, `GENERATE_COVER_LETTER`, `EXPORT_DOCUMENT`.

States: `queued → running → succeeded`; transient errors use `retry_wait → running`; terminal states `failed` and `cancelled`. `retry_wait` means the queue will retry, not that the browser should resubmit.

1. API validates ownership/input readiness. In one DB transaction, reserve any quota, capture immutable inputs, create task and outbox entry, and record idempotency response.
2. After commit, attempt SQS send with a short bounded timeout. Mark sent only after acknowledgement. If sending fails, return the persisted task; maintenance retries due unsent entries every minute. Do not lose accepted work or roll back a completed DB transaction conceptually.
3. Outbox delivery is at least once. A crash between sending and marking sent may duplicate the event; handlers must tolerate this. Do not hold a DB transaction open during external calls. Use short leases and row locks to claim outbox entries.
4. Worker loads the persisted task, validates envelope/type/owner/hash, and claims it atomically with a lease and fencing token. Only the current token may publish results or alter quota. Completed/cancelled duplicates are acknowledged. A duplicate with an active lease is retried rather than treated as completed work.
5. Keep DB transactions short. Invoke Bedrock/read S3 outside transactions; then commit results, task success and usage changes together. Use immutable result keys/uniqueness to avoid duplicate visible results. Retry can still incur repeated model charges if a crash occurs after inference but before persistence; do not claim exactly-once inference.
6. Persist intermediate extraction/generation output before later stages such as PDF rendering. Retry resumes from valid checkpoints where possible.
7. Maintenance retries outbox entries, repairs expired leases, and handles tasks that exceed their deadline. Default task deadline 30 minutes, above normal queue retry intervals. When terminalising, fence the old attempt and release quota only if no successful/pending action still needs it. Late workers cannot overwrite terminal state. Drain/inspect DLQs through an operator command; alarm on any messages.

Default function timeout: API 15 seconds; discovery 240 seconds; both queue workers 120 seconds; maintenance 30 seconds. SQS batch size 1, batch window 0, visibility 720 seconds, redrive after 5 receives, source retention 4 days, DLQ retention 14 days. Enable partial-batch failure reporting. Treat these as tunable POC settings, not performance guarantees. [AWS SQS configuration](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html)

The outbox closes the failure gap between database commits and message publication. [AWS outbox guidance](https://docs.aws.amazon.com/en_en/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)

## 6. Allowance semantics

Follow the report's “up to five jobs per month”, not five individual inference calls. Use Singapore calendar months, stored as `YYYY-MM` derived on the server. Default free allowance 5 distinct job IDs/month; premium allowance configurable (POC seed default 50), with no paid checkout.

- First premium action on a job reserves one monthly slot under a locked `usage_months` row. Concurrent requests for the same job share one reservation.
- Fit analysis, one resume and one cover-letter generation for that job share the slot. Default maximum is one successful generation of each kind per job/month, across profile versions; manual editing and repeated export are free. A later profile version requires an explicit regenerate policy change, not an accidental new charge bypass.
- Record exact inputs of the first request for an action. If another request uses new inputs while that monthly action already exists, return the existing action plus a clear `INPUT_VERSION_CHANGED` explanation or 409; never silently present stale output as freshly generated.
- A successful action consumes the slot; technical failures alone do not. Release a reservation only after all its actions are terminal and none succeeded. Retries reuse the action record/reservation. Month rollover does not move accepted work into a new month.
- Enforce application rate limits for free operations too (upload/confirm/export), separately from the commercial allowance. Proposed dev defaults: 10 uploads and 20 profile confirmations/user/day; document these operational protections in configuration.

## 7. Security and AI boundary

Use Cognito authorization-code flow with PKCE for the SPA, no client secret. Require a custom API scope (e.g. `jobhunter/access`) on protected API Gateway routes and validate the issuer/client audience. Explicitly reject ID tokens by checking access-token claims in the backend. Local test authentication is enabled only in local mode and must fail deployment validation if enabled in AWS. [AWS JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html)

All private tables have user ownership and RLS. Runtime roles are not owners/superusers and have no `BYPASSRLS`. Set user context transaction-locally; missing context denies access. See 02 for role separation. Never trust a body-supplied user ID or use the migration role in request handlers.

Resume/job text is untrusted data, including instructions embedded in documents. Model prompts separate instructions from quoted data, use bounded inputs, allow no tools/network actions, require schema-valid output and source evidence IDs. Unsupported personal facts are rejected. User-edited text is clearly distinct from model-grounded content.

## 8. Shared test conventions

- Python unit tests: `backend/tests/unit/`; database/component tests: `backend/tests/integration/`, with explicit markers for external dependencies.
- Frontend tests: colocated `*.test.ts` / `*.test.tsx`; browser journeys in a separate end-to-end directory.
- Infrastructure tests: `infra/test/` with CDK template assertions.
- Inject clocks, UUID generators where deterministic IDs matter, model clients, source clients and storage/queue boundaries. Do not patch away the business logic under test.
- Commit synthetic/permitted fixtures with documented expected outputs. Tests must not contain real resumes, tokens or secrets.
- Bootstrap scripts must expose documented unit, database integration and end-to-end commands; use separate opt-in commands for live cloud/provider checks.
- Unit suites must succeed offline with no cloud credentials. Test normal, edge, invalid and failure paths. Record test results and remaining gaps in every component handoff.

## 9. Source references

The group's report is the scope source: [completed preliminary report](/Users/andrew_tjs/Downloads/Preliminary.pdf). [Course specification](../../References/Project%20Specification.pdf) requires a working web service, system/user evaluation, cloud/on-premise cost comparison and documentation of AI use. Defaults here fill implementation gaps; they are not quotations from those documents.
