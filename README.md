# Job Hunter

Job Hunter helps job seekers in Singapore discover openings, shortlist them against their profile, prepare a tailored resume and track applications. This repository holds the working local proof of concept (React + FastAPI + PostgreSQL in Docker) and the plan for deploying it to AWS (API Gateway + Lambda, RDS, S3/CloudFront, Cognito).

> **Status:** the local application runs end to end. **AWS deployment has not been built yet.** See [Deploying to AWS](#deploying-to-aws).

## Features (local)

- Singapore job discovery from public employer feeds (Greenhouse, Lever), with search, save and pass
- Profiles and preferences, with explainable keyword/skill/role ranking
- Resume Studio: structured editor, autosave, undo/redo, two templates, server-rendered PDF export
- Application tracker with an attached reviewed resume PDF and cover letter

AI generation and semantic ranking are not connected yet. The full list and its gaps are in [docs/status/FEATURES.md](docs/status/FEATURES.md).

## Quick start

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with Compose) and Git.

```sh
git clone https://github.com/tjsandrew/job-hunter.git
cd job-hunter
docker compose up --build -d
```

- App: http://localhost:5173
- API docs: http://localhost:8000/docs

The first start runs database migrations and seeds two fictional development users (Alice and Bob). Switch between them in the app header. Alice has a populated demo profile, resume and application.

```sh
docker compose logs --tail=100 api web   # view logs
docker compose stop                      # stop, keeping data
```

`docker compose down --volumes` **permanently deletes** the local database and documents.

Importing live jobs, resetting the demo workspace and other tasks: [docs/LOCAL-DEVELOPMENT.md](docs/LOCAL-DEVELOPMENT.md).

## Repository layout

```
apps/web/          React + TypeScript + Vite frontend
backend/           FastAPI API, domain logic, Alembic migrations, tests
  src/job_hunter/    api/, adapters/, domain/, ingestion/, preparation/, recommendations.py
infra/local/       Local PostgreSQL role setup (not AWS infrastructure)
scripts/           HTTP smoke test and demo-workspace reset
docs/              Design, deployment plan and status (see docs/README.md)
compose.yaml       Local stack: PostgreSQL/pgvector, API, web
```

## Running the checks

```sh
cd apps/web && npm ci && npm test && npm run build
```

With the stack running, from the repository root:

```sh
python3 scripts/smoke.py
docker compose run --rm --no-deps -e RUN_DB_INTEGRATION=1 -v "$PWD/backend/tests:/app/tests:ro" api sh -c 'pip install -c requirements.lock ".[test]" && pytest /app/tests -q'
```

GitHub Actions runs the same checks on every push and pull request ([.github/workflows/checks.yml](.github/workflows/checks.yml)).

## Deploying to AWS

No AWS infrastructure code exists yet. The application was built so its business logic, schema and API can be reused behind Lambda handlers. Start here:

1. [Cloud deployment handoff](docs/deployment/CLOUD-DEPLOYMENT-HANDOFF.md): what exists locally, the AWS target for each component, and the remaining work
2. [Six-person work split](docs/deployment/SIX-PERSON-WORK-SPLIT.md): who owns what, with dependencies and acceptance checks
3. [Local-to-AWS portability rules](docs/deployment/LOCAL-TO-AWS.md) and [delivery scope](docs/deployment/DELIVERY-SCOPE.md)

Passing local tests does not verify AWS permissions, event delivery or deployment.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and pull-request workflow and the rules on private data.

## AI assistance

AI coding assistants helped with implementation and tests. The team reviews generated code and records actual verification. Scaffolding and mocked tests are not claims of production readiness or AI quality.
