# Job Hunter: design

These briefs record how each part of Job Hunter is designed and why. For what runs on AWS, see [architecture/aws-overview.md](../architecture/aws-overview.md) and the [deployment guide](../deployment/README.md); for running it locally, the [project README](../../README.md).

The design started from the group's preliminary report (Sections 1.2–1.3, 2 and 4). It keeps the report's user journey and cloud concepts, and replaces the proposed always-on compute with a serverless design that costs almost nothing when idle.

## Briefs

| Brief | Covers |
|---|---|
| [CONTRACTS.md](CONTRACTS.md) | Shared API, data and ownership contracts used by every component |
| [01 Infrastructure and deployment](01-INFRASTRUCTURE.md) | AWS resources, networking, IAM, Terraform, the Deploy staging workflow |
| [02 Backend, database and tasks](02-BACKEND-AND-DATA.md) | API, schema, authentication boundary, row-level security, background work, allowance |
| [03 Profiles and resumes](03-PROFILES-AND-RESUMES.md) | Upload, extraction, review and confirmation |
| [04 Job discovery and processing](04-JOB-INGESTION.md) | Source adapters, Singapore filtering, deduplication, the job pull |
| [05 Recommendations](05-RECOMMENDATIONS.md) | All jobs (keyword ranking) and For you (embeddings) |
| [06 Fit analysis and application documents](06-APPLICATION-PREPARATION.md) | Fit analysis, tailoring, cover letters, export |
| [07 Frontend and user journey](07-FRONTEND.md) | React screens, routes, sign-in, polling |
| [08 Integration and evaluation](08-INTEGRATION-AND-EVALUATION.md) | Tests, acceptance checks and the system evaluation |
| [09 Resume editor](09-RESUME-EDITOR.md) | Resume Studio, templates, preview and PDF export |
| [10 Profile bank](10-PROFILE-BANK.md) | Structured profile items, wordings, skills, snapshots, resume build from the bank |
| [11 Embedding worker](11-EMBEDDING-WORKER.md) | S3 flag, SQS and a dedicated Lambda for vectors |
| [12 Fit analysis](12-FIT-ANALYSIS.md) | Grounded requirement checks, coverage computed in code, the shared LLM worker |
| [13 Pricing and plans](13-PRICING-AND-PLANS.md) | Free and premium plans, AI and platform cost model (premium is a demo plan for now) |
| [14 Cover letters](14-COVER-LETTERS.md) | AI and manual cover letters as documents |

## Product commitments

| Preliminary report commitment | How the prototype meets it |
|---|---|
| Shared pool of jobs from several sources | Four live sources (MyCareersFuture, Adzuna, Greenhouse and Lever boards), Singapore only, pulled twice a day |
| Normalise, deduplicate, process each job once | One canonical row per job across sources; role family and seniority classified at ingestion; one vector per job |
| Resume, experience and preferences | Private upload, structured profile bank, explicit confirmation, preferences |
| Keyword and semantic recommendations | All jobs (TF-IDF, a keyword-weighting score that favours distinctive words, plus skill and role) and For you (embeddings fused with keyword ranking); no model call per job viewed |
| Swipe-based review and shortlist | Save and Pass buttons with keyboard access |
| AI fit and gap analysis | Evidence-linked judgement per requirement and a coverage percentage computed in code; never a probability of being hired |
| Tailored resumes and cover letters, editable | Resume editor with templates, preview and PDF export; AI rewrite and AI cover letters that may not add facts |
| Application tracking | Status, notes, dates and the exact attached documents; the user applies on the employer's site |
| Freemium, five AI-assisted jobs a month | Per-Singapore-month allowance (5 free, 50 premium); premium is a demo plan for now, and a payment gateway is future work |
| Cloud deployment and evaluation | Deployed on AWS; system evaluation in [eval/](../../eval/README.md) |

Out of scope: form prefilling, automatic applications, recruiter outreach, browser extensions, custom model training and salary prediction.

