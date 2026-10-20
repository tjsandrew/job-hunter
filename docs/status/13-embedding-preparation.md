# Job and profile embedding functions (local)

Implemented 16-17 October 2026 on `noah/semantic-recommendations`. The ingestion-owned classification changes in this
section are currently local and uncommitted. The embedding and recommendation code lives in
`backend/src/job_hunter/embedding/`. It is wired into the app through a small number of hooks (see "Backfill and the flagged
endpoint"): the confirm and preferences-save hooks, `GET /v1/recommendations/for-you` and the Discover "For you / All jobs"
toggle. The original keyword ranker stays as `/v1/recommendations` ("All jobs") and as the fallback. Two migrations:
`0012_embedding_tables` adds three **new** tables and alters nothing, and `0013_job_seniority` adds three nullable columns to `jobs`
(`seniority`, `seniority_source`, `seniority_evidence`), set at ingestion like `jobs.category` (see Storage and Match features).

## What it is for

One place owns how a job or a profile becomes text for the embedder, so ingestion and profile code only call a function
and never need to know the text format. The functions assemble versioned text, call the standalone embedder service
(through the client in `12-embedding-client.md`) and hand the vector to a storage object. A job's role family and seniority are
deliberately kept *outside* the vector and are **not** worked out here: ingestion sets them on the job row (see Match features).

## How to call it

```python
from job_hunter.embedding import (HttpEmbedder, JobEmbedRequest, JobTextInput, ProfileEmbedRequest,
                                  embed_job, embed_profile)

outcome = embed_job(
    JobEmbedRequest(job_id=str(job.id), job=JobTextInput.from_job(job)),
    embedder=HttpEmbedder("http://embedder:8100"), store=store)

outcome = embed_profile(
    ProfileEmbedRequest(profile_version_id=str(version.id), snapshot=snapshot,
                        target_roles=preferences.get("target_roles")),
    embedder=embedder, store=store)
```

Batch versions `embed_jobs` and `embed_profiles` embed many items per embedder call (default 32, maximum 64).

`outcome.status` is one of `ready` (vector stored), `unchanged` (text, text version and model are unchanged; nothing to do),
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

A job's **role family** and **seniority** are properties of the job, so they are set once, at **ingestion**, on the job row, and
everything else reads them from there (no second copy, nothing classified lazily for jobs):

| Column | Set by | Meaning |
|---|---|---|
| `jobs.category` (+ `category_source`, `category_evidence`) | `classify_title()` in `import_jobs.py`, which calls `classify_role_family` in `backend/src/job_hunter/role_family.py` (source label `role-family-v1`) | one of 12 families; "other" = no family matched |
| `jobs.seniority` (+ `seniority_source`, `seniority_evidence`) | `classify_seniority()` in `backend/src/job_hunter/seniority.py` (source `seniority-v1`, or `stated` when the source names the level itself via an optional `stated_seniority` on the record) | JSON list of ladder levels (intern, junior, mid, senior, lead, executive); `[]` = names no level (open to all levels); `NULL` = not classified yet |

- **Reading.** `db_retrieval.load_job_candidates` reads both columns. An empty, "other", unknown, invalid or `NULL` value counts as
  unknown / open to all levels, so it **never blocks** a job (a source whose ingestion skipped the classifiers therefore weakens the
  checks silently; `backfill --classification-report` shows per source how many open jobs have no category or seniority).
- **Profiles.** A profile's target-role families and level are worked out live from its preferences on each request with the same
  functions (`extract_profile_features`); "executive" is its own level but the checks count it as the same step as "lead" (`CHECK_LADDER`
  in `seniority.py`; split them only if a larger labelled set shows it helps). "executive" is stored only when a source or a user
  states it and is never read from a job title ("Account Executive" is a sales job); director/VP/chief/head-of titles stay "lead".
- **Checks.** Role family: same / adjacent / different / unknown, only "different" blocks (adjacency is a judgement call,
  `ADJACENT_FAMILIES` in `features.py`). Seniority: only a clear mismatch (two or more steps apart) blocks; an unspecified job is
  flagged `all_levels`.
- **Retuning.** After editing the keyword tables, run `make reclassify-jobs` (`python -m job_hunter.import_jobs --reclassify`): it
  recomputes both columns from the titles already in the database, without a fetch, and keeps a level a source stated. Re-running
  `make import-jobs` / `make replay-jobs` also refreshes them (the category and seniority fields count as content). No re-embedding
  is needed. If the deterministic rules are later replaced (for example by an LLM that returns the level and the family at
  ingestion), the two classify functions are the only swap point and the columns stay the same.
- **Ownership.** The two classifier modules are owned by the recommender; ingestion paths call them and do not edit the tables.

## Storage

`EmbeddingStore` is a small interface (`get_state(key, text_version)`, `save(key, record)`) with
an in-memory implementation (tests, offline runs) and database implementations in `db_store.py` (import it explicitly; it needs
SQLAlchemy). Embeddings live in **separate new tables** (migration `0012_embedding_tables`, chained after `0011`), so `jobs`,
`profile_versions` and the resume intake flow are not touched by it (the only change to an existing table is migration `0013`'s
three nullable seniority columns on `jobs`, see Match features):

- **`job_embeddings`**: one row per job per text format (`unique (job_id, text_version)`): vector, model, dimensions, input hash,
  status and a short reason. A new text format adds a row; a new model replaces the row for that format. Database checks require a
  vector exactly when the status is `ready`. Rows are deleted with their job.
- **`profile_embeddings`**: the same, per profile version, with a `user_id` and the **same per-user row-level security** as
  `profile_versions`. The owner is read from the profile version itself, so a caller cannot write an embedding for someone else's
  profile.
- **Legacy `job_match_features`**: migration `0012` created it; migration `0013` copies any saved seniority to `jobs` (preserving
  `stated` provenance) and drops the table. `0012` is kept unchanged because it may already have been applied. Existing jobs with
  no legacy feature still need `make reclassify-jobs` after migration.

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
  `--classification-report` (read-only) lists, per source, open jobs with no category or no seniority, and a normal run prints a note
  when there are any.
- **Endpoint:** `GET /v1/recommendations/for-you` (`limit`, `offset`, `q` for the Discover search text), **on by default in compose (`FOR_YOU_ENABLED`, set 0 to switch off)** (404 `FOR_YOU_DISABLED`
  when off; the application default without the variable is off). It excludes saved/dismissed jobs like the existing endpoint, runs
  eligibility, then the role and level checks, then similarity, and returns the existing result shape without a score (only the order
  is meaningful) plus `ranking_mode` (`semantic` or `keyword_fallback`), `fallback_reason` and `blocked_by_checks`. With no confirmed
  profile or no profile vector it returns the keyword ranker's result and says why. `/v1/recommendations` is unchanged and the OpenAPI
  contract has the one extra path.
- **Keyword fusion (on by default, `FOR_YOU_FUSION=0` switches it off):** after the checks, the semantic order is merged with the keyword
  ranker's order by reciprocal-rank fusion (`fuse_rankings`, k = 60, no tuned weight). Fusion only reorders the jobs that passed the checks;
  it never adds or drops one, and `ranking_mode` stays `semantic`. The response adds `ranking_fusion` (`rrf-v1` or null) and the ranking
  version ends in `+rrf-v1`. If the keyword ranking cannot be computed the page logs it and serves the semantic order. Evidence: on 15
  fictional profiles and 356 judged pairs the fused list scored nDCG@10 0.76 against 0.61 (keyword) and 0.67 (semantic with checks); see
  the 2026-10-20 "round 2c" entry of `RECOMMENDER-EVALUATION-LOG.md`. LLM-judged labels only.
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
  A new ingestion path must also fill `jobs.category` and `jobs.seniority` (with their `_source` / `_evidence`) by calling
  `job_hunter.job_classification.classify_job(title, stated_seniority=None)` after title normalization and before saving:
  the recommender's role and level checks, Andrew's keyword ranker, the job API output, the resume builder
  and search all read those columns. The embedder itself classifies nothing for jobs.
- **Preference seniority:** `GET /v1/preferences/seniority-options` serves the backend's six canonical keys (intern, junior, mid, senior, lead, executive) and display labels (the dropdown's own words).
  The UI fetches these when Job preferences opens, while target roles remain free text. `PUT /v1/preferences` validates and
  stores canonical keys; the earlier `entry` key and the Junior and Mid-level labels are accepted and normalized for compatibility.
