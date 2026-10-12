# Local POC to AWS: required portability contract

**Current delivery scope:** [local application first; AWS-native services later](DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

Recorded 4 October 2026 at the user's request. This is a requirement for the local implementation, not a future optional enhancement. Read alongside [README](../design/README.md), [shared contracts](../design/CONTRACTS.md) and the relevant component brief.

## Goal

Build a working local POC using Docker Compose and version-controlled source that can later run on the proposed AWS services. Deployment will require AWS configuration and integration testing, but should not require rebuilding the application's business logic or frontend API integration.

## Service mapping

| Local POC | AWS deployment | What stays shared |
|---|---|---|
| React development server/build | S3 + CloudFront | Frontend source, API client and production build |
| FastAPI through Uvicorn | API Gateway HTTP API + Lambda ASGI adapter | Routes, request/response schemas, validation and domain services |
| Docker PostgreSQL + pgvector | RDS PostgreSQL + pgvector | Schema, Alembic migrations, queries, ownership policies and vector configuration |
| Local task runner | SQS-triggered Lambda workers | Persisted task state, task envelope schema, dispatch and processing functions |
| Local/manual scheduler | EventBridge Scheduler | Discovery and maintenance entry points, bounded processing and checkpoints |
| Local object-storage adapter or S3-compatible store | Private S3 | Storage interface, ownership checks, object metadata and immutable input references |
| Local development identities | Cognito + API Gateway JWT authorizer | Internal user mapping and authorisation rules; authentication verification changes by environment |
| Fake model adapter for tests, optional real provider for local development | Bedrock adapter | Structured input/output schemas, grounding checks and versioned processing logic |
| Environment/local development secrets | Secrets Manager + IAM role credentials | Configuration names and application requirements; secret resolution changes |

Default to a filesystem storage adapter on a persistent volume for the local milestone. Defer S3 presigning/versioning/policy verification to AWS. Do not add an S3 emulator solely for service parity.

## Implementation rules

1. **Keep AWS and local entry points thin.** HTTP routes and event handlers call shared services such as `process_job_version`, `extract_resume`, `analyse_fit` and `export_document`. Business logic must not depend on a Lambda event dictionary, local CLI arguments or Docker hostnames.
2. **Use small explicit adapters.** Define interfaces for object storage, task publication, model invocation, source clients and identity verification. Select implementations through the application's composition/configuration layer, not scattered `if local` branches throughout features. Avoid a large generic framework.
3. **Preserve task semantics.** The local runner processes the same persisted tasks with the same inputs, idempotency and result commits. Use a single local worker with explicit retry; defer distributed leases, fencing and outbox dispatch to the AWS milestone. A local call directly into a task handler must not bypass the production transaction/quota rules. Test duplicate and interrupted execution; local FIFO execution alone does not test real SQS behaviour.
4. **Match the database.** Use the same PostgreSQL major version and a compatible pgvector extension locally and in RDS. Run all migrations, RLS policies and runtime-role tests locally. Do not substitute SQLite. Avoid extensions requiring privileges that the selected RDS environment cannot provide.
5. **Treat compute as stateless.** Do not store durable task state, uploads or user sessions in process memory or container files. Use the database/object store. Temporary working files must be bounded, uniquely named and cleaned up; use configurable temporary storage compatible with Lambda `/tmp`.
6. **Keep operations bounded.** Discovery uses pagination/checkpoints. Worker tasks obey the time/memory budgets in CONTRACTS. Do not introduce persistent browser sessions, an embedded scheduler, an always-running thread or a long-lived local process as a production requirement.
7. **Keep API contracts stable.** Frontend uses a configured API base URL and the same routes/shapes locally and in AWS. Test local CORS and API errors now; defer API Gateway event handling tests to the AWS adapter implementation. Local uploads may use a development backend route; cloud uploads must go directly to S3, as specified in DELIVERY-SCOPE.md.
8. **Separate development authentication.** Fake/local identities exist only behind an explicit local-mode flag. AWS builds/deployments must reject this flag. Authorisation, ownership and RLS checks remain active locally. Real Cognito validation requires a later cloud test.
9. **Version models and vectors.** Fake inference is visibly labelled and cannot become production data. If a different real model is used locally, record its model/preprocessing/dimension versions. Before switching to Bedrock, regenerate incompatible embeddings; do not mix vector spaces or claim local model quality demonstrates Bedrock quality.
10. **Use portable builds.** Pin dependencies and build native Python packages for the selected Lambda operating system/architecture. Keep runtime fonts and assets in the deployable package. A macOS or generic Docker success alone is not Lambda packaging verification.
11. **Externalise configuration.** Commit `.env.example` with names/placeholders; keep actual secrets out of Git. Use AWS role credentials in cloud deployment instead of embedded access keys. Never hardcode account IDs, local absolute paths, bucket names or `localhost` into shared logic.
12. **Version control reproducible inputs.** Commit code, Dockerfiles, Compose configuration, dependency locks, migrations, synthetic fixtures, tests, infrastructure definitions and runbooks. Exclude local database volumes, actual resumes, generated private documents and credentials. Git tracks source; database/object backups need separate procedures.

## Suggested configuration boundary

Document these settings during bootstrap; exact names may be refined consistently across components:

- `APP_ENV=local|test|aws`
- `DATABASE_URL` for local development; a database secret reference for AWS
- `STORAGE_BACKEND`, storage endpoint/bucket and upload endpoint configuration
- `TASK_TRANSPORT=local|sqs` and queue identifiers
- `MODEL_BACKEND=fake|bedrock` plus explicit generation/embedding model versions
- `AUTH_MODE=local|cognito` and issuer/client/scope configuration
- `AWS_REGION`, API origin, frontend origin and bounded task/concurrency settings

Validate configuration at startup/deployment. Fail loudly on invalid combinations such as `APP_ENV=aws` with local authentication or fake inference. Inject adapters in tests so environment variables do not become the only way to substitute dependencies.

## Local commands and tests to provide

Provide documented commands to start the Compose stack, run migrations, seed synthetic data, run discovery manually, process tasks, execute unit/database/browser tests and reset local data deliberately. Persist development data in named volumes; normal shutdown should not erase it.

Unit tests run without AWS credentials. Database integration tests run against real PostgreSQL/pgvector. Add contract tests that run shared cases against local and AWS adapter implementations where practical, with live cloud checks explicitly opt-in. When cloud adapters are implemented later, test their Lambda entry points with representative API Gateway/SQS event fixtures, without claiming this verifies AWS delivery. Those adapters/tests are not required to finish the local milestone.

## AWS migration checklist

- [ ] Shared code runs through both local and Lambda entry points; no duplicated business implementation.
- [ ] CDK can synthesise the planned resources, and Lambda-compatible packages build successfully.
- [ ] RDS accepts the migrations and runtime-role/RLS setup; connection limits are configured.
- [ ] Cognito sign-in and access-token validation replace local identities; test users are mapped/seeded deliberately.
- [ ] S3 direct upload, immutable object version capture and owned downloads work with actual bucket policies.
- [ ] Real SQS delivery, retries, DLQs, outbox recovery and duplicate handling pass cloud tests.
- [ ] EventBridge triggers bounded discovery/maintenance; source access works from the VPC network.
- [ ] Bedrock access is verified and any incompatible local embeddings are rebuilt.
- [ ] Frontend production build uses deployed API/auth configuration; no local/mock mode remains enabled.
- [ ] IAM, secrets, networking, logs and alarms are verified on AWS.
- [ ] Cold starts, timeout behaviour, concurrency and cost are measured in AWS rather than inferred from a laptop.
- [ ] Migration of any desired local data is explicit and tested; synthetic seed data may simply be recreated. Private development data is not uploaded automatically.

Deploying to AWS and pushing to a remote Git repository follow the user's actual authorisation and available credentials. Preparing portable code and infrastructure does not mean a cloud deployment has already been verified.

## Required component handoff statement

Every implementer must report: which code is shared; which local adapters it implemented; which AWS adapters/entry points exist; unit/integration test results; and the exact remaining cloud checks. Mark AWS portability as partially verified until the relevant real-service checks pass.

## Current implementation and deployment runbook

See [Cloud deployment handoff](CLOUD-DEPLOYMENT-HANDOFF.md) for the 5 October 2026 inventory of implemented local features, unbuilt cloud components, adapter changes, deployment sequence and cloud acceptance gates. The portability requirements above are target contracts, not evidence those adapters or distributed workers already exist.
