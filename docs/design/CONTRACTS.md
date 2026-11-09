# Shared contracts

Every part of Job Hunter follows these design conventions: where code lives, how identity and storage work, the data model, the HTTP contract, how background work is handled, the allowance rule and the security boundary. The [main design](README.md) gives the overview.

The exact API shapes are in the committed [`contracts/openapi.json`](../../contracts/openapi.json); a test fails if the running app and that file disagree.

## 1. Repository layout

```text
apps/web/                       # React single-page app (07)
backend/src/job_hunter/
  api/                          # FastAPI app and routers (02)
  adapters/                     # auth, database connections, storage (local files or S3)
  domain/                       # SQLAlchemy models and identity
  profile_bank/                 # profile items, imports, snapshots, export (10)
  preparation/                  # tailoring, cover letters, fit analysis, allowance, PDF rendering (06, 12, 14)
  embedding/                    # embedding client, store, worker logic, For you ranking (05, 11)
  ingestion/                    # job source readers and de-duplication (04)
  llm/                          # model client and the shared LLM worker's tasks (12)
  *_worker.py, migrate_aws.py   # Lambda entry points: embed, LLM, discovery, import, migrate
backend/migrations/             # Alembic migrations (17)
backend/tests/                  # unit tests; integration/ holds the PostgreSQL tests
services/embedder/              # the embedding service used by local Docker Compose
contracts/openapi.json          # committed API description
infra/aws/  infra/state/        # Terraform: the app stack and the state bucket
infra/local/                    # local database role setup
scripts/                        # deployment, operator and smoke-test scripts
eval/                           # evaluation scripts and results (08)
docs/                           # this documentation
```

The frontend API client types follow the OpenAPI file; do not invent API shapes in frontend mocks.

## 2. Identity, versions and storage

- Opaque UUIDs for domain IDs. Timestamps are UTC ISO-8601 in the API. Salaries carry a currency and a period (for example SGD per year), never a bare number.
- One job seeker is one tenant. There are no organisations or teams.
- The user ID is derived on the server: in AWS from the verified Cognito claims (a UUID5 of issuer and `sub`), locally from the dev user. A browser never selects its own tenant through a body field or header.
- Profile content is versioned. The profile bank (`profile_items`) is editable; **confirming** the profile takes `expected_bank_revision` and stores an immutable snapshot in `profile_versions` (with a content hash). Fit analysis, letters and ranking read the confirmed snapshot, so editing the bank does not change an analysis that already ran.
- Jobs are shared. A job is identified by `(source, source_board, external_id)`, and a repeat import refreshes the row rather than creating a new one. A posting that appears on two sources keeps one row per source, linked by `canonical_job_id` (see [04](04-JOB-INGESTION.md)).
- Private files live in the documents bucket as `uploads/<user_id>-<id>.<ext>` and `exports/<user_id>-<id>.pdf`. The server chooses every key. The database stores the object reference with its S3 version ID, never an expiring signed URL. Upload size is capped at 10 MiB.
- Shared job records hold listing data only: no resumes and no private generated material.

## 3. Data model

These are the tables the migrations create (`backend/src/job_hunter/domain/models.py` plus raw SQL for the embedding tables). JSON columns hold variable structured content; ownership, status and revision are real columns. Tables marked private have row-level security keyed on `user_id`; see [02](02-BACKEND-AND-DATA.md).

| Table | Purpose and key constraints |
|---|---|
| `users` (private) | UUID, unique `auth_subject`, display name, `plan` (`free` or `premium`, server-managed) |
| `profiles` (private) | One row per user: basics draft, `revision`, `bank_revision`, confirmed revision |
| `profile_items` (private) | The profile bank: experience, projects, skills and so on, each with bullets, wordings, tags, origin, `revision` and `archived_at` |
| `profile_imports` (private) | A resume import awaiting review: source, parser, candidate items, status, applied result |
| `profile_versions` (private) | Immutable confirmed snapshot; unique `(user_id, revision)`; content hash |
| `preferences` (private) | Roles, locations, work modes, seniority, salary minimum with currency and period; `revision` |
| `user_settings` (private) | Resume defaults; `revision` |
| `uploads` (private) | Uploaded resume file: object reference, declared size, content type, status, page count, extracted text, SHA-256 |
| `jobs` | Shared listing: title, company, location, work mode, description, skills, source, board and external ID, status, category, seniority, salary, posted and expiry dates, `canonical_job_id`, `match_key`, `also_seen_on`. Unique per source, board and external ID, and unique `dedup_key` |
| `job_embeddings`, `profile_embeddings` | `vector(512)` per text version, with model, dimensions, input hash and status. Profile rows are private |
| `job_match_features` | Seniority and other features of a job that sit outside the vector |
| `job_requirements` | Requirements read from a posting by the model; shared by all users and reused while the posting is unchanged |
| `job_reviews` (private) | `saved` or `dismissed` per user and job; unique `(user_id, job_id)` |
| `applications` (private) | Tracker row: status, notes, applied date, attached resume and cover letter, `revision`; one per user and job |
| `documents` (private) | A resume or cover letter: template, content, layout, `revision`, `reviewed_revision`, optional job |
| `document_exports` (private) | A rendered PDF of one reviewed revision of a document |
| `ai_tailor_uses` (private) | The allowance: one row per user and job for the month the slot was used |
| `fit_analyses` (private) | One latest analysis per user and job: status, profile revision, checked result, error code |