- **Role check without target roles** falls back to the profile headline (else the latest role). A stated seniority of "Executive" is kept as
  "executive" and compared as the same step as "lead"; "executive" is never read from a job title ("Account Executive" is a sales job).

## Verified

- The new rollback-only `scripts/smoke_semantic_pipeline.py` passed against the local PostgreSQL and Jina service: it applies `0012`
  and `0013` in a throwaway schema, checks that a legacy stated level survives migration, imports four jobs, embeds and re-backfills
  them, checks reclassification is idempotent, embeds a profile, checks two semantic matches and two role/level blocks, and runs the keyword ranker. The transaction rolls
  back, leaving the 71 development jobs unchanged. A source-mounted API on port 8001 answered `200` for health, For you
  (`semantic`, 35 results) and the keyword endpoint (70 results).
- Against the 71 existing jobs, source-mounted `backfill --jobs --limit 71` returned 71 `unchanged`, and
  `import_jobs --reclassify` returned 71 `unchanged`. The classification report found zero missing fields, but 18 `other`
  categories and 58 jobs with no stated seniority level.
- The full backend `pytest` suite passes with database integration enabled: **603 passed** (`pytest==9.1.1` and
  `httpx==0.28.1` installed in a temporary API test container), as do the web suite (227 tests) and the production web
  build. `scripts/check_profile_bank_migration.py` (the CI migration check: an old schema upgraded through `0013` to a
  single head, every ORM column created by a migration) passes too.
