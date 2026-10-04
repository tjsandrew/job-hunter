# 02 — Backend, database and task execution

**Current delivery scope:** [local application first; AWS-native services later](DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

**Portability requirement:** follow [LOCAL-TO-AWS.md](LOCAL-TO-AWS.md). Keep this component’s logic shared between local Docker execution and AWS; record adapter differences and unverified cloud checks in its handoff.

Read [README](README.md) and [contracts](CONTRACTS.md). Own shared schemas, migrations, API/auth/task scaffolding and quota logic. Other components contribute domain handlers through this infrastructure.

## Build steps

1. Bootstrap the Python package, dependency lockfile, local PostgreSQL/pgvector, formatting/type checks and pytest database fixtures. Implement small storage/model/source interfaces with fake adapters; avoid a generic plugin framework.
2. Implement the logical schema in CONTRACTS with indexes on foreign keys, task state/due time, source identity and user collections. Add optimistic revision checks for editable objects.
3. Implement Cognito claims mapping, standard errors, pagination, idempotency keys and transaction-scoped ownership. Export OpenAPI and common fixtures for 07.
4. Implement task creation/outbox dispatch, atomic claims, fencing, result commits, retries and maintenance according to CONTRACTS. API responses refer to persisted task IDs even when immediate queue sending fails.
5. Implement monthly quota reservation/consumption/release with transaction locks, unique constraints and per-action deduplication. Distinguish business rejection from retryable technical failure.
6. Implement reviews/tracking endpoints and register feature routes from 03/05/06. Wire handler entry points to the same services used locally.
7. Provide local commands for migrate, seed, run API, process tasks, run discovery and inspect/retry a failed task. Local mode must exercise the same persisted task states, even though it does not emulate SQS transport.

## RLS and roles

Separate migration owner, API runtime, personal worker, job-ingestion runtime and maintenance roles. API/personal worker may access private data only within an explicit user context; job-ingestion role writes only shared jobs and its system tasks. Maintenance has narrowly scoped access to task/outbox/quota metadata for reconciliation, not profile/document bodies. Scope grants by tables or reviewed stored procedures; do not grant global `BYPASSRLS` as a convenience.

Enable and force RLS on private content tables. Use both `USING` and `WITH CHECK` policies. In each transaction set a parameterised local setting, e.g. `SELECT set_config('app.user_id', :id, true)`. The policy compares `user_id` to `NULLIF(current_setting('app.user_id', true), '')::uuid`. Missing settings deny access. Do not leave session-level user settings on a reusable connection. Test interleaved users in the same warm runtime/connection pool. PostgreSQL owners normally bypass RLS unless forced; superusers and BYPASSRLS roles still bypass it. [PostgreSQL RLS](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)

Protect task ownership separately: workers first read minimal task routing metadata under a constrained role/procedure, validate the queued owner against persisted metadata, then set that user's context to load private inputs. Queue-provided ownership alone is not trusted. System-task types cannot be invoked using personal-task endpoints.

Use composite ownership constraints or explicit ownership checks when linking private records; possession of a foreign UUID is not sufficient. Never expose whether a private resource belongs to someone else.

## Connections and limits

Use a small pool with maximum one connection per Lambda environment initially, no overflow, short connection acquisition timeout, and recovery from stale connections. Reuse connections safely but keep transactions short. Budget the sum across reserved concurrency; monitor PostgreSQL connections. Introduce RDS Proxy only after a measured need, with costs documented. [AWS Lambda/RDS guidance](https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html)

Separate HTTP request timeout, DB statement timeout and model timeout. External generation stays out of the API request. Use bounded SDK retries so an invocation can persist state before timing out.

## Unit tests required during implementation

Use pytest for request/domain validation, error mapping, identity-claim handling, idempotency-key mismatch rules, allowed task transitions, retry classification, lease/deadline decisions, monthly-period calculation in Singapore, quota-action eligibility and application-status validation. Inject the clock and use fake repositories/queue publishers for deterministic business-logic tests. Include successful, invalid-input, boundary and failure cases.

Unit tests cannot prove transaction safety or RLS. Also run real PostgreSQL integration tests for concurrent quota reservations, uniqueness, outbox claims, fencing, migrations and tenant isolation. Keep those visibly separate from unit tests.

## Acceptance tests

- Two users cannot read/update each other's uploads, profiles, tasks, analyses, documents, exports or applications, including direct SQL using runtime roles.
- Missing user context fails closed; reused connections do not leak identity; ownership-changing updates fail.
- Concurrent identical POSTs create one logical task; same idempotency key with different payload returns 409.
- Crash after DB commit/before SQS send is repaired; crash after send/before mark-sent produces one visible result despite duplicate delivery.
- Active lease duplicates cannot create concurrent committed results; expired leases recover; stale fencing tokens cannot complete tasks.
- Six concurrent requests for different jobs permit only five free monthly reservations. Three action kinds for one job consume one slot. Failed-only work releases capacity; success plus failure does not release a consumed slot.
- Deadline/retry/month-boundary cases preserve usage accounting. Editing profile during processing preserves captured inputs.
- All migrations apply to an empty database and the previous schema; OpenAPI matches frontend fixtures.

Deliver `docs/handoffs/02-backend.md` with actual commands, schemas, test results and unresolved integration points.
