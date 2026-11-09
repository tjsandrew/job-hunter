# Job Hunter

Job Hunter helps job seekers in Singapore find openings that fit them and apply with less effort. Instead of checking several job boards and rewriting a resume for every posting, a user builds one profile. Job Hunter ranks Singapore jobs from several sources against that profile, shows how well each job fits, helps prepare a tailored resume and cover letter, and tracks every application in one place.

Built for NUS CS5224 Cloud Computing (Group 15). It runs serverless on AWS in Singapore (`ap-southeast-1`).

## Live prototype

[main.d3u7qeowlfzmzj.amplifyapp.com](https://main.d3u7qeowlfzmzj.amplifyapp.com)

Sign-up is invite-only. Grader accounts are listed in the project report.

## Features

- **Singapore job discovery:** jobs from MyCareersFuture, Adzuna, and employer job boards hosted on Greenhouse and Lever, pulled twice a day, with duplicates across sources shown once. Search, save and pass; filter by posting date and hide expired listings.
- **Profile from a resume:** upload a PDF or Word (.docx) resume, review what was extracted, and apply it to a structured profile (or enter it by hand).
- **Two ranked lists:** *All jobs* ranks by keyword, skill and role matches and shows why each job matched. *For you* also matches by meaning: the profile and each job are turned into vectors, and the closest jobs rank higher.
- **Job fit analysis:** a language model extracts the posting's requirements and judges each one against the profile with cited evidence. The app re-checks every answer and works out, in code, what share of the requirements the profile covers.
- **Resume Studio:** structured editor with autosave, undo and redo, two templates, build from the profile, and PDF export generated on the server.
- **Resume tailoring:** a free rule-based pass that moves the bullets matching the job to the top (always available), and an optional AI rewrite that may not add new numbers or names.
- **Cover letters:** an AI-written draft from the profile and the job, an editor with checks, and PDF export.
- **Documents and tracker:** resumes, uploads and cover letters in one library; an application tracker with the exact reviewed resume PDF and cover letter attached.
- **Plans:** a free and a premium plan with a monthly AI allowance (5 or 50 AI-assisted jobs per Singapore calendar month). Fit analysis, AI tailoring and an AI cover letter for the same job share one slot. Premium is a demo plan for now: an operator switches an account to it, and taking payments (for example through a payment gateway) is future work.

## Architecture

The React frontend is served by **Amplify Hosting**, and users sign in with **Cognito** (invite-only). Requests go through an **API Gateway** HTTP API with a JWT authorizer to the FastAPI backend, which runs as a container-image **Lambda** inside a private VPC with no internet access. Data lives in **Aurora PostgreSQL Serverless v2** (scales to zero, pgvector for embeddings, row-level security for tenant isolation) and documents in a private **S3** bucket. Background work starts with a small file in S3. An **SQS**-triggered embedding Lambda turns profiles and jobs into vectors. A shared **LLM worker** (large language model) Lambda outside the VPC calls the school's SoCLaaS model gateway (`ornith1.5:35b`) for fit analysis, AI tailoring and cover letters. An **EventBridge** schedule starts a job pull at 06:00 and 20:00 Singapore time: a Discovery Lambda outside the VPC reads the job feeds, and an Import Lambda inside the VPC loads them into Aurora. There is no NAT gateway, load balancer or always-on server. The AI features use SoCLaaS because Amazon Bedrock isn't available on the course AWS account, so no language model is hosted on AWS.

Diagram, request flows and design reasons: **[docs/architecture/aws-overview.md](docs/architecture/aws-overview.md)** ([styled HTML](docs/architecture/aws-overview.html)).

## Code by function

| Area | What it does | Key paths |
|---|---|---|
| Auth and tenant isolation | In AWS the user comes only from the Cognito token claims that API Gateway verified. Every database transaction sets `app.user_id`, and PostgreSQL row-level security limits every user-owned table to that user's rows; the shared job tables are readable by all. | [`adapters/auth.py`](backend/src/job_hunter/adapters/auth.py), [`adapters/database.py`](backend/src/job_hunter/adapters/database.py), [`migrations/versions/`](backend/migrations/versions) |
| Profile and resume import | PDF or Word upload, extraction into a review screen, then a structured profile bank (items, points, skills) that the user confirms. | [`profile_bank/`](backend/src/job_hunter/profile_bank), [`api/profile_bank.py`](backend/src/job_hunter/api/profile_bank.py), [`apps/web/src/profile/`](apps/web/src/profile) |
| Job ingestion and dedup | Source adapters for the four sources used in staging (Singapore only; a SmartRecruiters adapter also exists), role and seniority classification, and cross-source duplicate linking by listing link or by matching employer, title, place and near-identical description. | [`ingestion/discovery.py`](backend/src/job_hunter/ingestion/discovery.py), [`ingestion/dedup.py`](backend/src/job_hunter/ingestion/dedup.py), [`job_classification.py`](backend/src/job_hunter/job_classification.py), [`discovery_worker.py`](backend/src/job_hunter/discovery_worker.py), [`import_worker.py`](backend/src/job_hunter/import_worker.py) |
| Ranking | *All jobs* (`GET /v1/recommendations`) is a TF-IDF, skill and role ranker. *For you* (`GET /v1/recommendations/for-you`) ranks by embedding similarity (`jinaai/jina-embeddings-v2-small-en`, 512 dimensions), fused with the keyword ranking, and falls back to it when there is no profile vector. | [`recommendations.py`](backend/src/job_hunter/recommendations.py), [`embedding/`](backend/src/job_hunter/embedding), [`services/embedder/`](services/embedder), [`embed_worker.py`](backend/src/job_hunter/embed_worker.py) |
| AI features | Fit analysis, AI tailoring and cover letters run as tasks on one LLM client: inline locally, through S3 and the LLM worker in AWS. Model answers are checked in code before they are saved. The allowance module enforces the monthly limit. | [`preparation/fit/`](backend/src/job_hunter/preparation/fit), [`api/fit_analysis.py`](backend/src/job_hunter/api/fit_analysis.py), [`preparation/ai_tailoring.py`](backend/src/job_hunter/preparation/ai_tailoring.py), [`api/cover_letters.py`](backend/src/job_hunter/api/cover_letters.py), [`llm/`](backend/src/job_hunter/llm), [`llm_worker.py`](backend/src/job_hunter/llm_worker.py), [`preparation/allowance.py`](backend/src/job_hunter/preparation/allowance.py) |
| Documents and tracker | Resumes and cover letters are documents with autosave and revision checks. A reviewed export is an immutable PDF, so an application keeps the exact version attached. | [`api/main.py`](backend/src/job_hunter/api/main.py), [`preparation/rendering.py`](backend/src/job_hunter/preparation/rendering.py), [`apps/web/src/studio/`](apps/web/src/studio), [`apps/web/src/letters/`](apps/web/src/letters) |
| Frontend | React + TypeScript + Vite. Every page, list and document has its own address, so refresh, Back and shared links work. | [`apps/web/src/`](apps/web/src), [`routes.ts`](apps/web/src/routes.ts) |
| Infrastructure | Terraform for the whole staging stack (table below). The remote state bucket is bootstrapped separately. | [`infra/aws/`](infra/aws), [`infra/state/`](infra/state) |
| CI/CD | GitHub Actions for checks, Terraform validation, release, job pulls and pause/resume. | [`.github/workflows/`](.github/workflows), [`scripts/deploy_aws.py`](scripts/deploy_aws.py) |
| Evaluation | Load tests, AI task timing, job-pull pipeline timing, dedup accuracy, acceptance checks and a cost model, with raw results. | [`eval/`](eval) ([README](eval/README.md)) |

### Terraform files

| File | AWS resources |
|---|---|
| [`infra/aws/main.tf`](infra/aws/main.tf) | Amplify app and branch; Cognito user pool, app client and domain; ECR repositories; GitHub OIDC provider and release IAM role; the backend module |
| [`infra/aws/backend/main.tf`](infra/aws/backend/main.tf) | VPC, private subnets and S3 gateway endpoint; Aurora Serverless v2 cluster; documents bucket; API and migration Lambdas; API Gateway HTTP API with JWT authorizer |
| [`infra/aws/backend/embedder.tf`](infra/aws/backend/embedder.tf) | SQS queue and dead-letter queue, bucket notification, embedding Lambda, alarms |
| [`infra/aws/backend/llm_worker.tf`](infra/aws/backend/llm_worker.tf) | LLM worker Lambda, S3 invoke permission, alarm |
| [`infra/aws/backend/discovery.tf`](infra/aws/backend/discovery.tf) | Discovery and Import Lambdas, EventBridge schedule, error alarm |
| [`infra/aws/backend/activity_alarm.tf`](infra/aws/backend/activity_alarm.tf) | Aurora activity alarm and SNS topic |
| [`infra/aws/budget.tf`](infra/aws/budget.tf), [`permissions.tf`](infra/aws/permissions.tf) | Budget alert; IAM policies |

## Run locally

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with Compose) and Git.

