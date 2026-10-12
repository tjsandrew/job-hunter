# Delivery scope: local application first, AWS-native services later

**Resume editor requirement:** [09-RESUME-EDITOR.md](../design/09-RESUME-EDITOR.md) adds a core local resume editor, manual resume creation, template/layout controls, preview, autosave and PDF export. Its document/API extensions supersede assumptions that every resume requires AI generation or a job.

This staging decision reflects the user's latest direction: preserve AWS portability while avoiding time spent recreating cloud services locally. It takes precedence over earlier wording that requires cloud adapters, infrastructure or distributed-delivery machinery during the local milestone. The AWS design remains the eventual target, not a prerequisite for local development.

## Build now versus defer

| Area | Build for the local milestone | Defer to the AWS milestone |
|---|---|---|
| UI and API | React, FastAPI, stable routes/schemas, validation and error handling | API Gateway, Lambda adapter/packaging and CloudFront deployment |
| Data | Actual PostgreSQL + pgvector in Docker, migrations, ownership/RLS, tracking and quotas | RDS provisioning, backups, connection tuning and optional proxy |
| Authentication | Two seeded development identities behind an explicit local-only guard; test authorisation | Cognito sign-up/login/recovery, JWT authorizer and real token lifecycle |
| Files | Small filesystem storage adapter backed by a Docker volume; owned upload/download endpoints and immutable file references | S3 adapter, presigning, bucket versioning/policies and lifecycle rules |
| Background work | Persisted tasks, one local runner calling shared task functions, visible states, explicit retry, result idempotency | SQS publication/polling, outbox dispatcher, DLQs, distributed leases/fencing and maintenance Lambda |
| Scheduling | Commands to run discovery and pending tasks manually; optional simple runner loop | EventBridge schedules and target failure handling |
| Live jobs | Real permitted source retrieval from the laptop, normalisation, deduplication and freshness | Verification of source access from AWS networking |
| Recommendations | Filters, keyword ranking and pgvector queries using a compatible real embedding model if available | Bedrock embedding integration if AWS access is unavailable |
| AI-assisted preparation | Schemas, prompt construction, grounding checks, editing/export and fake responses for workflow tests; use an already available real provider through a thin adapter if practical | Bedrock-specific integration and quality evaluation if no real model is available |
| Operations | Local logs, reproducible Compose setup, environment template, unit/database/browser tests and Git | IAM, VPC/NAT, Secrets Manager, CloudWatch alarms, cloud scaling/cost measurements and full CDK deployment |

Do not install LocalStack, a local Cognito clone, a message broker, a local secrets platform, or an S3 emulator merely to imitate AWS. Add a local dependency only when it is needed to exercise a concrete product feature and saves more effort than it adds. The default local services are frontend, API, PostgreSQL and one worker; files use a persistent volume.

## Preserve the application, not a local replica of AWS

Use small interfaces only at boundaries that actually vary: storage, identity resolution, task execution/publication and model/source clients. Keep business rules, task functions, schemas and database migrations shared. Implement the local side now; document the AWS mapping without writing placeholder AWS implementations that falsely appear complete.

The single local worker may process persisted queued tasks sequentially. On startup, interrupted running tasks can be marked failed/retryable under this single-worker constraint. Keep task creation and quota reservation transactional and retries idempotent. Do not implement a distributed queue, visibility timeout simulator, outbox or fencing system for this milestone. Before allowing multiple AWS workers, implement and test the full cloud reliability contract in CONTRACTS.md. Outbox and distributed lease columns/tables may be introduced with later migrations.

Local file uploads can use a development-only backend upload route through the storage abstraction. The upload initiation API should return transport instructions so the browser does not hardcode a filesystem or S3 implementation. Preserve opaque upload IDs, ownership and immutable file references; do not emulate signed S3 URLs or expose filesystem paths. AWS uploads later go directly to S3 to avoid API Gateway/Lambda payload limits. This is a deliberate adapter/transport difference, not a promise of byte-identical infrastructure behaviour.

Use development identities only on localhost/local mode. Do not build custom passwords or token issuance as temporary production authentication. Keep ownership enforcement active. Deployment validation must reject local identity mode before any cloud release.

Synthetic vectors and fake generated documents can test plumbing, but do not demonstrate semantic matching or AI quality. Label them. If an existing real model is usable, track its provenance and vector dimensions; otherwise mark real semantic/AI acceptance as deferred while completing the keyword and editing/export flows. Do not spend the POC schedule hosting a model solely to avoid Bedrock.

## Two separate completion gates

### Local milestone

- Reproducible Docker startup, migrations and synthetic seed data.
- Frontend/backend workflow, real database persistence and isolated development users.
- At least one live job source, with two as the multi-source target; external access blockers stated explicitly.
- Upload/manual profile, job review/tracking, ranking, editable documents and export to the extent supported by available real models; mock-only features labelled.
- Relevant unit tests plus actual PostgreSQL/component/browser tests pass.
- Shared business logic has no hardcoded AWS events or local paths; cloud adapter mapping and deferred tasks are recorded.

Cloud-specific acceptance criteria in other briefs do not block this milestone. Passing the local milestone does not mean the course's deployed SaaS requirement is complete.

### AWS milestone, later

Implement native Cognito, S3, SQS, EventBridge, Bedrock, Lambda/API Gateway and deployment infrastructure when cloud work begins. Add distributed task-delivery guarantees before running concurrent cloud workers. Test actual permissions, network access, event delivery, failure recovery and production builds. Then measure cloud latency/scaling/cost and complete the deployed web-service evaluation.

## Instructions to implementers

Default to the local milestone unless the user assigns cloud work. For each handoff report `implemented locally`, `verified with a real external service`, `mocked`, and `deferred to AWS` separately. Do not interpret future cloud acceptance checklists as an instruction to recreate AWS locally. Continue building the application when a cloud dependency is deferred; never claim that a fake passed the corresponding real-service acceptance test.
