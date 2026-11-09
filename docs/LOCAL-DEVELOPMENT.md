# Local development

Start the stack first with `make up` (see the [README](../README.md)). Most commands below also have a `make` shortcut; run `make` to list them.

## Local stack

The stack runs PostgreSQL/pgvector, a migration and seed step, the API (as a non-superuser database role with row-level security) and the frontend. The database and exported documents use named Docker volumes. API and frontend ports bind to localhost only, and the database has no host port.

Development identity switching (Alice/Casey) works only on localhost. It is not authentication.

## Singapore job data

Only jobs explicitly located in Singapore are kept; overseas jobs, description-only Singapore mentions and worldwide-remote roles do not count. Synthetic seed jobs are labelled separately. In AWS, jobs are pulled twice a day by the Discovery and Import Lambdas ([job pull runbook](deployment/JOB-PULL-ROLLOUT.md)). Locally, imports are run by hand.

Local discovery is a manual, one-shot command (`make import-jobs` runs a default set). Do not run it on every app launch:

```sh
docker compose exec api python -m job_hunter.import_jobs --greenhouse stripe --greenhouse cloudflare --greenhouse coinbase --lever lalamove --location Singapore
```

The importer saves a normalised snapshot in the document volume. Replay it without contacting job sources:

```sh
docker compose exec api python -m job_hunter.import_jobs --snapshot-in /data/job-import-snapshots/latest.json --location Singapore
```

`make replay-jobs` replays the last snapshot. Adzuna needs `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`; in AWS they are GitHub secrets written into the Discovery Lambda by Deploy staging.

Compose does not pass Adzuna credentials to the API automatically. For a local import, pass them explicitly from your shell:

```sh
docker compose exec -e ADZUNA_APP_ID -e ADZUNA_APP_KEY api python -m job_hunter.import_jobs --adzuna "data engineer" --location Singapore
```

## Resetting the demo workspace

This resets Alice's profile and demo application and archives QA resumes. It backs up current records in the document volume first.

```sh
docker compose run --rm --no-deps -v "$PWD/backend/src:/app/src:ro" -v "$PWD/scripts/setup_demo_workspace.py:/app/setup_demo_workspace.py:ro" -e PYTHONPATH=/app/src api python /app/setup_demo_workspace.py
```

`make test-backend` uses the running Compose database. For a clean database, `make reset` permanently deletes local data before recreating the stack. Test fixtures otherwise clutter the resume library. The smoke test also creates synthetic documents and uploads in the local database.

## Data and backups

Only synthetic fixtures belong in Git. Real resumes, uploads, exported documents and database volumes stay out of the repository. Git backs up source history only; back up data volumes separately if you need them.

## Importing resumes into the profile

On the Profile page, **Import** (on an uploaded PDF or a Resume Studio resume), **Import from file** (PDF or Word) or **Paste text** opens a review screen. Nothing is saved until you choose **Apply to profile**; merges only add facts and never overwrite.

Use **Restore profile backup** for a `resume.json` backup.

PDFs, Word files and pasted text are parsed by local heuristics by default. To try a local model instead, run [Ollama](https://ollama.com) on your Mac and start the stack with:

```sh
MODEL_BACKEND=ollama OLLAMA_MODEL=llama3.2 make up
```

If the model is unavailable or returns invalid output, the import falls back to the heuristics and says so. `bedrock` is a stub, as Amazon Bedrock isn't available on the course AWS account.

## AI features locally

Fit analysis, the AI resume rewrite and AI cover letters use the school's SoCLaaS model gateway (`ornith1.5:35b` since 8 November 2026, when `gemma4:26b` was withdrawn). Locally the model call runs inside the API process: set `MODEL_BACKEND=hosted` plus the `LLM_*` settings in a git-ignored `.env` (see `.env.example`). Until a model is configured the AI buttons stay disabled.

In AWS the API writes a request file to S3 and the shared LLM worker Lambda makes the call instead; see [design brief 12](design/12-FIT-ANALYSIS.md).

## Embeddings and job classification

The standalone embedder in `services/embedder/` starts with the stack (`make up`; `make embedder-up` / `make embedder-down` to manage it alone). The backend embeds the confirmed profile after "Update my matches" and after saving preferences (best effort: a failed embed never fails the save). `GET /v1/recommendations/for-you` ranks jobs by vector similarity and falls back to the keyword ranker (`GET /v1/recommendations`) when there is no profile vector.

- Job vectors: in AWS the import writes an embed flag and the embedding worker fills them. Locally, run `make backfill` to embed open jobs and confirmed profiles.
- Switches (all default on in Compose): `FOR_YOU_ENABLED`, `FOR_YOU_FUSION` and `EMBED_ON_SAVE`.
- Classification: a job's role family and seniority are set at ingestion by `job_hunter.job_classification.classify_job(title, stated_seniority=None)`, stored in `jobs.category` and `jobs.seniority`. After changing the keyword tables, run `make reclassify-jobs` and inspect the report (`python -m job_hunter.embedding.backfill --classification-report`). Backfill makes vectors but does not classify jobs.
- Seniority preferences: `GET /v1/preferences/seniority-options` returns the canonical keys (`intern`, `junior`, `mid`, `senior`, `lead`, `executive`); `PUT /v1/preferences` saves one (the old `entry` key and labels are converted). The match checks treat `lead` and `executive` as one step.

Design: [05 Recommendations](design/05-RECOMMENDATIONS.md) and [11 Embedding worker](design/11-EMBEDDING-WORKER.md).

## Where the resume editor code lives

| Piece | Where |
|---|---|
| Editor UI (Resume Studio, preview, layout controls) | [`apps/web/src/studio/`](../apps/web/src/studio), [`App.tsx`](../apps/web/src/App.tsx) |
| Pure editing helpers (sections, entries, bullets), with tests | [`editor.ts`](../apps/web/src/editor.ts), [`editor.test.ts`](../apps/web/src/editor.test.ts) |
| API: `/v1/documents` CRUD, duplicate, review, `preview.pdf`, exports | [`api/main.py`](../backend/src/job_hunter/api/main.py) |
| PDF rendering (ReportLab, Latin Modern fonts, templates) | [`preparation/rendering.py`](../backend/src/job_hunter/preparation/rendering.py) |
| Design and behaviour spec | [09 Resume editor](design/09-RESUME-EDITOR.md) |

Documents autosave with revision checks. A PDF is exported from a reviewed revision and stays immutable, so an application keeps the exact resume that was attached.
