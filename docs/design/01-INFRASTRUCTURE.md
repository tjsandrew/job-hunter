# 01 — Infrastructure and deployment

Job Hunter runs on AWS as a serverless web app: static hosting, one API function, a pausing database and a few background workers, all in one region. This page gives the reasoning. See also [What runs where on AWS](../architecture/aws-overview.md) for the diagram and flows, and the [deployment guide](../deployment/README.md) for runbooks.

Everything is defined as code under `infra/` and applied with Terraform. Nothing is created by hand in the console, except the one-off bootstrap of the Terraform state bucket (which is also Terraform, in `infra/state`).

## Resources and connections

All resources are in Singapore (`ap-southeast-1`).

| Resource | Configuration |
|---|---|
| Amplify Hosting | Serves the React build over HTTPS on Amplify's own address. The branch is built by the **Deploy staging** workflow, not by Amplify (`enable_auto_build = false`) |
| Cognito | One user pool, accounts created by an operator only, one public web client with the authorisation code flow and PKCE (Proof Key for Code Exchange, which protects the code without a client secret), custom API scope `jobhunter/use`. Access tokens last 60 minutes and refresh tokens one day |
| API Gateway | HTTP API with one `$default` route behind a JWT authorizer (audience = the web client, scope `jobhunter/use`). `GET /v1/health` and the CORS preflight `OPTIONS` route are public. CORS allows only the Amplify origin. Throttle 20 requests/s with burst 40; `/v1/health` 1 request/s with burst 2 |
| VPC | Two private subnets in two availability zones, **no NAT gateway and no route to the internet**, and a free S3 gateway endpoint. The database accepts PostgreSQL only from the Lambda security group |
| Aurora PostgreSQL Serverless v2 | Version 16, one writer, 0–1 ACU (Aurora Capacity Unit, the database's unit of compute and memory), auto-pause after 30 idle minutes, encrypted storage, 7-day backups, deletion protection, not publicly accessible. pgvector is enabled by the first migration |
| S3 documents bucket | Private, versioned, AES-256 encrypted, public access blocked, TLS-only policy, CORS limited to the Amplify origin. Holds uploads, exported PDFs and small working files: request and flag files start background work, result files are outputs, and import snapshots are read through a direct invoke |
| Lambda (API) | Container image, FastAPI through Mangum, ARM64, 2,048 MB, 29 s timeout, reserved concurrency 10, inside the VPC |
| Lambda (migrate) | Same image, handler `job_hunter.migrate_aws.handler`, 512 MB, 300 s, concurrency 1, inside the VPC. Applies Alembic migrations and the role grants, and runs the operator-only plan change |
| Lambda (embed) | Own image with the embedding model baked in, 3,008 MB, 900 s, concurrency 2, inside the VPC. Started by SQS |
| Lambda (LLM worker) | API image, handler `job_hunter.llm_worker.handler`, 512 MB, 300 s, concurrency 5, **outside** the VPC, no database access. Started by an S3 event |
| Lambda (discovery) | API image, 1,024 MB, 900 s, concurrency 1, **outside** the VPC, no database access |
| Lambda (import) | API image, 1,024 MB, 240 s, concurrency 1, inside the VPC |
| SQS | One embed queue and its dead-letter queue (redrive after 5 receives). Message retention 1 day on the queue and 14 days on the dead-letter queue |
| EventBridge | One rule: job pull at 06:00 and 20:00 Singapore time |
| ECR | One repository for the API image and one for the embed image; images are referenced by digest |
| Secrets Manager | The AWS-managed master secret, and one secret holding the separate application and migration (and embedder) database passwords |
| CloudWatch and SNS | Log groups with 7-day retention (14 days for API Gateway access logs), alarms for the embed queue and workers, LLM worker errors, discovery errors and sustained Aurora activity, all to one SNS email topic. A monthly AWS Budget (USD 40) sends separate email alerts |
| GitHub OIDC | A GitHub identity provider and one release role that only the `main` branch can assume. No AWS keys are stored in GitHub |

The code for these is in:

- `infra/aws/main.tf`: Amplify, Cognito, ECR, OIDC and the release role.
- `infra/aws/backend/main.tf`: VPC, Aurora, bucket, API, migrate and API Gateway.
- `infra/aws/backend/embedder.tf`, `llm_worker.tf`, `discovery.tf`, `activity_alarm.tf` and `permissions.tf`: the workers, alarms and permissions.
- `infra/aws/budget.tf`: the monthly budget.

## Why serverless and Terraform

The first plan used AWS CDK, Lambda behind API Gateway, a provisioned RDS PostgreSQL instance, a NAT gateway and Amazon Bedrock. The deployed design keeps the Lambda-and-API-Gateway idea and replaces the rest, for these reasons:

- **Terraform instead of CDK.** `terraform plan` shows exactly what will change before an operator applies it, and the operator applies from their own machine rather than from CI. The state lives in a private, versioned S3 bucket that the `infra/state` stack creates and protects with `prevent_destroy`.
- **Aurora Serverless v2 instead of provisioned RDS.** Use is intermittent (team testing, demos), so scaling to zero and pausing when idle costs less than an always-on instance. It is still PostgreSQL, so the schema, pgvector and row-level security are unchanged. The trade-off is a slow first request after a pause, which the web app handles with a bounded "waking up" screen.
- **No NAT gateway.** A NAT gateway has a fixed hourly cost that would dominate this project's bill. See the next section for how the design works without one.
- **SoCLaaS instead of Bedrock.** Amazon Bedrock isn't available on the course AWS account. The language model is the school's SoCLaaS gateway, called from a worker outside the VPC (see [12](12-FIT-ANALYSIS.md)).
- **No Fargate, load balancer, Redis or separate vector database.** Fargate runs containers on servers that bill all day, an Application Load Balancer (ALB) has an hourly charge, Redis is an always-on cache, and a separate vector database is another service to run. One API Lambda, one database and pgvector are enough for the load we measured.
- **Password database login, not IAM database authentication.** IAM database login isn't available on the course AWS account. Each role has its own password: `jobhunter_app` for requests, `jobhunter_migrator` for migrations, and `jobhunter_embedder` for the embedding worker. The **Deploy staging** workflow copies each password into the right function's environment, so no function needs Secrets Manager at run time (which would otherwise need a paid VPC endpoint).

## Networking decision

The core rule is that **no function can reach both the internet and the database.**

- Functions that need the database (API, migrate, embed, import) sit in the private subnets. The database accepts connections only from their security group.
- Functions that need the internet (LLM worker, discovery) sit outside the VPC and have no database access.
- Without a NAT gateway, a function inside the VPC cannot call the internet, and a function outside cannot call the database. Work that has to cross is passed as a small file in S3 (free through the S3 gateway endpoint) or a direct Lambda call:
  - **Embedding:** the API writes an empty flag object after the profile is confirmed or preferences are saved, S3 sends it to SQS, and the embed Lambda embeds whatever the database says is pending ([11](11-EMBEDDING-WORKER.md)).
  - **AI features:** the API writes `llm-requests/<id>.json`, S3 starts the LLM worker, and the worker writes `llm-results/<id>.json` for the API to read back and check ([12](12-FIT-ANALYSIS.md)).
  - **Job pull:** discovery reads the public job feeds and writes `imports/<id>.json`, then invokes the import Lambda, which reads the file over the S3 gateway endpoint and writes to the database ([04](04-JOB-INGESTION.md)).

A bucket can have only one notification configuration, so the embed and LLM triggers share it and discovery uses a direct invoke instead of a third S3 trigger. If a NAT gateway or an SQS endpoint were ever added, the embed flag could become a direct SQS send; (see [11](11-EMBEDDING-WORKER.md)).

## Limits and cost guards

Each limit protects either the database or the shared model key, and costs nothing when idle:

- **Reserved concurrency** caps each function: API 10, embed 2 (the SQS mapping's maximum concurrency is also 2), LLM worker 5, discovery 1, import 1, migrate 1. Terraform sets these on creation and then ignores later concurrency changes on the API, embed, LLM worker, discovery and import functions (migrate keeps its fixed 1), so the **Pause or resume staging backend** workflow can set the API, embed and discovery functions to 0 without Terraform undoing it.
- **Database connections.** Each API instance keeps one reused connection (at most two overflow connections for the rare second session in one request, three in total) and closes sessions idle for 60 seconds so a warm but idle instance cannot keep Aurora awake. The workers open short-lived connections. The runtime role has a 15 s statement timeout, 30 s idle-in-transaction timeout and 60 s idle-session timeout; the embedder role has longer limits for its batch work.
- **Timeouts match the layers.** The API Lambda stops at 29 seconds (the API Gateway integration timeout is 30 seconds), so work that can take longer (fit analysis) is asynchronous and polled, and the short AI calls wait inside the request for at most 25 seconds.
- **Job pulls.** The schedule adds up to 150 new jobs each time and the **Pull jobs** workflow defaults to 100.
- **Cost alerts.** The budget and the Aurora activity alarm only notify; they never stop anything. The **Pause or resume staging backend** workflow is the manual brake.

## Packaging and release

1. One container image holds the backend. The API, migrate, LLM worker, discovery and import functions run it with different handlers; the embedding worker has its own larger image. Both are built for ARM64 and referenced by immutable digest, never a mutable tag.
2. **Deploy staging** is manual (`workflow_dispatch`) and only from `main`. It needs the **Checks passed** result, pushes the images to ECR, runs migrations through the migrate Lambda, updates each Lambda, then publishes the website to Amplify. If the API fails its health check, it rolls the API back to the previous digest and the release fails. Migrations stay applied, so each one must be backwards compatible. Logic is in `scripts/deploy_aws.py`.
3. Migrations run inside the VPC through the migrate Lambda, never from outside. The database is never exposed to run them. The schema-change (DDL) credentials for `jobhunter_migrator` are held only by that function.
4. Browser code receives only public identifiers (API URL, Cognito client and domain), exported to GitHub variables by `scripts/configure_github_deploy.py`.
5. Terraform is applied by hand by one operator after reviewing the plan; the **Deploy staging** workflow never applies Terraform. The first-time order (foundation, image, backend, database bootstrap, workflow variables) is in the [deployment guide](../deployment/README.md).

## IAM and secrets

Each function has its own role with only what it needs:

- The API can read and write `uploads/*` and `exports/*`, write embed flags, write LLM request files and read LLM result files. It cannot list or delete the request, result or flag prefixes, and it has no queue, model or secret permissions.
- The LLM worker can read request files and write result files only. It has no VPC access.
- Discovery can write `imports/*` and invoke the import function only.
- The embed role can read its queue and write follow-up flags only.
- Because several backend roles can reach more than one user's S3 prefix, per-user isolation does not rest on IAM. The API checks ownership in the database, and PostgreSQL row-level security enforces it (see [02](02-BACKEND-AND-DATA.md)).

Terraform state and saved plans can contain Lambda environment values after a refresh, so the state bucket is private, versioned and encrypted, and plans are treated as secrets and never committed. Resume text is never placed in deployment assets or logs.

## How this is tested

- `terraform fmt`, `validate` and the `terraform test` files in `infra/aws/tests/` (embed worker, LLM worker, discovery and activity alarm) and `infra/state/tests/` run in the **Terraform validation** workflow. They check settings that matter for safety and cost, such as that the LLM worker has no VPC configuration and that a stage-1 plan creates no function.
- The **Local POC checks** workflow builds the real ARM64 Lambda image and checks that every handler imports (API, migrate, LLM worker, discovery and import) and that the certificates and PDF fonts are packaged. The embed image is checked separately.
- Cloud acceptance was run against staging (`eval/results/a6-*`): 26 of 27 acceptance checks passed on 25 October 2026 and one was informational, plus a pause/resume run and a 73-hour Aurora idle check. See [08](08-INTEGRATION-AND-EVALUATION.md) and [eval/README](../../eval/README.md).

## Acceptance

- A fresh authorised deployment produces a working browser → JWT API → database request, and a real background task (an embed or a fit analysis).
- Requests with no token, an expired token, or the wrong scope are rejected by API Gateway before any application code runs.
- The database and bucket are private, and a user cannot upload to an arbitrary key (upload URLs are presigned for one server-chosen key).
- Secrets are absent from build artefacts and from the repository.
- Alarms exist for the dead-letter queue, worker errors and sustained database activity.
- Pause and resume work, and a paused backend is not silently redeployed.
- No NAT gateway, Fargate, ALB, Redis, separate vector database or provisioned concurrency exists.
