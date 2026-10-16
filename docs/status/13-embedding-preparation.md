# Job and profile embedding functions (local)

Implemented 16 October 2026 on `noah/embedder-service`. Local commits only; no push or PR. Everything lives in
`backend/src/job_hunter/embedding/` and is **not wired into the API, ingestion, profile saves, the database, search or
ranking**. The live app still uses the existing keyword/skill/role ranker. There is no schema change.

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
    JobEmbedRequest(job_id=str(job.id), job=JobTextInput.from_job(job), category=job.category),
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

- **Job, `job-v1`:** `Role`, `Stated skills` (only when the source lists skills), `Work` and `Requirements` taken from known
  headings in the description (company, team, salary, equal-opportunity and contact text dropped), or the whole normalised
  description when no known section is found. Company name, location, work mode and salary are not in the text.
- **Profile, `profile-v2`:** `Target role` (from preferences), `Summary`, `Demonstrated skills`, `Roles`, `Projects`,
  `Highlights`. Contact data is removed with the same stripping the older `profile-v1` text uses; education is not
  included. `profile-v1` is untouched.
- Re-embedding is skipped when the text hash, text version and (if given) the model are unchanged.

## Match features and checks (outside the vector)

- **Seniority:** a five-step ladder (intern, entry, mid, senior, lead) from a stated value or conservative title keywords. A job that
  names no level counts as open to all levels and is flagged `all_levels`. Only a clear mismatch (two or more steps apart) blocks.
- **Role family:** reuses `jobs.category` from `classify_title()` in `import_jobs.py`. Results are same / adjacent / different /
  unknown; only "different" blocks, and unknown (including category "other") never does. The adjacency list is a judgement
  call (`ADJACENT_FAMILIES` in `features.py`).
- These are checks for the future recommender to use; nothing calls them yet.

## Storage

`EmbeddingStore` is a small interface (`get_state(key, text_version)`, `save(key, record)`, `save_features(key, features)`).
Only `InMemoryEmbeddingStore` exists; no table has been created. The interface assumes **separate tables** rather than extra
columns on `jobs` and `profile_versions`:

- **Embedding rows** are keyed by `(entity, text_version)` and hold the vector, model, dimensions, input hash, status and a short
  reason. A new text version adds a row instead of overwriting, so formats can be compared side by side; a new model replaces the
  row for that text version.
- **Match features** (seniority levels and source, role family) are keyed by the entity alone and are saved on every run,
  independently of whether an embedding succeeded, because they describe the job or profile rather than the vector.

The proposed layout (job embeddings, profile embeddings with the same per-user row-level security as `profile_versions`, and a
job match-features table) is awaiting agreement with the other owners. The existing `embedding` columns on `jobs` and
`profile_versions` would stay untouched.

## Verified

- 102 embedding tests plus the 9 existing ranking tests pass inside the backend container (`pytest` with `backend/src` mounted
  and `PYTHONPATH=/app/src`). The text builders and checks also run on the host Python.
- End to end against the local embedder service (Jina, 512-d): 70 real listings embedded in about 10 seconds in batches of 16;
  a second run skipped all 70 in 0.02 seconds. Alice's demo profile embedded with `profile-v2`.

## Not verified / known gaps

- No database storage, migration, call from ingestion or profile save, or backfill command yet.
- Years-of-experience is not used to infer seniority, and "associate" and "manager" are deliberately not read as levels.
- Role families depend on the title-keyword classifier: about 29% of the 70 sample listings fall under "other", so the role
  check does nothing for them; most sample listings state no level, so the seniority check rarely fires.
- Replaying the checks on 75 judged pairs (assistant labels, same cases that motivated them) blocked none of the 5 good
  pairs, 1 of 22 partial and 16 of 48 poor. This shows the checks are plausible, not that they are accurate.
- The profile text includes the target role from preferences, which can change without a new profile version; the
  stored input hash is what detects that.