Embeddings use one 512-dimension space (`jinaai/jina-embeddings-v2-small-en`) for jobs and profiles. Every row records the model, dimensions and text version, so incompatible vectors are never compared; a model change needs a backfill.

## 4. HTTP contract

Base path `/v1`. JSON uses snake_case. Collections return `{"items": [...]}`; lists that can be long take `limit` (default 20, maximum 100) and `offset` and return `next_offset` (null on the last page). Errors have one shape:

```json
{"error": {"code": "...", "message": "...", "request_id": "...", "details": {}}}
```

No response exposes a stack trace or reveals whether another user's resource exists: unknown and foreign private resources both return 404.

| Area | Routes |
|---|---|
| Health and identity | `GET /health` (public, no database) · `GET /me` (identity, plan, monthly allowance, which AI features are available) |
| Profile | `GET/PUT /profile` (basics, with `expected_revision`) · `POST /profile/confirm` · `GET /profile/bank` · `POST /profile/items`, `GET/PATCH/DELETE /profile/items/{id}`, bullets, alternatives, `revert`, `PUT /profile/items/order` · `GET/PUT /settings` · `GET /profile/export.json` · `DELETE /profile/data` |
| Resume import | `GET/POST /uploads`, `GET/PATCH/DELETE /uploads/{id}`, `GET /uploads/{id}/download` · `PUT /uploads/{id}/content` (local) or a presigned S3 URL then `POST /uploads/{id}/finalize` (AWS) · `GET/POST /profile/imports`, `GET /profile/imports/{id}`, `apply`, `discard`, `retry` |
| Preferences | `GET/PUT /preferences` (with `expected_revision`) · `GET /preferences/seniority-options` |
| Discover | `GET /recommendations` (keyword ranking) · `GET /recommendations/for-you` (semantic ranking; 404 `FOR_YOU_DISABLED` when off) · `GET /jobs/{id}` · `PUT /jobs/{id}/review` (`saved`, `dismissed` or `none`) · `GET /jobs/reviewed` |
| Tracking | `GET /applications` · `PUT /applications/{job_id}` (status, notes, attached resume and letter, with `expected_revision`) |
| Fit analysis | `POST /jobs/{id}/fit-analysis` (202) · `GET /fit-analyses/{id}` · `GET /jobs/{id}/fit-analysis` · `GET /fit-analyses` |
| Documents | `GET/POST /documents` · `POST /documents/from-bank` · `POST /resume-builds/suggest` · `GET/PATCH/DELETE /documents/{id}` · `restore`, `duplicate`, `tailor`, `review`, `preview.pdf`, `exports` · `GET /exports/{id}` |
| Cover letters | `POST /jobs/{id}/cover-letter` (modes `write`, `improve` or `blank`) |

Application statuses are `saved`, `preparing`, `applied`, `interviewing`, `offer`, `rejected` and `withdrawn`. Saving a job creates a `saved` tracker row; un-saving removes it only if it is still untouched (no notes, no attachments, no status change), so dismissing never destroys tracking history. Corrections and backwards transitions are allowed, and a click never marks a job as applied.

Status codes:

- 401 `AUTH_REQUIRED`: no valid sign-in.
- 404 `NOT_FOUND`: unknown or foreign resource.
- 409: a revision conflict (`REVISION_CONFLICT`) or a failed precondition such as `PROFILE_NOT_CONFIRMED` or `REVIEW_REQUIRED`.
- 422: invalid input.
- 402 `AI_LIMIT_REACHED`: the monthly allowance is used up.
- 503 `AI_NOT_CONFIGURED` or `AI_UNAVAILABLE`: the model cannot be used.

Concurrent edits are handled with revisions: an update sends the revision it read and gets 409 if it is stale. We do not use idempotency keys; the AI actions are protected instead by the one-slot-per-job rule and by refusing to start a second analysis while one is pending.

