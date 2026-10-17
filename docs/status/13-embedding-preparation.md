# Job and profile embedding functions (local)

Implemented 16-17 October 2026 on `noah/embedder-service`. Local commits; nothing pushed. Everything lives in
`backend/src/job_hunter/embedding/`. It is wired into the app through a small number of hooks (see "Backfill and the flagged
endpoint"): the confirm and preferences-save hooks, `GET /v1/recommendations/for-you` and the Discover "For you / All jobs"
toggle. The original keyword ranker stays as `/v1/recommendations` ("All jobs") and as the fallback. The only schema change is
migration `0012_embedding_tables`, which adds three **new** tables and alters no existing table or column (see Storage).

## What it is for

One place owns how a job or a profile becomes text for the embedder, so ingestion and profile code only call a function
and never need to know the text format. The functions assemble versioned text, call the standalone embedder service
(through the client in `12-embedding-client.md`), work out a few match features that are deliberately kept *outside* the
vector, and hand the result to a storage object.

## How to call it

```python
from job_hunter.embedding import (HttpEmbedder, JobEmbedRequest, JobTextInput, ProfileEmbedRequest,
                                  embed_job, embed_profile)

outcome = embed_job(
    JobEmbedRequest(job_id=str(job.id), job=JobTextInput.from_job(job)),
    embedder=HttpEmbedder("http://embedder:8100"), store=store)

outcome = embed_profile(
    ProfileEmbedRequest(profile_version_id=str(version.id), snapshot=snapshot,
                        target_roles=preferences.get("target_roles"), seniority_preference=preferences.get("seniority")),
    embedder=embedder, store=store)
```

Batch versions `embed_jobs` and `embed_profiles` embed many items per embedder call (default 32, maximum 64).

`outcome.status` is one of `ready` (vector stored), `unchanged` (nothing to do; match features were refreshed),
`pending` (embedder unavailable, retry later), `failed` (unusable response or internal error) or `no_content` (blank
title or empty profile). **The functions do not raise for expected problems**, so an embedder outage cannot break an import
or a profile save. Reasons are short and never contain the input text. The caller supplies the embedder and the store, and
the caller's database session lives inside the store, which keeps per-user row-level security intact.

## Text (versioned, deterministic)

- **Job, `job-v2` (the default):** `Role`, `Stated skills` (only when the source lists skills) and `Description`, the whole
  normalised description (links, emails, bullet marks and stray replacement characters cleaned; capped at 8000 characters). No
  heading detection, so nothing can be dropped silently. Company name, location, work mode and salary are not in the text.
- **Job, `job-v1` and `job-v3` (kept, not the default):** `Role`, `Stated skills`, `Work` and `Requirements` taken from known
  headings (company, team, salary, equal-opportunity and contact text dropped). `job-v1` is frozen as first built; `job-v3` also
  accepts headings whose spaces were lost ("Whatyou'll do") and falls back to the whole description unless both Work and
  Requirements are found. Choose one with `embed_job(s)(..., text_version=...)` or `build_job_text(job, version=...)`; each
  version is stored as its own row, so formats can be compared side by side. `python -m job_hunter.embedding.backfill --text-report`
  shows, per source, how heading detection would do (read-only, embeds nothing). Heading detection will be reconsidered as the
  default once a larger, more varied job set exists (on the 70 listings it scored higher than the whole description; see the
  evaluation log in the offline notes).
- **Profile, `profile-v2`:** `Target role` (from preferences), `Summary`, `Demonstrated skills`, `Roles`, `Projects`,
  `Highlights`. Contact data is removed with the same stripping the older `profile-v1` text uses; education is not
  included. `profile-v1` is untouched.
- Re-embedding is skipped when the text hash, text version and (if given) the model are unchanged.

## Match features and checks (outside the vector)

- **Seniority:** a five-step ladder (intern, entry, mid, senior, lead) from a stated value or conservative title keywords. A job that
  names no level counts as open to all levels and is flagged `all_levels`. Only a clear mismatch (two or more steps apart) blocks.
- **Role family:** worked out from the job title alone by the shared classifier in `backend/src/job_hunter/role_family.py`
  (`classify_role_family`; the old `embedding/role_family.py` path still imports it). Ingestion calls the **same** classifier
  (`classify_title()` in `import_jobs.py`, source label `role-family-v1`) to fill `jobs.category`, so `jobs.category` and the
  recommender's role family always agree, and the keyword tables in `role_family.py` are the one place to tune. The family is
  worked out when a job is embedded and saved in `job_match_features`; For you reads the saved value (nothing is classified at
  request time for jobs; a profile's target-role families are worked out from its preferences on each request). Results are
  same / adjacent / different / unknown; only "different" blocks, and unknown (family "other") never does. The adjacency list is
  a judgement call (`ADJACENT_FAMILIES` in `features.py`). After the keyword tables change, re-run `make import-jobs` /
  `make replay-jobs` to refresh `jobs.category` (a changed category counts as an update) and `make backfill` to refresh the saved
  families (no re-embedding needed).
- The checks are used by the For you ranking (see below); the old ingestion-category fallback no longer exists.

## Storage

`EmbeddingStore` is a small interface (`get_state(key, text_version)`, `save(key, record)`, `save_features(key, features)`) with
an in-memory implementation (tests, offline runs) and database implementations in `db_store.py` (import it explicitly; it needs
SQLAlchemy). Embeddings live in **separate new tables** (migration `0012_embedding_tables`, chained after `0011`), so `jobs`,
`profile_versions` and the resume intake flow are not touched:

- **`job_embeddings`**: one row per job per text format (`unique (job_id, text_version)`): vector, model, dimensions, input hash,
  status and a short reason. A new text format adds a row; a new model replaces the row for that format. Database checks require a
  vector exactly when the status is `ready`. Rows are deleted with their job.
- **`profile_embeddings`**: the same, per profile version, with a `user_id` and the **same per-user row-level security** as
  `profile_versions`. The owner is read from the profile version itself, so a caller cannot write an embedding for someone else's
  profile.
- **`job_match_features`**: one row per job (seniority levels and where they came from, role family) as JSON with a feature
  version. It is saved on every run, independently of whether the embedding succeeded. Profile match features are read live from
  preferences and need no table.

`DbJobEmbeddingStore` and `DbProfileEmbeddingStore` take the caller's SQLAlchemy `Session` and never commit; every write runs in a
savepoint, so one bad row cannot poison a batch. The older `embedding` columns on `jobs` and `profile_versions` are left unused.
The migration runs automatically when the api container starts (`alembic upgrade head` in `compose.yaml`), so a stack
rebuilt from this branch picks it up.

## Semantic candidate retrieval

`retrieval.py` (pure, in memory) and `db_retrieval.py` (loads from the embedding tables) rank jobs for a profile in this order:

1. **Eligibility**: open status, wanted location and work mode, optional excluded job ids. It reuses the existing ranker's own
   helpers, and a test pins it to return exactly the set of jobs `rank_jobs` returns.
2. **Checks**: a job whose role family is clearly different, or whose level is two or more steps from the profile's, is blocked.
   Unknown and unspecified never block. Blocked jobs are returned in a separate list (with their similarity) for evaluation.
3. **Similarity**: the rest are ordered by cosine similarity. Only the order is meaningful; do not show the raw number as a
   percentage. Each result carries short positive reasons ("Same kind of role as your target role", "Level matches your profile");
   caveats such as "level not stated" are not shown as reasons.

Vectors from different models are never compared: candidates must have been embedded with the same model and text version as the
profile. `recommend_for_profile` returns `None` when the profile has no usable vector, which is the caller's cue to fall back to the
existing keyword ranker. Similarity is computed exactly in memory (fine at proof-of-concept scale); a pgvector query can replace it
later without changing callers.

## Backfill and the flagged "for you" endpoint

- **Backfill:** `python -m job_hunter.embedding.backfill [--jobs] [--profiles] [--user alice] [--limit N] [--force]` (in the api
  container, `docker compose run --rm --no-deps api python -m job_hunter.embedding.backfill`). It embeds every open job and each
  user's *confirmed* profile version, commits per batch / per user, skips unchanged items and retries pending or failed ones. The
  embedder URL comes from `EMBEDDER_URL` (default `http://embedder:8100`). In local mode the users come from the development identity
  map; a cloud deployment must pass `user_ids` itself. Also callable as `backfill_jobs` / `backfill_profiles`.
- **Endpoint:** `GET /v1/recommendations/for-you` (`limit`, `offset`, `q` for the Discover search text), **on by default in compose (`FOR_YOU_ENABLED`, set 0 to switch off)** (404 `FOR_YOU_DISABLED`
  when off; the application default without the variable is off). It excludes saved/dismissed jobs like the existing endpoint, runs
  eligibility, then the role and level checks, then similarity, and returns the existing result shape without a score (only the order
  is meaningful) plus `ranking_mode` (`semantic` or `keyword_fallback`), `fallback_reason` and `blocked_by_checks`. With no confirmed
  profile or no profile vector it returns the keyword ranker's result and says why. `/v1/recommendations` is unchanged and the OpenAPI
  contract has the one extra path.
- **Discover page:** a "For you / All jobs" toggle (For you is the default). For you calls `/v1/recommendations/for-you` (it accepts `q` for typed search);
  All jobs is the original keyword list. If the For you request errors, the page falls back to All jobs with a note; if the server itself fell
  back, it shows the server's reason. `reasons` on For you cards are user-facing positives only (matched skills, role/level checks that
  matched); caveats such as "level not stated" are not reasons, and the check verdicts come back as `role_check` / `seniority_check`.
  A hint asks for target roles and seniority when either is missing.
- **Profile hook (`EMBED_ON_SAVE`, on by default in compose; off in the application when the variable is unset):** `POST /v1/profile/confirm` and `PUT /v1/preferences` call
  `profile_sync.embed_after_save` after saving. It embeds the user's confirmed profile version in the same transaction, inside a savepoint
  with a 5 second embedder timeout, and never raises: an embedder outage leaves the profile `pending` (the for-you endpoint falls back,
  the backfill retries), an unexpected error is logged and swallowed, and unchanged text skips the embedder entirely. Saving preferences
  without a confirmed profile does nothing. Roles are part of the embedded text, so changing them re-embeds.
- **Job side:** keeping job vectors current when jobs are ingested is still for the ingestion owner, who calls `embed_job(s)`.
  A new ingestion path should also fill `jobs.category` with `classify_title(title)` from `import_jobs.py` (or
  `classify_role_family(title)` from `job_hunter.role_family`); the embedder does not read `jobs.category`, but Andrew's
  keyword ranker, the job API output, the resume builder and search still do.
- **Role check without target roles** falls back to the profile headline (else the latest role). A stated seniority of "Executive" counts
  as the top of the ladder; "executive" is never read from a job title ("Account Executive" is a sales job).

## Verified

- The full backend suite (567 tests, including the database integration tests, the OpenAPI contract and the new backfill and for-you tests) passes inside the backend container (`pytest` with `backend/src` mounted
  and `PYTHONPATH=/app/src`). The text builders and checks also run on the host Python.
- 10 database integration tests (`backend/tests/integration/test_embedding_db_store.py`, `RUN_DB_INTEGRATION=1`) run in a
  rolled-back transaction with a throwaway schema and a restricted role, like the existing integration tests: migration adds only the
  three new tables, changes no existing column, is re-runnable and reversible; stores, constraints, cascades, per-user isolation and
  the embedding functions on top of the database stores.
- The whole migration chain (`0001` to `0012`) applied to a throwaway database with a single head, downgraded to `0011` and
  re-applied; after seeding, the full existing backend suite (498 tests, including the profile and resume integration tests) passed
  against it. The throwaway database was dropped; the development database was not touched.
- End to end against the local embedder service (Jina, 512-d): 70 real listings embedded in about 10 seconds in batches of 16;
  a second run skipped all 70 in 0.02 seconds. Alice's demo profile embedded with `profile-v2`.

## Not verified / known gaps

- Keeping **job** vectors current when jobs are ingested is for the ingestion owner (`embed_job(s)` after insert/update, or
  `make backfill`); until then new jobs have no vector and do not appear in For you. Profiles are embedded by the confirm and
  preferences-save hooks.
- All relevance labels so far are assistant-only and non-blind, on 70 listings (48 from one employer, 2 with stated skills).
  The replacement gate (match or beat the keyword ranker on a broader, independently labelled set) has not been met.
- Role family comes from title keywords (`role_family.py`); about a quarter of titles are "other" (unknown, never blocked).
  Years of experience are not used to infer seniority, and "associate" and "manager" are not read as levels.
- The embedding model is English-only (`jina-embeddings-v2-small-en`).
- The migration has been applied to the development database only; its position in the chain (`0012`, after Andrew's `0011`) must be
  re-checked if a newer migration lands first.
- The profile text includes the target roles from preferences, which can change without a new profile version; the stored input
  hash detects that, and the preferences-save hook re-embeds.
