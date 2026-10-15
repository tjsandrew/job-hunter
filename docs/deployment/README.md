# Deploying to AWS: start here

The application runs locally. Nothing is deployed to AWS yet, and there is no infrastructure code. This page is the entry point for the team doing the deployment.

## Target

| Local | AWS |
|---|---|
| React dev server (`apps/web`) | `npm run build` output on private S3 + CloudFront |
| FastAPI via Uvicorn (`backend/`) | API Gateway HTTP API → Lambda (ASGI adapter around `job_hunter.api.main:app`) |
| PostgreSQL 16 + pgvector in Docker | RDS PostgreSQL + pgvector; same Alembic migrations |
| Document volume (`/data`) | Private S3 bucket |
| Alice/Casey development identities | Cognito + JWT authorizer, mapped to internal users |
| Manual `import_jobs` command | EventBridge → bounded discovery Lambda |

## Suggested order

1. **Read** the [work split](../WORK-SPLIT.md) and the [Lambda notes](LAMBDA-NOTES.md).
2. **Foundation:** create an `infra/aws` CDK app (TypeScript), with the VPC, RDS and private buckets in a data stack kept separate from the application stack. Add `cdk synth` and assertion tests to CI. See [01-INFRASTRUCTURE.md](../design/01-INFRASTRUCTURE.md).
3. **Frontend:** deploy the static build to S3/CloudFront. This can ship first because it needs no backend changes beyond the API URL.
4. **API:** add a Lambda entry point, then run migrations once from a release job. Hit `/v1/health` through API Gateway.
5. **Identity:** replace `X-Dev-User` handling in `api/main.py` and `adapters/database.py` with verified Cognito claims. Keep the per-transaction RLS user setting.
6. **Documents:** move uploads and exported PDFs from the local volume to S3 behind a storage interface.
7. **Background work:** add discovery, queues and AI workers.

The [cloud deployment handoff](CLOUD-DEPLOYMENT-HANDOFF.md) has the per-component detail and a checklist. [LOCAL-TO-AWS.md](LOCAL-TO-AWS.md) lists the portability rules: business logic stays shared, and AWS-specific code lives in thin adapters.

## Configuration already in place

- `APP_ENV` and `AUTH_MODE` exist in `backend/src/job_hunter/config.py`. The app refuses to start with local identities outside `APP_ENV=local|test`, so an AWS build must provide real authentication.
- The frontend reads its API base URL from `VITE_API_BASE_URL`.
- Fonts used for PDFs ship inside the backend package (`job_hunter/preparation/fonts`).