- End to end against the local embedder service (Jina, 512-d): 70 real listings embedded in about 10 seconds in batches of 16;
  a second run skipped all 70 in 0.02 seconds. Alice's demo profile embedded with `profile-v2`.
- 2026-10-17: the development database is at `0013` with category and seniority populated on all 71 jobs; a read-only check
  confirmed the count. The source-mounted For you route answered `semantic` with 35 results. This does not validate relevance.

## Not verified / known gaps

- Keeping **job** vectors current when jobs are ingested is for the ingestion owner (`embed_job(s)` after insert/update, or
  `make backfill`); until then new jobs have no vector and do not appear in For you. Profiles are embedded by the confirm and
  preferences-save hooks.
- Every ingestion path, including Dao Yi's, must classify both fields before embedding. `make backfill` only creates vectors;
  it does not repair missing category or seniority. After migration or classifier retuning, run `make reclassify-jobs` and check
  `backfill --classification-report` before treating role/level safeguards as active. Missing or unknown fields currently fail open.
- All relevance labels so far are assistant-only and non-blind, on 70 listings (48 from one employer, 2 with stated skills).
  The replacement gate (match or beat the keyword ranker on a broader, independently labelled set) has not been met.
- Role family and seniority come from title keywords (`role_family.py`, `seniority.py`); about a quarter of titles are "other"
  (unknown, never blocked) and about 80% of today's jobs name no level in the title (currently treated as open to all levels,
  not proof that the employer has no level requirement). Years of experience are not used to
  infer seniority, and "associate" and "manager" are not read as levels. A job source whose ingestion skips the classifiers is
  invisible to the checks until the coverage report is looked at.
- The embedding model is English-only (`jina-embeddings-v2-small-en`).
- The migrations have been applied to the development database only; their position in the chain (`0012` and `0013`, after Andrew's
  `0011`) must be re-checked if a newer migration lands first.
- The profile text includes the target roles from preferences, which can change without a new profile version; the stored input
  hash detects that, and the preferences-save hook re-embeds.
