# Local POC → AWS deployment handoff

Updated 5 October 2026. **No AWS deployment has been performed.** This is an implementation inventory and deployment plan, not evidence that cloud components exist. Read with [delivery scope](DELIVERY-SCOPE.md), [shared contracts](../design/CONTRACTS.md), [portability rules](LOCAL-TO-AWS.md) and [current outstanding work](../status/PENDING.md). Cloud work begins only when assigned; this note does not authorize provisioning or spending.

## What can be reused, and what still needs building

| Component | Actually built locally | Cloud destination | Work still required |
|---|---|---|---|
| Web application | React/TypeScript/Vite discovery, profile, tracker, resume editor, preview and export flows | Private S3 frontend bucket + CloudFront | Build production `dist`; provision hosting and SPA routes; configure API/auth URLs and Cognito login/logout; remove development identity controls. The current web Dockerfile runs a development server. |
| HTTP API | FastAPI routes, schemas, validation and SQLAlchemy persistence | API Gateway HTTP API → standard Lambda | Add maintained ASGI adapter and Lambda entry point; package dependencies; configure CORS, JWT authorization, timeouts and concurrency. Current backend Dockerfile starts Uvicorn and is not a Lambda image. |
| Identity and tenant isolation | Fixed Alice/Bob development identities; transaction-local user context and PostgreSQL RLS | Cognito + JWT authorizer + existing RLS | Implement real accounts and verified JWT-subject mapping to internal user UUIDs. Replace development-header identity resolution; preserve transaction-local RLS and non-owner database access. A configuration flag alone does not implement Cognito. |
| Database | PostgreSQL 16/pgvector, Alembic migrations, ownership constraints, profiles, jobs, applications, document records | Private RDS PostgreSQL/pgvector | Provision networking/backups; validate regional engine/extension versions; run migrations separately; manage credentials and Lambda connection budgets. Keep runtime and migration roles separate. |
| Profile/resume upload | Local file storage and PDF text extraction with manual confirmation | Private document S3 + API finalize flow; extraction worker if needed | Extract storage interface from route/file logic; add presigned upload, validation/finalization and authorized download. Preserve confirmation semantics. Local filesystem paths must become durable object references. |
| Resume editor and PDF rendering | Structured editor, autosave/revision conflicts, layout controls, Latin Modern font, review gate, deterministic ReportLab PDF | Same frontend and rendering code; private S3 for exported PDFs | Package fonts/native dependencies for Lambda; write temporary output to `/tmp`, then persist to S3. Port preview/download transport and test the actual deployed PDF. No hosted LaTeX service is required for the current renderer. |
| Application tracker/packets | Status/notes, application-linked resume preparation, immutable reviewed PDF attachment, manual cover letter and download | API Lambda + RDS + private S3 | Preserve owner-scoped references and exact exported revision; authorize every download. Tracker records manual/external applications; it does not submit applications. |
| Job discovery | Bounded public Greenhouse/Lever import commands; normalization/upsert; Singapore source data and local snapshots | EventBridge → bounded discovery Lambda; SQS workers for processing stages | Add deployed handler, schedule, durable checkpoints, source backoff and monitoring. Retain source provenance. Source coverage is limited; source identities are not necessarily distinct vacancies. No production continuous discovery schedule exists yet. |
| Basic recommendations | Deterministic eligibility filters, lexical TF-IDF/skills/role ranking | Reuse in API Lambda | Benchmark query/memory/latency at target corpus size; optimize only when measured. This baseline needs no Bedrock or separate ML host. |
| Semantic recommendations | Planned, not implemented | Bedrock embeddings + pgvector | Add actual model adapter, versioned embeddings, compatible dimensions and backfill/reprocessing; evaluate ranking quality against lexical baseline. Verify regional model access first. |
| AI fit analysis/tailoring | Honest unavailable state; manual editing/export works | SQS personal-task Lambda → Bedrock | Build generation and evidence validation, persistent task status/polling, retries and stale-input checks. Do not describe current manual documents as AI-generated. |
| Distributed tasks and free allowance | Planned contracts, not a working production queue/quota system | RDS task/outbox/quota state + SQS/DLQ + workers/maintenance | Implement atomic distinct-job monthly reservations, reliable publishing/reconciliation, duplicate-safe handlers, leases where needed, failure/refund policy and polling. Do not assume Docker already tested these cloud semantics. |
| Operations/deployment | Local Compose, tests and Git source backup | CDK, GitHub Actions, CloudWatch, Secrets Manager/IAM | Build IaC, release workflow, secrets/configuration, alarms, cost controls, restore and rollback procedures. `infra/local` is not AWS infrastructure. |

## Compute decisions relative to the preliminary design

