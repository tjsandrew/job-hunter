# Six-person implementation work split

Prepared 9 October 2026. Proposed ownership for the next cloud POC milestone; names can be assigned by the group. Based on the existing local application and [cloud deployment handoff](CLOUD-DEPLOYMENT-HANDOFF.md). No cloud provisioning is authorized by this document.

Keep one repository and the existing React/FastAPI/PostgreSQL architecture. Reuse implemented local features rather than rewriting them. Each owner supplies implementation, relevant unit tests, integration evidence and a short handoff. Working in parallel does not require six microservices.

## 1. Cloud infrastructure and release pipeline

**Own:** CDK infrastructure, environment configuration, networking, IAM, Secrets Manager, CloudWatch, deployment and rollback workflow.

- Provision S3/CloudFront hosting, private document storage, RDS, API Gateway/Lambda and Cognito resources with input from their feature owners.
- Provision queues, DLQs and schedules as workers become ready. Infrastructure owner owns resources; feature owners own handlers.
- Implement GitHub Actions AWS OIDC releases, resource outputs, budgets/alarms and a documented teardown/restore procedure.
- Package and deploy the backend Lambda runtime with Person 2; publish the frontend build with Person 6.

**Done when:** a reproducible development environment deploys, configuration is documented, CDK assertions pass, and a deployed API/frontend smoke test succeeds. Record actual costs and rollback steps.

**Depends on:** agreed runtime, API/auth/storage requirements from Persons 2–6. This is an ongoing integration role, not only initial setup.

## 2. Backend, authentication and data foundation

**Own:** FastAPI Lambda entry point, Cognito identity integration, database migrations/roles/RLS and shared API contracts.

- Port the existing API using an ASGI adapter; replace fixed development identities with verified Cognito subject-to-user mapping.
- Preserve transaction-local tenant isolation and non-owner database access. Manage migrations separately from Lambda invocation.
- Define shared interfaces for storage, tasks and model use with the other owners; avoid owning all feature implementation.
- Configure connection/concurrency limits with Person 1 and verify health/error handling.

**Done when:** two real accounts can use the API and cannot access each other's records, spoofed development headers grant no access, connection reuse preserves RLS, migrations run reproducibly, and affected tests pass.

**Depends on:** Person 1's database/identity/API resources. Can develop the entry point, mapping and tests locally first.

## 3. Profiles, resume storage and application documents

**Own:** profile confirmation, uploaded resumes, storage interface/S3 adapter, PDF rendering/export and application packet backend.

- Port local upload/export storage to private S3 with authenticated upload-init/finalize and authorized downloads.
- Preserve immutable reviewed PDF revisions and application ownership links; retain working local storage for development.
- Package Latin Modern fonts and validate deployed PDF output. Keep the existing structured editor and renderer.
- Integrate generated drafts from Person 5 without bypassing user review; work with Person 6 on preview/download behavior.

**Done when:** upload → extract → confirm → edit → review → export → attach to application works on AWS, files stay private, repeated finalization is safe, and subsequent edits do not alter attached PDFs. Add storage/ownership/revision regression tests.

**Depends on:** Person 2's identity/data foundation and Person 1's S3/IAM resources. Owns document transport endpoints; coordinate changes in shared routes with Person 2.

## 4. Live Singapore job discovery and ingestion

**Own:** source adapters, normalization, source provenance, import checkpoints, scheduled discovery and shared job-processing handlers.

- Deploy the existing bounded Greenhouse/Lever imports through EventBridge-triggered Lambda.
- Add durable checkpoints, backoff/error reporting, stale-job policy and deduplication improvements appropriate to available sources.
- Improve useful job-description coverage and category diversity through permitted source access; do not promise a numerical target before source access is established.
- Produce canonical, versioned job inputs for recommendations and AI; coordinate embedding input/version contracts with Person 5.

**Done when:** a real scheduled cloud import runs, obeys source limits, recovers from failures, avoids duplicate source records and supplies readable Singapore job descriptions with provenance. Record sources, counts and coverage limitations.

