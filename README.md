# Job Hunter

Job Hunter helps job seekers in Singapore discover openings, shortlist them against their profile, prepare a tailored resume and track applications. This repository holds the working local proof of concept (React + FastAPI + PostgreSQL in Docker) and the plan for deploying it to AWS (API Gateway + Lambda, RDS, S3/CloudFront, Cognito).

> **Status:** the local application runs end to end. **AWS deployment has not been built yet.** See [Deploying to AWS](#deploying-to-aws).

## Features (local)

- Singapore job discovery from public employer feeds (Greenhouse, Lever), with search, save and pass
- Profiles and preferences, with explainable keyword/skill/role ranking
- Resume Studio: structured editor, autosave, undo/redo, two templates, server-rendered PDF export
- Application tracker with an attached reviewed resume PDF and cover letter

AI generation is not connected yet. Semantic ranking is available as the "For you" list on the Discover page (see below). The full list and its gaps are in [docs/status/FEATURES.md](docs/status/FEATURES.md).

A standalone embedder service in `services/embedder/` starts with the stack (`make up`). The backend embeds the confirmed
profile after "Update my matches" and after saving preferences (best effort: a failed embed never fails the save), and
`GET /v1/recommendations/for-you` ranks jobs semantically, falling back to the keyword ranker (which stays the default
`/v1/recommendations`) when there is no profile vector. Job vectors are filled by `make backfill` until ingestion calls
`embed_job(s)`. A job's role family and seniority are set at ingestion (`jobs.category`, `jobs.seniority`); the `0013`
migration adds seniority columns and retires the old match-features table. After migrating existing jobs or changing the
keyword tables, run `make reclassify-jobs` and inspect the classification report (`python -m job_hunter.embedding.backfill
--classification-report`). Backfill makes vectors but does not classify jobs. Switches: `FOR_YOU_ENABLED`, `EMBED_ON_SAVE`
(both default on in compose). See
[embedder status](docs/status/11-embedder-service.md), [backend client status](docs/status/12-embedding-client.md) and
[embedding preparation](docs/status/13-embedding-preparation.md).

Ingestion can call `job_hunter.job_classification.classify_job(title, stated_seniority=None)` before saving a job; it returns the six category/seniority columns. Job preferences keep free-text target roles. The seniority dropdown loads canonical keys and labels from `GET /v1/preferences/seniority-options`; `PUT /v1/preferences` saves a canonical key (`intern`, `entry`, `mid`, `senior`, `lead`). If the options endpoint is unavailable, only the seniority selector is disabled and can be retried.

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
  src/job_hunter/    api/, adapters/, domain/, ingestion/, preparation/, recommendations.py
infra/local/       Local PostgreSQL role setup (AWS infrastructure goes in infra/aws, not yet created)
scripts/           HTTP smoke test and demo-workspace reset
docs/              Design, deployment plan and status (see docs/README.md)
compose.yaml       Local stack: PostgreSQL/pgvector, API, web
Makefile           Shortcuts for common tasks (run `make`)
```

## Running the checks

```sh
make test        # frontend tests + build, backend tests, HTTP smoke (stack must be running)
```

Or run them separately with `make test-web`, `make test-backend` and `make smoke`.

GitHub Actions runs the same checks on every push and pull request ([.github/workflows/checks.yml](.github/workflows/checks.yml)).

## Deploying to AWS

No AWS infrastructure code exists yet. The application was built so its business logic, schema and API can be reused behind Lambda handlers. Start here:

1. [Deployment start page](docs/deployment/README.md): the target architecture and a suggested order of work
2. [Cloud deployment handoff](docs/deployment/CLOUD-DEPLOYMENT-HANDOFF.md): what exists locally, the AWS target for each component, and the remaining work
3. [Lambda notes](docs/deployment/LAMBDA-NOTES.md): suggested functions, entry point, packaging and code changes for Lambda
4. [Local-to-AWS portability rules](docs/deployment/LOCAL-TO-AWS.md) and [delivery scope](docs/deployment/DELIVERY-SCOPE.md)

Passing local tests does not verify AWS permissions, event delivery or deployment.

## Contributing

The team is split into six areas: see [docs/WORK-SPLIT.md](docs/WORK-SPLIT.md).


See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and pull-request workflow and the rules on private data.

## AI assistance

AI coding assistants helped with implementation and tests. The team reviews generated code and records actual verification. Scaffolding and mocked tests are not claims of production readiness or AI quality.
