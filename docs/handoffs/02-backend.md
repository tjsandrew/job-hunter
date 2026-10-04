# Backend handoff

## Delivered local API

The FastAPI application is in `backend/src/job_hunter/api/main.py`; SQLAlchemy models and the database/session boundary are in `domain/models.py` and `adapters/database.py`. PostgreSQL 16 with pgvector is the only supported database. Alembic migrations `0001`–`0008` create the local schema, vector extension, tenant RLS policies, immutable confirmed profile revisions, ingestion provenance/category columns and bounded upload extraction fields. The local API uses the non-owner `jobhunter_app` role. It sets `app.user_id` transaction-locally from the fixed Alice/Bob development identity map before accessing private rows. Seed and migration commands use the owner URL.

The `/v1` API implements health and current user, editable profile and explicit immutable confirmation, preferences, filtered/ranked and paginated recommendations, job detail/review, application tracking, resume document create/read/revision-checked edit/duplicate/review, and PDF preview/reviewed export/download. `GET /recommendations` accepts `limit` (1–100), `offset`, and `q`; the response has `items`, `total`, `next_offset`, `degraded_mode`, and `ranking_status`. Job cards include source board, original URL, posted/fetched timestamps and the title-derived category provenance.

Local PDF upload accepts `POST /v1/uploads` with `{filename,content_type,size_bytes}`, followed by raw PDF bytes sent to the returned upload URL. It captures one immutable copy and SHA-256, enforces 10 MiB and 20 pages, and exposes extracted text via `GET /v1/uploads/{id}` as a review candidate. Encrypted, corrupt and textless/scanned-like PDFs report safe status codes; OCR is not implemented. Extracted text is not silently converted into structured profile facts. The resume editor persists structured JSON, uses classic and modern typography, and exports selectable text with bundled ReportLab Vera font support for modern output.

The ingestion agent owns `backend/src/job_hunter/ingestion` and `import_jobs.py`; the ORM supports provider/board/external ID uniqueness and its deterministic title-only category is labelled `title_keyword_v1` with evidence. Its discovery/import paths are separate from normal API shared-job writes.

## Run and verify

From the project root, `docker compose up --build` starts PostgreSQL, applies migrations, seeds Alice/Bob and runs the API and web app. For the test suite against the running local DB:

```sh
docker compose run --rm --no-deps \
  -v "$PWD/backend/src:/app/src:ro" \
  -v "$PWD/backend/migrations:/app/migrations:ro" \
  -v "$PWD/backend/tests:/app/tests:ro" api \
  sh -c 'pip install pytest httpx -c requirements.lock && RUN_DB_INTEGRATION=1 pytest -q /app/tests'
```

Actual result on the shared Compose PostgreSQL database: **46 passed**. The suite includes end-to-end owned PDF upload, text extraction, immutable-byte and foreign-user checks; parser errors and limits; multi-page rendering in both templates with accented Latin names and bold markup; ingestion upsert behavior; API request validation, ownership, revision checks and pagination/search; plus direct runtime-role SQL checks proving private rows are hidden without a user context and when switching from Alice to Bob. A separately created empty `jobhunter_migration_test` database successfully applied migrations `0001`–`0008` and the synthetic seed. The local Python environment could not install packages because network access was blocked; verification therefore ran inside the Compose image. The test run emitted FastAPI `on_event` and Starlette/httpx deprecation warnings, no failures.

## Limits and follow-up

AI generation, semantic embeddings, usage reservations, task state/worker retry, profile fact extraction/confirmation UI, OCR, uploads deletion, Cognito, S3, Lambda/API Gateway and AWS RLS-role verification are not implemented. `/me` marks allowance accounting disabled and shows no usage value. The keyword ranker uses explicit location preferences as a hard filter, deterministic keyword/skill scoring and excludes reviewed jobs. PDF exports are created synchronously and stored on the local volume; automatic export deduplication and asynchronous task processing are deferred. The bundled font supports accented Latin text but not CJK glyphs. PDF rendering currently lives in the API module and can move to a preparation/rendering service when that component is expanded. The live job adapter was tested separately by its owner; this backend handoff does not claim AWS source access, Bedrock, Cognito or cloud deployment verification.