**Depends on:** Persons 1–2 for schedule/runtime/data access. Can improve parsers and fixture tests immediately without live fetching.

## 5. Recommendations, AI tasks and allowance enforcement

**Own:** existing lexical ranking baseline, optional semantic ranking, Bedrock fit/tailoring, persistent task/outbox execution and AI allowance transactions.

- Deploy and evaluate lexical recommendations first; reuse the current TF-IDF/skills/role logic.
- Implement task status, reliable queue publishing/reconciliation, idempotent workers, retries/DLQ behavior and stale-input protection.
- Enforce the intended configurable five-distinct-jobs monthly free allowance atomically, including documented failure/retry behavior.
- Add real Bedrock generation and embeddings only after model access is confirmed. Store model/input versions and evaluate factual grounding and recommendation quality.

**Done when:** lexical ranking has reproducible evaluation; AI tasks complete with polling and reviewable outputs; duplicate delivery cannot duplicate results or consume allowance twice; failures recover; generated claims remain grounded in confirmed facts. Clearly label any deferred model functionality.

**Depends on:** confirmed profiles/documents from Person 3, canonical jobs from Person 4, foundation/resources from Persons 1–2.

**Scope caution:** this is the largest new-code package. Deliver task reliability plus one generation flow before expanding semantic ranking. Persons 2 and 4 review transaction and job-version interfaces; the group can defer semantic ranking rather than overload this owner.

## 6. Frontend integration and end-to-end evaluation

**Own:** cloud login/session UI, API configuration, profile/editor/tracker/task UI integration, responsive/accessibility review and cross-feature browser acceptance.

- Reuse the existing frontend; replace development identity controls with real sign-in/out and expired-session handling.
- Integrate S3 upload/download flows, application-linked preparation, task polling, errors and allowance feedback.
- Refine resume editor/discovery/tracker usability; verify desktop/mobile layouts, keyboard navigation and clear loading/error states.
- Coordinate the end-to-end acceptance script, user feedback and evaluation report with measurements supplied by every owner.

**Done when:** a fresh user can sign in and complete the deployed job → profile → preparation → reviewed PDF → tracker journey; browser tests cover key flows; unit/build checks pass; usability findings and unresolved limitations are recorded.

**Depends on:** contracts from Persons 2–5. Can use deterministic mocks until endpoints are available; mocked flows do not count as cloud acceptance.

## Parallel work and integration order

1. **Agree contracts first:** user identity, job/profile versions, upload/finalize/download, task status, allowance behavior and environment outputs. Record changes in [CONTRACTS.md](../design/CONTRACTS.md). Agree file ownership when editing the shared API module.
2. **Start all six in parallel:** infrastructure; API/auth boundary; storage adapter/PDF tests; source parsers/checkpoints; task/ranking logic; frontend auth/integration scaffolding.
3. **First deployed slice:** Persons 1–3 and 6 prove login → profile → manual resume → private PDF download. Person 4 adds scheduled real jobs; Person 5 deploys lexical ranking.
4. **Second slice:** Person 5 adds reliable asynchronous fit/tailoring; Persons 3 and 6 integrate editable drafts, review and application attachments. Semantic ranking follows only if time/access allow.
5. **Joint release gate:** every owner supplies their tests and operational evidence. Person 6 coordinates the user journey; Person 1 coordinates release/rollback. Integration and quality remain everyone's responsibility.

## Common handoff requirements

For each package, record files changed, commands, passing/failing/skipped tests, real AWS verification, configuration prerequisites and remaining gaps. Unit tests are offline; use disposable PostgreSQL for database tests and real cloud integration tests for IAM, Cognito, S3, SQS and networking. Do not populate the shared demo with test resumes.

Use small reviewed branches/PRs and keep deployment secrets out of Git. Do not overwrite another owner's code or silently change shared contracts. Preserve local Compose operation. Source backup does not back up local Docker volumes or deployed user data.

The first cloud POC can demonstrate manual preparation plus lexical recommendations before AI is ready. Payment collection, automatic application submission, browser automation and custom model training remain outside this split.
