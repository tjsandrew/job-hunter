# Job Hunter

Job Hunter helps job seekers in Singapore discover openings, shortlist them against their profile, check how well they fit, prepare a tailored resume and track applications. This repository holds the application (React + FastAPI + PostgreSQL), the local Docker stack, and the Terraform and GitHub Actions setup for the staging deployment on AWS.

> **Status:** the application runs end to end locally. A **staging deployment is live on AWS** (Amplify, Cognito, API Gateway + Lambda, Aurora Serverless v2, S3, an SQS-triggered embedding Lambda and a shared LLM worker Lambda for job fit and the AI resume rewrite), invite-only. It was built with a serverless design that differs from the original proposal, so read [Deploying to AWS](#deploying-to-aws) for what actually runs. Staging currently holds no job listings: discovery is a manual local command and no scheduled cloud discovery exists yet.

## Features

- Singapore job discovery from public employer feeds (Greenhouse, Lever), with search, save and pass. The Discover page has For you, All jobs, Saved and Passed tabs
- Profiles and preferences. The profile is built from an uploaded PDF or Word resume (reviewed by the user before it is applied) or entered by hand, kept as a structured profile bank, and confirmed explicitly
- Recommendations: an explainable keyword/skill/role ranker, and a semantic "For you" list built on an embedding model
- **Job fit analysis:** a language model extracts the posting's requirements, judges each one against the confirmed profile with cited evidence, and the app re-checks every answer and computes a coverage percentage in code, plus suggestions. See [design brief 12](docs/design/12-FIT-ANALYSIS.md)
- Resume Studio: structured editor, autosave, undo/redo, two templates, build from the profile bank, server-rendered PDF export
- Resume tailoring: a rule-based reorder (always available) and an optional AI rewrite
- Application tracker with an attached reviewed resume PDF and cover letter
- Every page, job list, opened listing and resume has its own address (`/discover/saved`, `/jobs/<id>`, `/resumes/<id>`, ...), so a refresh, the Back button and a pasted link land where you were; signing in returns you to the page you opened (`apps/web/src/routes.ts`)
- Sign-in with Amazon Cognito in the deployed app; free and premium plans with a monthly AI allowance (5 or 50 jobs per Singapore month, one use per job shared by fit analysis and AI tailoring)

Built, waiting for the next Terraform apply and deploy: the job pull (GitHub Actions "Pull jobs" loads 10 new public postings into staging) and cross-source duplicate detection (see [docs/deployment/JOB-PULL-ROLLOUT.md](docs/deployment/JOB-PULL-ROLLOUT.md)). Not built: AI cover-letter generation, swipe gestures (Save and Pass are buttons), a job schedule that is switched on by default, payments. The full list and its gaps are in [docs/status/FEATURES.md](docs/status/FEATURES.md) and [docs/status/PENDING.md](docs/status/PENDING.md).

Fit analysis and the AI resume rewrite use the school's SoCLaaS model gateway (`gemma4:26b`). Locally it runs inside the API process (`MODEL_BACKEND=hosted` plus `LLM_*` settings in a git-ignored `.env`, see `.env.example`). In AWS the API writes a request file to S3 and the shared LLM worker Lambda outside the VPC calls the model. Locally the fit button stays disabled until a model is configured; in AWS it is enabled whenever the S3 worker route is configured, even if the worker has no key yet.

A standalone embedder service in `services/embedder/` starts with the stack (`make up`). The backend embeds the confirmed
profile after "Update my matches" and after saving preferences (best effort: a failed embed never fails the save), and
`GET /v1/recommendations/for-you` ranks jobs semantically, falling back to the keyword ranker (which stays the default
`/v1/recommendations`) when there is no profile vector. Job vectors are filled by `make backfill` until ingestion calls
`embed_job(s)`. A job's role family and seniority are set at ingestion (`jobs.category`, `jobs.seniority`); the `0013`
migration adds seniority columns and retires the old match-features table. After migrating existing jobs or changing the
keyword tables, run `make reclassify-jobs` and inspect the classification report (`python -m job_hunter.embedding.backfill
--classification-report`). Backfill makes vectors but does not classify jobs. Switches: `FOR_YOU_ENABLED`, `FOR_YOU_FUSION`, `EMBED_ON_SAVE`
(both default on in compose). See
[embedder status](docs/status/11-embedder-service.md), [backend client status](docs/status/12-embedding-client.md) and
[embedding preparation](docs/status/13-embedding-preparation.md).

Ingestion can call `job_hunter.job_classification.classify_job(title, stated_seniority=None)` before saving a job; it returns the six category/seniority columns. Job preferences keep free-text target roles. The seniority dropdown loads canonical keys and labels from `GET /v1/preferences/seniority-options`; `PUT /v1/preferences` saves a canonical key (`intern`, `junior`, `mid`, `senior`, `lead`, `executive`; the old `entry` key and the old labels are accepted and converted). The match checks treat `lead` and `executive` as one step for now. If the options endpoint is unavailable, only the seniority selector is disabled and can be retried.

## Quick start

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with Compose) and Git.

```sh
git clone https://github.com/tjsandrew/job-hunter.git
cd job-hunter
make up          # or: docker compose up --build -d
```

