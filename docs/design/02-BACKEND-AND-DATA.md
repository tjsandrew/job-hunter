# 02 — Backend, database and tenant isolation

The backend is one Python package that holds the API, the schema and migrations, the identity check, the row-level security that keeps users apart, and the handling of slow work. The AWS side is in [01](01-INFRASTRUCTURE.md) and [What runs where on AWS](../architecture/aws-overview.md); the shared conventions are in [contracts](CONTRACTS.md).

## Shape of the backend

The code is in `backend/src/job_hunter/`. The FastAPI app in `api/main.py` (plus the routers in `api/profile_bank.py`, `api/fit_analysis.py`, `api/cover_letters.py` and `api/resume_build.py`) is the only HTTP surface. The same app runs under `uvicorn` locally and inside Lambda through Mangum (`api/lambda_handler.py`), so there is one code path for both.

Small adapters in `adapters/` hold the differences between local and AWS: `auth.py` (who the caller is), `database.py` and `aws_config.py` (connections), `storage.py` (local files or S3). Domain logic does not know which one it is using. We did not build a generic plugin framework; each adapter is a few functions.

Other entry points are plain functions that Lambda calls or a person runs: `migrate_aws.py`, `embed_worker.py`, `llm_worker.py`, `discovery_worker.py` and `import_worker.py`.

## Slow work: three simple patterns, not a task engine

The original design had a task table, an outbox, leases and a repair job. We did not build it. There are only a few kinds of slow work, and each has a natural shape, so a general engine would have added more failure modes than it removed:

| Work | Pattern | If it fails |
|---|---|---|
| Embeddings | The API writes an empty S3 flag after a save. S3 → SQS → the embed Lambda embeds whatever the database says is pending. Embedding is idempotent, so a lost, repeated or merged flag changes nothing | The queue retries up to 5 times, then the dead-letter queue and an alarm. A failed embed never fails the save |
| Fit analysis | The API adds a `fit_analyses` row marked `pending` and writes `llm-requests/<id>.json`. The LLM worker writes `llm-results/<id>.json`. The web app polls `GET /v1/fit-analyses/{id}`; the API reads the result, checks it, saves it and marks the row `ready` | A pending row older than 5 minutes is reported as failed (`TIMEOUT`). Nothing is charged for a failed result |
| AI resume rewrite and cover letter | Same request and result files, but the API waits inside the request for up to 25 seconds (the API Lambda stops at 29 s and API Gateway at 30 s) | A slow or failed worker returns the rule-based copy, or no letter, and spends no allowance |

Locally there is no worker Lambda: the fit analysis runs as a background task in the API process and the other AI calls run inline. The state machine the web app sees is the same.

Why not a generic queue: the three patterns above cover every feature we shipped, each stores its own state in a table the user can already read, and the embed flag can be delivered more than once without harm, so we do not need exactly-once delivery. The cost is that a failed AI call is not retried automatically; the user can retry.

## Identity and the authentication boundary

In AWS, the only source of identity is the claims that API Gateway's JWT authorizer has already verified. `adapters/auth.py` reads them from the Lambda event and checks again that the issuer and client match, the token is an **access** token (ID tokens are rejected), it has not expired, and it carries the `jobhunter/use` scope. Anything else is a 401.

The user's internal ID is derived from the token (a UUID5 of `issuer#sub`), so the caller can be identified before any database lookup. That matters because the `users` table is itself protected by row-level security; a new user's row is created on their first request with `INSERT ... ON CONFLICT DO NOTHING`. Browsers never choose their own tenant through a body field or header.

Local development uses an `X-Dev-User` header (`alice` or `casey`) instead, and only when `AUTH_MODE=local`. The settings module refuses to start with that mode unless `APP_ENV` is `local` or `test`, and AWS mode refuses to start without Cognito, S3 and an explicit database host and user.

## Tenant isolation: row-level security and roles

Each request opens one transaction and runs `SELECT set_config('app.user_id', :id, true)` first. The `true` makes the setting local to the transaction, so it is cleared at commit or rollback and cannot leak to the next request on a reused connection.

Every table holding private content has row-level security **enabled and forced**, with a `tenant_isolation` policy that has both `USING` and `WITH CHECK`:

```sql
user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
```

If the setting is missing the comparison is NULL and no rows are visible, so the failure mode is closed. The policies are created in migrations 0001 (users, profiles, preferences, job reviews, applications, documents, exports, uploads), 0003 (profile versions), 0010 (profile items, imports, settings), 0012 (profile embeddings), 0014 (AI uses) and 0015 (fit analyses). The shared tables — `jobs`, `job_embeddings`, `job_match_features` and `job_requirements` — hold public listing data and derived job features only, with no resumes and no private generated text.

Roles are separate, and none is a superuser or has `BYPASSRLS`:

| Role | Used by | Can do |
|---|---|---|
| `jobhunter_admin` | Operator bootstrap only | Master login; creates the other roles. Not in any function's environment |
| `jobhunter_migrator` | Migrate Lambda | Owns the schema and runs schema changes (DDL, the statements that create and alter tables). Never handles an HTTP request |
| `jobhunter_app` | API and Import Lambdas | Select/insert/update/delete on tables, subject to row-level security. 15 s statement timeout |
| `jobhunter_embedder` | Embed Lambda | Reads jobs, profiles, profile versions and preferences; writes the two embedding tables; one extra read-only policy on `profiles` so it can list users with a confirmed profile. Sets `app.user_id` for each user before touching that user's rows |

