# Job Hunter

Local-first Job Hunter POC: live job discovery, profile-based browsing, application tracking and a resume editor. The eventual cloud design uses AWS Lambda; cloud-native setup is deferred while the local application is built.

## Current status

The first local slice includes Singapore job discovery/import, keyword-based browsing, profiles and preferences, application tracking, and a manual resume editor with PDF preview/export. See [handoffs](docs/handoffs) for verified features, test results and remaining work. Development identity switching is for localhost only. AI generation and semantic ranking are unavailable until a real provider is configured.

## Local development

Prerequisites: Docker Desktop with Compose, and Git.

```sh
docker compose up --build -d
```

Frontend: http://localhost:5173. API documentation: http://localhost:8000/docs.

The stack uses PostgreSQL/pgvector, a migration/seed step and a non-superuser API database role. Database and exported documents use named volumes. API/frontend ports bind to localhost. The database is not exposed on a host port.

```sh
docker compose logs --tail=100 api web
docker compose stop
```

Normal shutdown preserves data. `docker compose down --volumes` permanently deletes the local database and document volumes; use only when deliberately resetting development data.

## Singapore job data

The collection target is about 1,000 jobs explicitly located in Singapore, with 300–500 as an intermediate milestone. The first bounded import contains **70 source listings** across four employers and two ATS providers; it is not representative of the entire Singapore market. Overseas jobs, description-only Singapore mentions and worldwide-remote eligibility do not count. Synthetic seed jobs are labelled separately. See the [ingestion handoff](docs/handoffs/04-ingestion.md) for actual imported counts and source limitations.

Live discovery is a manual, one-shot local command. Do not run it on every app launch:

```sh
docker compose exec api python -m job_hunter.import_jobs --greenhouse stripe --greenhouse cloudflare --greenhouse coinbase --lever lalamove --location Singapore
```

The importer saves a normalized snapshot in the local document volume. Reuse it without contacting job sources:

```sh
docker compose exec api python -m job_hunter.import_jobs --snapshot-in /data/job-import-snapshots/latest.json --location Singapore
```

JustPostedJobs returned HTTP 429 during a limited review; collection from that source is paused. Scheduled cloud discovery, source credentials, expiry reconciliation and broader source coverage remain subsequent work.

## Checks

```sh
cd apps/web
npm ci
npm test
npm run build
```

From the repository root with Compose running:

```sh
python3 scripts/smoke.py
docker compose run --rm --no-deps -e RUN_DB_INTEGRATION=1 -v "$PWD/backend/tests:/app/tests:ro" api sh -c 'pip install -c requirements.lock ".[test]" && pytest /app/tests -q'
```

The smoke test creates synthetic documents and uploads in the local database. GitHub Actions runs the checks against a disposable PostgreSQL database. Unit tests check small isolated behaviours; the PostgreSQL and HTTP checks exercise real persistence, isolation and document flows.

## Design and implementation scope

- [Design and component briefs](docs/poc-design/README.md)
- [Local now, cloud later](docs/poc-design/DELIVERY-SCOPE.md)
- [Local-to-AWS portability](docs/poc-design/LOCAL-TO-AWS.md)
- [Resume editor](docs/poc-design/09-RESUME-EDITOR.md)

Local business logic, schema and interfaces are intended to be shared with later Lambda handlers. Passing local tests does not verify AWS permissions, event delivery or deployment.

## Source control and private data

This is a private project repository. Original report/reference files, local secrets, uploaded resumes, generated private documents and database volumes are excluded from Git. Only synthetic fixtures should be committed. Git backs up source history; data volumes need separate backups.

## AI assistance

Codex agents assist with implementation and tests. The team must review generated code and document actual verification and learning for the course submission. No claim of production readiness or measured AI quality is implied by scaffolding or mocked tests.
