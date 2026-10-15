# Local development

Start the stack first with `make up` (see the [README](../README.md)). Most commands below also have a `make` shortcut; run `make` to list them.

## Local stack

The stack runs PostgreSQL/pgvector, a migration and seed step, the API (as a non-superuser database role with row-level security) and the frontend. The database and exported documents use named Docker volumes. API and frontend ports bind to localhost only, and the database has no host port.

Development identity switching (Alice/Casey) works only on localhost. It is not authentication.

## Singapore job data

The collection target is about 1,000 jobs explicitly located in Singapore, with 300–500 as an intermediate milestone. The first bounded import contains **70 source listings** across four employers and two ATS providers, so it is not representative of the Singapore market. Overseas jobs, description-only Singapore mentions and worldwide-remote roles do not count. Synthetic seed jobs are labelled separately. See the [ingestion notes](status/04-ingestion.md) for counts and source limits.

Live discovery is a manual, one-shot command. Do not run it on every app launch:

```sh
docker compose exec api python -m job_hunter.import_jobs --greenhouse stripe --greenhouse cloudflare --greenhouse coinbase --lever lalamove --location Singapore
```

The importer saves a normalized snapshot in the document volume. Replay it without contacting job sources:

```sh
docker compose exec api python -m job_hunter.import_jobs --snapshot-in /data/job-import-snapshots/latest.json --location Singapore
```

JustPostedJobs returned HTTP 429 during a limited review, so collection from that source is paused. Scheduled discovery, source credentials, expiry reconciliation and broader coverage are future work.

## Resetting the demo workspace

This resets Alice's profile and demo application and archives QA resumes. It backs up current records in the document volume first.

```sh
docker compose run --rm --no-deps -v "$PWD/backend/src:/app/src:ro" -v "$PWD/scripts/setup_demo_workspace.py:/app/setup_demo_workspace.py:ro" -e PYTHONPATH=/app/src api python /app/setup_demo_workspace.py
```

Run database integration tests against a disposable database, not the demo workspace. Test fixtures otherwise clutter the resume library. The smoke test also creates synthetic documents and uploads in the local database.

## Data and backups

Only synthetic fixtures belong in Git. Real resumes, uploads, exported documents and database volumes stay out of the repository. Git backs up source history only; back up data volumes separately if you need them.

## Importing resumes into the profile

On the Profile page, **Import** (on an uploaded PDF or a Resume Studio resume), **Import from file** (`resume.json`) or **Paste text** opens a review screen. Nothing is saved until you choose **Apply to profile**; merges only add facts and never overwrite.

PDFs and pasted text are parsed by local heuristics by default. To try a local model instead, run [Ollama](https://ollama.com) on your Mac and start the stack with:

```sh
MODEL_BACKEND=ollama OLLAMA_MODEL=llama3.2 make up
```

If the model is unavailable or returns invalid output, the import falls back to the heuristics and says so. `bedrock` is a placeholder until the AWS milestone.
