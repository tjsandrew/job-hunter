# Lambda notes and suggestions

These are suggestions for whoever builds the Lambda side, not decisions. They follow the [design](../design/01-INFRASTRUCTURE.md) and [handoff](CLOUD-DEPLOYMENT-HANDOFF.md). Change them if measurements say otherwise.

## Functions

One backend package, several thin entry points:

| Function | Trigger | Starting memory / timeout | Notes |
|---|---|---|---|
| `api` | API Gateway HTTP API | 1024 MB / 15 s | Wraps the existing FastAPI app. PDF preview/export runs here. |
| `discovery` | EventBridge (every 6 h) | 512 MB / 240 s | Calls the same code as `python -m job_hunter.import_jobs`, in bounded batches |
| `job-worker` | SQS | 1024 MB / 120 s | Per-job processing (embeddings later) |
| `personal-worker` | SQS | 1024 MB / 120 s | AI fit analysis and tailoring, when built |
| `maintenance` | EventBridge (every 1 min) | 512 MB / 30 s | Retries, stale-task cleanup |
| `migrate` | Manual, from the release pipeline | 512 MB / 300 s | Runs `alembic upgrade head`. Never runs on cold start. |

Start with only `api` and `migrate`. The resume editor, profiles and tracker need nothing else. Add the others when their features exist.

## API entry point

[Mangum](https://mangum.fastapiexpert.com/) adapts the existing ASGI app with a few lines. A suggested `backend/src/job_hunter/api/lambda_handler.py`:

```python
from mangum import Mangum

from job_hunter.api.main import app

handler = Mangum(app, lifespan="off")
```

Checked locally (Mangum 0.22.0): an API Gateway HTTP API v2 event for `GET /v1/health` returns `200 {"status":"ok"}`. Add `mangum` to `pyproject.toml` and `requirements.lock`. Keep `uvicorn` for local Docker.

Alternative: [AWS Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) runs the current Uvicorn container unchanged as a Lambda image. It needs no code change, but the image is larger.

Handler tests can feed API Gateway event fixtures to `handler(event, None)` without AWS credentials.

## Packaging

- **Container image** (recommended): base it on `public.ecr.aws/lambda/python:3.12`, install with `pip install -c requirements.lock .`, and set the command to `job_hunter.api.lambda_handler.handler`. That avoids building psycopg, ReportLab and pypdf wheels for Amazon Linux on a Mac, and the bundled fonts in `job_hunter/preparation/fonts` are included automatically.
- Choose one architecture (arm64 is cheaper) and use it in both build and deploy.
- `migrate` can reuse the same image with a different command.

## Things in the current code to change for Lambda

| Current behaviour | Where | Lambda change |
|---|---|---|
| Connection pool `pool_size=3` per process | `adapters/database.py` | Use `pool_size=1, max_overflow=0` per Lambda environment. Total connections = reserved concurrency × 1 + migrations + operators, so keep within RDS limits. |
| Identity from the `X-Dev-User` header | `identity()` in `api/main.py`, `adapters/database.py` | Read the Cognito `sub` from the JWT authorizer claims (`event.requestContext.authorizer.jwt.claims`, available through Mangum as `request.scope["aws.event"]`). Map it to an internal user and keep setting `app.user_id` per transaction for RLS. |
| PDFs written to `PDF_STORAGE_DIR` and uploads to the `/data` volume | `api/main.py`, `config.py` | Only `/tmp` is writable, and it is not durable. Render to memory or `/tmp`, then store in S3 behind a small storage interface (local filesystem for Docker, S3 for AWS). |
| `DATABASE_URL` with a password in the environment | `config.py` | Load credentials from Secrets Manager at cold start. Keep separate runtime and migration roles. |
| CORS from `CORS_ORIGINS` | `api/main.py` | Set it to the CloudFront domain, or handle CORS in API Gateway only (not both). |
| Seeding on startup | `compose.yaml` command | Don't seed in AWS except in a dev environment, from `migrate`. |

`config.py` already refuses `AUTH_MODE=local` outside `APP_ENV=local|test`, so an AWS deployment fails fast until real authentication is wired in.

## Networking and cost

- The `api` function must be in the VPC to reach private RDS. It needs internet (NAT) only for outbound calls, such as job sources or Bedrock. The API alone does not need NAT, so `discovery` could run outside the VPC and hand off work through SQS to save the NAT cost.
- Add RDS Proxy only if connection counts become a problem. Re-test RLS with it, because it pins connections that use session settings.
- Reserved concurrency starting points: api 10, discovery 1, workers 2–3.

## Cold starts

The API imports FastAPI, SQLAlchemy, ReportLab and pypdf, so expect roughly 1–2 s cold starts. Measure before optimising. Options: lazy-import the PDF libraries inside the routes that use them, use arm64, and add provisioned concurrency only if a demo needs it.

## Frontend

Not a Lambda: `cd apps/web && VITE_API_BASE_URL=https://<api-domain>/v1 npm run build`, upload `dist/` to the private S3 bucket and serve it through CloudFront.
