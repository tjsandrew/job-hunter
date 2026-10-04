# Job Hunter

Local-first Job Hunter POC: live job discovery, profile-based browsing, application tracking and a resume editor. The eventual cloud design uses AWS Lambda; cloud-native setup is deferred while the local application is built.

## Current status

Implementation in progress. See [handoffs](docs/handoffs) for verified features and test results. Development identity switching is for localhost only, not production authentication. AI features must be labelled unavailable or mocked until a real provider is configured.

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
