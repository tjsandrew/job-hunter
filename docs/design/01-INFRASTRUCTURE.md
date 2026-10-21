# 01 — Infrastructure and deployment

**Current delivery scope:** [local application first; AWS-native services later](../deployment/DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

**Portability requirement:** follow [LOCAL-TO-AWS.md](../deployment/LOCAL-TO-AWS.md). Keep this component’s logic shared between local Docker execution and AWS; record adapter differences and unverified cloud checks in its handoff.

Read [README](README.md) and [contracts](CONTRACTS.md). Own `infra/`, build/deploy scripts and the operations runbook. Deliver a reproducible CDK deployment, not console-only setup.

## Current assignment boundary

For the local milestone, provide Dockerfiles/Compose, persistent development volumes, environment examples and local startup/test commands. The CDK, AWS resources, Lambda packaging and cloud acceptance criteria below make up the cloud milestone. Do not emulate these services locally.

## Resources and connections

| Resource | POC configuration |
|---|---|
| VPC | Two availability zones; public subnet for NAT; private egress subnets for functions; isolated DB subnets; one NAT gateway |
| RDS | Small supported burstable PostgreSQL instance selected after regional price check; Single-AZ, encrypted storage, 7-day backup retention, no public access; pgvector migration |
| Lambda | Five functions from shared backend package; API 1024 MB, discovery 512 MB, job/personal workers 1024 MB, maintenance 512 MB as starting values |
| API Gateway | HTTP API, explicit JWT-protected application routes, public `/health`; CORS restricted to deployed SPA origin and explicit dev origins |
| Cognito | User pool, public SPA client, code + PKCE, API resource-server scope; verified callback/logout URLs |
| SQS | Two queues plus two DLQs; contracts define timeouts/retry settings |
| S3 frontend | Private bucket, CloudFront Origin Access Control, immutable asset caching, short caching for index |
| S3 documents | Private, encrypted, versioning enabled, public access blocked; constrained browser CORS; no CloudFront public distribution |
| S3 routing | SPA path fallback to index only for frontend routes, not API or missing asset errors |
| EventBridge | Six-hour discovery trigger; one-minute maintenance trigger; target retry policy and failure destination; permission scoped to target function |
| Secrets Manager | Per-role database credentials and enabled source API credentials; no secrets in frontend or source control |
| CloudWatch | Structured logs, 14-day POC retention, alarms for DLQ, worker failures, old queue messages and DB connection pressure |

Initial reserved concurrency: API 10, discovery 1, job worker 2, personal worker 3, maintenance 1. Set SQS mapping maximum concurrency to 2 and 3 respectively. Validate the account's concurrency quotas before deployment; if reservation settings are unavailable in a small/new account, explicitly reduce limits/configuration rather than failing silently. Total DB connection budget must include each Lambda environment's connection-pool size, migrations and operator access. These small limits deliberately protect RDS/Bedrock and may throttle a 100-user test.

## Networking decision

Functions needing RDS use private subnets and the function security group. RDS accepts PostgreSQL only from authorised function/migration security groups. Internet egress uses NAT; being in a public subnet would not give a standard Lambda a public IP. An S3 gateway endpoint is a useful addition; do not add a fleet of paid interface endpoints without a cost comparison. [AWS VPC internet access](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc-internet.html)

The deployed staging environment deliberately has **no NAT** to save cost; embedding there uses an S3 flag, an SQS queue and a dedicated worker instead of a direct call, and should switch to a direct SQS send if a NAT or SQS endpoint is later provisioned. See [11 Embedding worker](11-EMBEDDING-WORKER.md).

This topology supports external job APIs, Bedrock, SQS sends and secret retrieval. Keep outbound connections/timeouts explicit. The Lambda service polls SQS through its event source mapping; code still needs network access for any SDK requests it makes.

## Packaging and migration

1. Package shared backend dependencies once with handler-specific entry points. Use a Lambda-compatible build environment for native packages and PDF fonts. Keep one architecture consistently across build and deployment.
2. Export non-secret resource configuration to backend and frontend environment files through deployment outputs. Browser code receives only public API/Cognito identifiers.
3. Run migrations in the VPC through a deployment-only Lambda or documented short-lived runner; this is separate from the five runtime functions. Never expose RDS publicly to run migrations. Keep DDL credentials unavailable to normal handlers.
4. Separate foundation/data stack from application stack so updates do not recreate the database. Retain data resources on accidental stack deletion; provide an explicit cleanup command requiring the target environment name.
5. Seed two synthetic users/jobs only in development. Test token validation, presigned storage, RLS, real queue delivery and model connectivity from deployed functions.

## IAM and deployment preflight

Give each function only its queues, bucket prefixes, secrets and model invocation permissions. Discovery/job processor cannot read private resumes. The API cannot invoke Bedrock. Maintenance can dispatch tasks and repair state but cannot download resumes. Where backend roles can access multiple users' prefixes, application ownership checks remain required; IAM alone is not per-user isolation.

Check account/region, supported PostgreSQL/pgvector, Bedrock model access/inference profile, source credentials, quotas and estimated fixed cost. Default to Singapore; do not silently switch region to make a model call work. Never embed personal resumes in deployment assets or logs.

Prepare `cdk synth`, diff, deploy, migrations, smoke test, rollback and cleanup commands. Actual paid deployment follows the user's authorization. Report whether checks used mocks, local services or AWS.

## Unit tests required during implementation

Use the CDK assertions library with the project's TypeScript test runner. Test the synthesised template without deploying: private/encrypted buckets, non-public RDS, protected API routes, scoped permissions, worker concurrency, queue visibility/redrive settings, scheduled targets and data-retention behaviour. Assert meaningful security/resource relationships rather than snapshotting the entire template. Deployment smoke tests remain separate.

## Acceptance

- CDK synthesis succeeds; security assertions reject public RDS/buckets and unauthenticated application routes.
- A fresh authorised deployment produces a working SPA → JWT API → RDS request and a real queue task.
- Unauthenticated/expired/wrong-scope requests fail; valid tokens work.
- Secrets are absent from build artefacts; generated upload credentials cannot target arbitrary keys.
- Queue/DLQ alarms and logs exist; a deliberately failed task is observable.
- Runbook lists fixed-cost resources, deletion behaviour and restore/rollback procedure.
- No Fargate, ALB, Redis, separate vector database or provisioned Lambda concurrency is added by default.