- App: http://localhost:5173
- API docs: http://localhost:8000/docs

The first start runs database migrations and seeds two fictional development users (Alice and Casey). Switch between them in the app header. Alice has a populated demo profile, resume and application.

Run `make` to list every command (`make logs`, `make down`, `make test`, `make import-jobs`, `make reset-demo`, …). `make reset` **permanently deletes** the local database and documents. More detail: [docs/LOCAL-DEVELOPMENT.md](docs/LOCAL-DEVELOPMENT.md).

## Resume editor

The resume editor is the most complete part of the app and a good place to start building:

| Piece | Where |
|---|---|
| Editor UI (Resume Studio, preview, layout controls) | [apps/web/src/App.tsx](apps/web/src/App.tsx), [styles.css](apps/web/src/styles.css) |
| Pure editing helpers (sections, entries, bullets), with tests | [apps/web/src/editor.ts](apps/web/src/editor.ts), [editor.test.ts](apps/web/src/editor.test.ts) |
| API: `/v1/documents` CRUD, duplicate, review, `preview.pdf`, exports | [backend/src/job_hunter/api/main.py](backend/src/job_hunter/api/main.py) |
| PDF rendering (ReportLab, Latin Modern fonts, templates) | [backend/src/job_hunter/preparation/rendering.py](backend/src/job_hunter/preparation/rendering.py) |
| Design and behaviour spec | [docs/design/09-RESUME-EDITOR.md](docs/design/09-RESUME-EDITOR.md) |

Documents autosave with revision checks. A PDF is exported from a reviewed revision and stays immutable, so an application keeps the exact resume that was attached.

## Repository layout

```
apps/web/          React + TypeScript + Vite frontend
backend/           FastAPI API, domain logic, Alembic migrations, tests
  src/job_hunter/    api/, adapters/, domain/, ingestion/, embedding/, llm/, preparation/ (incl. fit/),
                     profile_bank/, recommendations.py, and the Lambda entry points
                     (api/lambda_handler.py, migrate_aws.py, embed_worker.py, llm_worker.py)
services/embedder/ Standalone embedding service and its Lambda packaging
infra/local/       Local PostgreSQL role setup
infra/aws/         Terraform for the staging deployment (infra/state bootstraps the remote state bucket)
scripts/           Smoke tests, demo-workspace reset, release and deployment scripts
.github/workflows/ Checks, Deploy staging, pause/resume of the backend, Terraform validation
docs/              Design, deployment and status (see docs/README.md)
compose.yaml       Local stack: PostgreSQL/pgvector, API, embedder, web
Makefile           Shortcuts for common tasks (run `make`)
```

## Running the checks

```sh
make test        # frontend tests + build, backend tests, HTTP smoke (stack must be running)
```

Or run them separately with `make test-web`, `make test-backend` and `make smoke`.

GitHub Actions runs the same checks on every push and pull request ([.github/workflows/checks.yml](.github/workflows/checks.yml)).

## Deploying to AWS

The staging stack is defined in Terraform (`infra/aws`) and released by GitHub Actions. **Merging to `main` does not deploy**: run **Actions → Deploy staging → Run workflow** on `main`. Terraform changes are applied by hand by an operator with AWS access; CI only validates them.

What runs in `ap-southeast-1`: Amplify Hosting (React build), Cognito (invite-only sign-in), API Gateway HTTP API with a JWT authorizer, the API as a container-image Lambda in a VPC, Aurora PostgreSQL Serverless v2 (0–1 ACU, auto-pause, row-level security), a private S3 documents bucket, an S3 → SQS → Lambda embedding worker, and the shared LLM worker Lambda (fit analysis, AI resume rewrite) outside the VPC. The job pull adds a Discovery Lambda outside the VPC and an Import Lambda inside it (an EventBridge schedule exists but is off). There is no NAT gateway, ALB, Fargate or Bedrock: the proposal's design was replaced by this serverless one. The architecture page is [docs/architecture/aws-overview.html](docs/architecture/aws-overview.html).

Start here:

1. [Deployment guide](docs/deployment/README.md): the deployed architecture, credentials, cost model, release and pause/resume workflows, Terraform state
2. [Fit analysis design](docs/design/12-FIT-ANALYSIS.md): includes the runbook for the LLM worker (section 11) and how to add a task (section 12)
3. [Embedding worker](docs/design/11-EMBEDDING-WORKER.md) and its [rollout notes](docs/deployment/EMBEDDING-WORKER-ROLLOUT.md)

The earlier proposals ([cloud handoff](docs/deployment/CLOUD-DEPLOYMENT-HANDOFF.md), [Lambda notes](docs/deployment/LAMBDA-NOTES.md), [portability rules](docs/deployment/LOCAL-TO-AWS.md), [delivery scope](docs/deployment/DELIVERY-SCOPE.md)) are kept as design history and do not describe the deployed resources.

Passing local tests does not verify AWS permissions, event delivery or deployment.

## Contributing

The team is split into six areas: see [docs/WORK-SPLIT.md](docs/WORK-SPLIT.md).


See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and pull-request workflow and the rules on private data.

## AI assistance

AI coding assistants helped with implementation and tests. The team reviews generated code and records actual verification. Scaffolding and mocked tests are not claims of production readiness or AI quality.