- Replace the proposed Fargate API service and its ALB with **API Gateway HTTP API + Lambda**. ALB can invoke Lambda, but is unnecessary for this selected API design.
- Replace bounded Fargate background processing with **SQS-triggered Lambda workers**. Keep SQS and dead-letter queues: Lambda executes work; it does not replace durable queueing.
- Replace a continuously running discovery process with **EventBridge-triggered bounded Lambda invocations**. Preserve rate limits and split large imports into resumable batches.
- Keep **RDS/pgvector, S3/CloudFront, Cognito, EventBridge, Secrets Manager and Bedrock where required**. These provide persistence, delivery, identity or managed inference rather than application compute.
- Fargate is a fallback if measured work requires long-lived processes or cannot be split below standard Lambda's 15-minute limit. It is serverless container compute, not a VM we manage. The current local workloads do not demonstrate a need to retain it.

See [AWS API Gateway integration](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway.html), [Lambda limits](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) and [ALB integration](https://docs.aws.amazon.com/lambda/latest/dg/services-alb.html).

## Porting instructions by boundary

### Frontend hosting

Run `npm ci` and `npm run build` in `apps/web`; deploy the resulting `dist` rather than the Node/Vite development container. Supply public API/Cognito configuration at build time or through an explicit public runtime configuration file. Never put server secrets into `VITE_*` variables.

Use CloudFront origin access control with a private S3 REST origin. Configure SPA deep links without masking API errors as HTML; use a separate API domain or deliberately route `/v1` to API Gateway. Verify auth callback/logout URLs and cache invalidation on release. Personal API responses and private documents must not inherit public asset caching. [AWS private S3 origin guidance](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)

### FastAPI and identity

Add a thin Lambda/ASGI entry point around `backend/src/job_hunter/api/main.py`. Choose a Lambda-compatible zip or container build and prove Linux/architecture compatibility for psycopg, ReportLab and packaged fonts. Keep business logic callable from local tests and commands. Do not run seeding or Alembic migrations during Lambda invocation or cold start.

Add a trusted authenticated-user boundary replacing `DEV_USERS` resolution in `adapters/database.py`. Validate JWT issuer/audience and required authorization at the gateway; backend identity must come from verified claims through the chosen adapter, never an arbitrary client header. Map Cognito subjects to internal users. Continue setting `app.user_id` inside each database transaction, clearing state through transaction completion. Test reused connections with different users.

### Database and networking

Match local PostgreSQL major version where available, enable the supported `vector` extension and run existing Alembic migrations through a controlled deployment job. Use a privileged migration role and a separate runtime role that neither owns tenant tables nor bypasses RLS. Importing local demo/user data is a separate explicit decision; default to a new cloud database and clearly labelled fixtures.

The existing engine has a small pool per process. Multiple warm Lambda instances multiply that pool: set reserved concurrency and pool sizes against RDS capacity. Start with the documented direct connection design; add RDS Proxy only if measurements justify it, validating transaction-local RLS behavior and proxy pinning rather than assuming it solves all connection issues. [AWS Lambda/RDS guidance](https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html)

Private RDS requires VPC access. VPC Lambda functions calling public sources or model APIs need a deliberate egress/endpoints design. The current target uses one NAT gateway for POC simplicity; RDS and NAT retain fixed costs. A split discovery topology can be evaluated later, but must include durable handoff to database-connected processing.

### Files, uploads and exports

Introduce a storage interface supporting local filesystem and S3 implementations. Persist stable object keys and, where used, S3 version IDs instead of laptop paths. Keep ownership, document revision and exported PDF metadata in PostgreSQL.

Use an authenticated upload-init/finalize protocol with short-lived presigned transport. Enforce the current PDF/type/size policy, verify object presence/content and make finalization duplicate-safe before extraction. Large uploads should bypass API Gateway payload transport. Do not trust only the browser's MIME declaration. Store original uploads and immutable exports privately; authorize against database ownership before issuing short-lived downloads. Never overwrite an already attached reviewed export when its editable source changes.

Lambda `/tmp` is scratch space only. Write a generated PDF there, upload it successfully, then commit its durable export reference using a recoverable failure policy. Port browser preview/download code to the new authorized transport. Include fonts and their licenses in the deployment artifact. Local named Docker volumes persist application data; Git backs up source, not those volumes.

### Discovery and asynchronous work

Reuse `ingestion/discovery.py` and normalization logic behind a scheduled entry point. Keep requests bounded, checkpoint batches durably and obey source backoff. Verify source access from AWS; successful laptop access does not prove cloud access. Never run discovery on every user request. Do not retry the previously rate-limited source aggressively.

Build workers when enabling AI/embedding processing. Persist task input versions and status; use outbox/reconciliation so a database commit followed by a failed queue send does not lose accepted work. SQS delivery may repeat: ensure handlers are idempotent, stale results cannot overwrite newer revisions, and quota reservations are atomic. Configure visibility timeouts, retries, maximum concurrency and DLQs; use partial batch failure reporting when batching records. Return task IDs and poll for long work rather than holding HTTP requests open. [AWS SQS error handling](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html)

### Recommendations and models

Deploy the lexical baseline first. Preserve confirmed-profile inputs and filter/ranking behavior; measure cloud performance before adding a separate service. Bedrock is additional functionality, not needed to make this baseline run.

For embeddings, record model ID, dimension, text-format version and source content version; never compare incompatible vectors. For generation, use confirmed facts, evidence references and human review, with timeouts and token/cost limits. Add model-dependent features only after real account/region access and quality tests. Shared contracts define the intended five-distinct-jobs monthly free allowance; enforcement remains implementation work.

## Suggested deployment sequence

1. **Preflight:** select account/region, confirm billing authorization and service/model access, inspect current source and outstanding work. Agree the first cloud milestone: manual workflows plus lexical recommendations can ship before AI.
2. **Infrastructure:** implement CDK stacks for private database, frontend/document buckets, identity, API, IAM/secrets, networking and logs. Add queue/schedule resources when their handlers are ready. Record actual resource names and environment outputs.
3. **Database release:** provision roles/extension and run migrations once through a network-capable release job. Verify RLS with real runtime credentials. Do not copy local hardcoded passwords.
4. **API/file port:** add verified identity, S3 adapter, upload finalization and Lambda handler; deploy and smoke-test profile → job → tracker → reviewed export before publishing frontend.
5. **Frontend release:** build with cloud configuration, upload assets and invalidate changed entry files. Test login, SPA deep links, editing, application-linked preparation and PDF downloads in the deployed browser.
6. **Discovery:** enable a conservative schedule after one bounded cloud import passes. Measure source coverage and errors; document schedule, backoff and stale-job policy.
7. **Async/AI milestone:** implement task/outbox/quota machinery, then add real embeddings and generation. Exercise failures and duplicates before enabling these for users.
8. **Acceptance:** run cloud integration/load checks, record latency/cost/user feedback, and publish actual deployment/rollback/cleanup commands in the release handoff.

There is no executable CDK deployment command yet because AWS infrastructure code has not been written. The cloud implementer must supply reproducible bootstrap/deploy commands and environment prerequisites after building it, rather than treating this plan as a runnable release.

## Tests and release gates

Keep unit tests deterministic and offline. Reuse backend/frontend tests; run PostgreSQL integration tests in a disposable database so test resumes do not pollute the demo workspace. Add tests around new storage, identity, task and model boundaries, plus CDK resource assertions.

Cloud-only acceptance must prove:

- Two real Cognito accounts cannot read/edit each other's profiles, documents, applications or export URLs; spoofed development headers grant no access. Reused database connections preserve isolation.
- Private S3 objects cannot be fetched publicly. Upload finalization handles missing/invalid objects and repeated requests. Exact reviewed revisions remain attached after source edits.
- The packaged PDF renderer loads Latin Modern fonts and produces a readable deployed PDF; preview/download work after a fresh browser session.
- Queue duplicates, failed batches, lost initial publishing, worker failure and DLQ recovery do not duplicate outputs or consume allowance twice. Stale inputs cannot overwrite current edits.
- Scheduled discovery obeys source limits and resumes bounded batches. Real model access and output quality are verified separately from fake/offline tests.
- Auth callbacks, deep links, CORS, expired sessions, API errors and deployed mobile layouts work. Load measurements include Lambda latency/throttles and database connections.

Configure alarms for API/worker errors, queue age/DLQ messages, throttling, database capacity and cost. Log request/task IDs and failure categories without resume text, tokens or signed URLs. Define document retention/deletion and database backup/restore procedures; local fixture archiving is not a production retention policy.

Use GitHub Actions with AWS OIDC and narrowly scoped environment roles rather than long-lived AWS keys. Keep Secrets Manager access in server roles. Separate migration and app releases; use backward-compatible schema changes where needed. Record rollback strategy without deleting existing document objects or export references.

## Handoff checklist for cloud implementers

- [ ] Inspect actual source and latest handoffs; do not mark planned components as implemented.
- [ ] Implement IaC, runtime/configuration, identity and S3 boundaries.
- [ ] Prove manual local workflows on AWS before expanding AI scope.
- [ ] Implement schedules, queues, reliable tasks and quotas where the assigned milestone needs them.
- [ ] Run unit, disposable-PostgreSQL and cloud integration tests; distinguish each result.
- [ ] Record deployed commit, resource/environment outputs, commands, costs, failures, remaining gaps, rollback and cleanup steps.

Do not reintroduce test-resume clutter, deploy cloud resources merely from this document, or claim external applications were submitted by the tracker.