```sh
git clone https://github.com/tjsandrew/job-hunter.git
cd job-hunter
make up
```

- App: http://localhost:5173
- API docs: http://localhost:8000/docs

The first start runs the database migrations (17) and seeds two fictional development users, Alice and Casey; switch between them in the app header. Local mode needs no AWS account. The AI features need a model configured in a git-ignored `.env` (see [`.env.example`](.env.example)); everything else works without one.

Run `make` to list every command (`make logs`, `make down`, `make import-jobs`, `make reset-demo`, …). `make reset` **permanently deletes** the local database and documents. More: [docs/LOCAL-DEVELOPMENT.md](docs/LOCAL-DEVELOPMENT.md).

## Tests

```sh
make test        # frontend tests + build, backend tests, HTTP smoke test (stack must be running)
```

Or run `make test-web`, `make test-backend`, `make smoke` and `make test-embedder` separately.

| Suite | Location | Tests defined |
|---|---|---|
| Backend (pytest) | `backend/tests` | 705 |
| Frontend (Vitest) | `apps/web/src` | 342 |
| Release and control scripts | `scripts/tests` | 51 |
| Embedder service | `services/embedder/tests` | 22 |
| Terraform | `infra/**/tests` | 5 files, 21 `run` blocks |

Counts are test definitions; parametrised tests run more cases (for example, the frontend's 342 definitions run as 371 tests). GitHub Actions runs the affected suites on every push and pull request to `main` (**Local POC checks**, whose *Checks passed* job is the overall result) and **Terraform validation** runs the Terraform tests.

## Deploy

Merging to `main` does not deploy. A release is started by hand: **Actions → Deploy staging → Run workflow** on `main`. It requires the commit's *Checks passed* result and pushes images to ECR, pinned by digest. It then runs migrations, updates each Lambda and the Amplify site, and restores the previous API image if the health check fails. GitHub signs in to AWS through **OIDC**, so no AWS keys are stored in the repository.

Terraform changes are applied by hand by an operator with AWS access; CI only validates them. Other workflows: **Pull jobs** (an extra job pull on demand) and **Pause or resume staging backend** (sets the API, embedding and Discovery Lambdas to zero concurrency so nothing wakes Aurora).

Full guide: [docs/deployment/README.md](docs/deployment/README.md).

## Documentation

| Where | What |
|---|---|
| [docs/architecture/](docs/architecture/aws-overview.md) | What runs where on AWS |
| [docs/deployment/](docs/deployment/README.md) | Deployment guide, release, cost, job pull and embedding worker runbooks |
| [docs/design/](docs/design/README.md) | Design briefs 01–14 and the reasons behind each decision |
| [docs/status/](docs/status/FEATURES.md) | Feature list against the proposal, and what is still open |
| [eval/](eval/README.md) | System evaluation scripts and results |

The full index is [docs/README.md](docs/README.md).

## Team and acknowledgements

NUS CS5224 Cloud Computing, Group 15.

We used AI tools, including Claude Code, ChatGPT and Codex, to help write code, tests, infrastructure configuration and documentation.