## Key decisions

| Decision | Why | Instead of |
|---|---|---|
| API Gateway HTTP API + one FastAPI Lambda | Usage is bursty and requests are short; no server runs while idle, and FastAPI keeps one routing layer for local and cloud | Fargate behind an ALB, which costs money around the clock |
| Aurora PostgreSQL Serverless v2 (0–1 ACU, auto-pause) with pgvector | Profiles, ownership, tracking, allowance and vectors fit one relational database, and it pauses when nobody uses it | Provisioned RDS (fixed cost); DynamoDB plus a separate vector store |
| Row-level security on per-user tables | Tenant isolation is enforced by the database even if a query forgets a filter | Relying only on application checks |
| No NAT gateway | A NAT gateway would be the largest fixed cost. Functions that need the internet run outside the VPC; functions that need the database run inside | One NAT gateway for all functions |
| Background work starts with a small file in S3 | The S3 gateway endpoint is free, and an S3 event (or SQS) wakes the worker | Interface endpoints or a NAT gateway for SQS and Lambda calls from inside the VPC |
| Job pull split into Discovery (outside the VPC) and Import (inside) | One function can reach either the job feeds or the database, never both | A single crawler with internet and database access |
| Shared LLM worker outside the VPC, calling SoCLaaS | Amazon Bedrock isn't available on the course AWS account; one worker serves every AI task and has no database access, and the API checks every answer before saving it | One Lambda per AI feature; Bedrock |
| Slow AI work is asynchronous and polled | The API Lambda stops at 29 s; fit analysis can take longer, so it returns at once and the web app polls. Short tasks (rewrite, cover letter) wait up to 25 s | WebSockets or a general task queue |
| Embedding model baked into the worker image | The model is small, so the embed Lambda needs no network | Calling a hosted embedding API |
| Cognito, invite-only | Managed sign-in and JWT checks at the gateway; no password handling in the app | Custom authentication |
| Amplify Hosting for the React build | HTTPS hosting and deploys without managing S3 and CloudFront by hand | S3 + CloudFront |
| Terraform, applied by hand; releases by the manual Deploy staging workflow over OIDC | One reviewed infrastructure tool, no AWS keys in GitHub, and nothing deploys by accident on merge | CDK; automatic deploy on merge |

Not used, because nothing measured needed them: Step Functions, Redis, OpenSearch, Kubernetes, RDS Proxy.

## Technology

- **Frontend:** React, TypeScript and Vite, served by Amplify Hosting.
- **Backend:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, psycopg, Alembic; Mangum adapts FastAPI to Lambda. The API, migration, import, discovery and LLM worker functions share one container image.
- **Database:** PostgreSQL 16 with pgvector (Aurora Serverless v2 in AWS, `pgvector/pgvector:pg16` locally). 17 Alembic migrations.
- **Embeddings:** `jinaai/jina-embeddings-v2-small-en`, 512 dimensions, the same model and text format for jobs and profiles.
- **Language model:** the NUS SoCLaaS gateway, `ornith1.5:35b` since 8 November 2026.
- **Infrastructure:** Terraform in `infra/aws` (state bucket from `infra/state`), region `ap-southeast-1`.
- **Rendering:** PDFs generated on the server from structured data with ReportLab and bundled fonts.

## Local and cloud share the code

The same domain logic, migrations, API schemas and tests run in Docker Compose and on AWS. Only adapters and entry points differ: local file storage and a local embedder service in Compose; S3, the embed Lambda and the LLM worker in AWS. A local test pass does not prove AWS permissions, networking or event delivery; those are covered by the Terraform tests and the acceptance checks in [eval/](../../eval/README.md).

## Testing

Each component has unit tests (pytest for Python, Vitest and React Testing Library for the frontend), PostgreSQL tests for row-level security and migrations, Terraform tests for the infrastructure, and acceptance and load tests against staging. Current counts are in the [README](../../README.md#tests).