An export needs the current revision of the document to have been **reviewed** first, so the user always sees what is exported. The export renders a PDF in the request and stores it in the bucket; in AWS `GET /exports/{id}` returns a short-lived signed download URL as `{"url": ...}` (uncached), and locally it returns the PDF.

## 5. Background work

There is no generic task table or queue. Three small patterns cover all slow work; the reasoning is in [02](02-BACKEND-AND-DATA.md).

1. **Embedding.** After the profile is confirmed or preferences are saved, or after a job import, the API or the import function writes an empty flag object to S3. S3 sends it to SQS, and the embed Lambda embeds whatever is pending. The flag carries no data, so duplicate or merged flags are harmless. Failures retry up to five times, then land in a dead-letter queue and raise an alarm. See [11](11-EMBEDDING-WORKER.md).
2. **Fit analysis.** The API writes `llm-requests/<id>.json`, the LLM worker writes `llm-results/<id>.json`, and the web app polls `GET /fit-analyses/{id}`. A pending analysis with no answer after 5 minutes is reported as failed. See [12](12-FIT-ANALYSIS.md).
3. **AI resume rewrite and cover letters.** The same request and result files, but the API waits inside the request for at most 25 seconds. On a slow or failed worker, tailoring returns the rule-based copy, a cover letter is not created, and no allowance is used.

A request file has this shape, where `input` contains only what that task needs:

```json
{"request_id": "...", "task": "fit | tailor | cover_letter", "input": {}}
```

Request and result files expire from the bucket after one day because they hold profile text. The LLM worker has no database access, and the API checks every answer before it is saved or shown.

Locally the fit analysis runs as a background task in the API process and the other AI calls run inline; the states the web app sees are the same. A pause (reserved concurrency 0 on the API, embed and discovery functions) stops the API, embedding and job pulls in AWS without touching the database.

## 6. Allowance semantics

The allowance counts **jobs**, not model calls. A user has 5 (free) or 50 (premium) jobs per Singapore calendar month, stored as the month the slot was used and computed on the server.

- The first successful AI action on a job takes one slot. Fit analysis, AI tailoring and AI cover letters for that same job in that month share the slot, so doing all three costs one.
- A slot is spent only when the model returns a usable result that passes our checks. A failed or discarded result costs nothing.
- A fit analysis that is still running counts against the limit, so starting several at once cannot go over it.
- Manual editing, rule-based tailoring, blank letters, review and export are free.
- Premium is a plan value an operator sets (`scripts/set_plan.py`); there is no payment or checkout. See [13](13-PRICING-AND-PLANS.md).

## 7. Security and AI boundary

- The browser signs in with Cognito using the authorisation-code flow with PKCE (Proof Key for Code Exchange, which protects the code without a client secret) and no client secret. Accounts are created by an operator; there is no public sign-up or social login. API Gateway requires the `jobhunter/use` scope on every route except `GET /health` and the CORS preflight, and the backend checks the issuer, client, token type, expiry and scope again, rejecting ID tokens.
- `X-Dev-User` works only with `AUTH_MODE=local`, and the app refuses to start in that mode outside `local` or `test`.
- Private tables have forced row-level security; runtime roles are not owners and have no `BYPASSRLS`. User context is set transaction-locally and a missing context returns no rows. Never trust a body-supplied user ID or use the migration role in a request handler.
- Resume and job text is untrusted data, including any instructions inside it. Prompts keep instructions separate from quoted data, give the model no tools or network actions, and ask for structured output. Before anything is stored, the code drops evidence IDs that were not supplied, and any number or name that is not in the source material; the fit coverage percentage is computed in code, not by the model. User-edited text is kept distinct from AI-written text.

## 8. Shared test conventions

- Python unit tests are in `backend/tests/` and database tests in `backend/tests/integration/` (enabled with `RUN_DB_INTEGRATION=1`). Unit tests run offline with no cloud credentials.
- Frontend tests are colocated `*.test.ts` and `*.test.tsx` files, run with Vitest.
- Terraform has `terraform test` files in `infra/aws/tests/` and `infra/state/tests/`.
- Clocks, model clients and storage are injected so business logic can be tested without patching it away. Fixtures are synthetic or permitted, and tests contain no real resumes, tokens or secrets.
- Cloud and live-provider checks are separate, opt-in commands (`scripts/smoke.py`, the `eval/` scripts), never part of the offline suite.
- `make test` runs the frontend tests, backend tests and the smoke test against the local stack.

## 9. Source references

Scope follows the preliminary report; the implementation choices here are ours.