PostgreSQL table owners bypass row-level security unless it is forced, and superusers always bypass it. That is why the policies are forced and why the runtime roles are not owners. Cross-table links are checked in the application as well (for example, an application can only attach the caller's own reviewed document); possession of another user's UUID is never enough, and an unknown or foreign resource returns the same 404. IAM alone is not per-user isolation, because several backend roles can reach the whole bucket.

## Connections and limits

AWS uses password login with verified TLS against the bundled public RDS certificate. The API keeps one reused connection per Lambda instance (pool size 1, up to 2 extra for a rare second session), checked before use, and asks PostgreSQL to close it after 60 idle seconds so a warm instance does not keep Aurora awake. We measured that opening a new TLS and password connection on every request kept a 1-ACU (Aurora Capacity Unit) Aurora busy under load, which is why the API reuses one; the workers still open a short-lived connection each time. Reuse is safe for tenant isolation because the user setting is transaction-local.

Timeouts are layered. The API Lambda stops at 29 seconds (API Gateway's own limit is 30), and AI waits inside a request end at 25. The runtime role has a 15 s statement timeout, a 30 s idle-in-transaction timeout and a 60 s idle-session timeout. A model call runs in the LLM worker, outside any database transaction. The database is private, so nothing outside the Lambda security group can open a session; the AWS limits and why they are small are in [01](01-INFRASTRUCTURE.md).

## Data and migrations

The schema is created by 17 Alembic migrations in `backend/migrations/versions/` (the latest is `0017_cover_letter_packets`). The logical tables are in [contracts](CONTRACTS.md). Rules we keep:

- Migrations must apply to an empty database and to the previous schema, and must be backwards compatible, because a failed release rolls the API back but not the schema.
- In AWS, only the migrate Lambda runs them, as `jobhunter_migrator`, under a database lock that stops two migrations running at once. It then re-applies the runtime grants and role timeouts, so every release leaves permissions in a known state. The very first run is the operator bootstrap (`scripts/bootstrap_database.py`), which creates the roles and passwords.
- Embeddings are `vector(512)` from `jinaai/jina-embeddings-v2-small-en`. Each embedding row records the model, dimensions and text version, so vectors from different models are never compared.
- Editable objects (profile basics, profile items, preferences, settings, applications, documents) carry a `revision`; an update sends `expected_revision` and a mismatch returns 409 `REVISION_CONFLICT`.

## Allowance

`preparation/allowance.py` implements one rule: each user has a number of **jobs** per Singapore calendar month on which AI features may be used — 5 on the free plan and 50 on premium. One slot per job is shared by fit analysis, AI tailoring and AI cover letters, so repeating any of them on the same job in the same month costs nothing more. A slot is spent only when the AI returns a usable result, and a fit analysis that is still running counts against the limit so several started at once cannot exceed it. Reaching the limit returns 402 `AI_LIMIT_REACHED`.

Everyone starts on free. Plans are server-managed and there is no payment: an operator changes one with `scripts/set_plan.py`, which calls the migrate Lambda's `set_plan` action. Plans are implemented; premium is a demo plan for now. See [13](13-PRICING-AND-PLANS.md) for pricing and the [deployment guide](../deployment/README.md#changing-a-users-plan) for the command.

## Local mode

`docker compose up` (or `make up`) starts PostgreSQL with pgvector, the API, the embedder service and the web app. The API container runs migrations, grants the embedder's database role its access, seeds two dev users and starts `uvicorn`. The API connects as `jobhunter_app`, a non-owner role without `BYPASSRLS`, so local runs exercise the same row-level security as AWS. S3, SQS and Lambda are not emulated; local storage is a volume and the model call is inline. See [LOCAL-DEVELOPMENT](../LOCAL-DEVELOPMENT.md).

## Tests

- **Unit tests** (`backend/tests/`): validation, error mapping, identity-claim handling, allowance and the Singapore month boundary, tailoring, fit analysis, cover letters, embedding, deduplication, the import pipeline and the Cognito and password connection code. They need no cloud credentials.
- **Database integration tests** (`backend/tests/integration/`, run with `RUN_DB_INTEGRATION=1` against PostgreSQL): tenant isolation through the real non-owner role, concurrent first sign-in of new users, missing user context failing closed, profile bank row-level security on writes, the runtime role timeouts and `set_plan`.
- `contracts/openapi.json` is the committed API description (regenerate it with `make openapi`); `test_openapi.py` fails if the app drifts from it.

Unit tests cannot prove transaction safety or row-level security, so the integration tests are kept separate and run in CI against a disposable PostgreSQL started with Docker Compose.

## Acceptance

- Two users cannot read or update each other's uploads, profile data, documents, exports, applications or analyses, including through direct SQL as the runtime role.
- A missing user setting returns no rows; a reused connection never carries one user's identity into the next request.
- A token with the wrong issuer, client, type or scope is rejected; local `X-Dev-User` has no effect in AWS.
- Only one AI slot is spent per job per month, however many AI features are used on it.
- Every migration applies to an empty database; the API matches the committed OpenAPI file.
