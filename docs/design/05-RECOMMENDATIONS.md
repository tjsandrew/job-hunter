# 05 — Recommendations and the review workflow

How Discover orders jobs for a user, and how Save and Pass feed the tracker. Related briefs: [04 Job ingestion](04-JOB-INGESTION.md) (where jobs come from), [03 Profiles](03-PROFILES-AND-RESUMES.md) (the confirmed profile) and [11 Embedding worker](11-EMBEDDING-WORKER.md) (how vectors are made in AWS). Shared names and paths are in [CONTRACTS](CONTRACTS.md).

## The two lists and the fallback

Discover has two ranked lists, plus the user's Saved and Passed lists.

| List | Endpoint | How it ranks |
|---|---|---|
| **All jobs** | `GET /v1/recommendations` | keyword ranker: TF-IDF text similarity, skill overlap and target-role match (`recommendations.py`, version `local_tfidf_hybrid_v1`). TF-IDF (term frequency–inverse document frequency) scores a word higher when it is frequent in a job but rare across jobs |
| **For you** | `GET /v1/recommendations/for-you` | semantic ranker: vector similarity after eligibility and role and level checks, then merged with the keyword order. It ranks against the confirmed profile |

**Why two.** The keyword ranker needs no model and no vectors, works the moment a profile is saved, and is easy to explain. The semantic ranker finds relevant jobs that share few words with the profile (for example a "data infrastructure" job for a profile about "data pipelines"). Merging the two lets each ordering lift jobs the other ranked lower.

**Fallback.** If the user has no confirmed profile, or the profile's vector is not ready yet, For you serves the keyword list and says why (`ranking_mode: keyword_fallback`, with a reason the page shows). A fake semantic result is never produced.

Scores are for ordering only. The app never shows a match percentage and never presents a score as a chance of being hired. The keyword results label their score "relevance score (not probability)". The For you status line says the order is meaningful, not the scores.

## Inputs

The authenticated user and their profile: the confirmed version for For you, and the current working profile for All jobs (so All jobs works before the first confirm). Also their saved preferences (roles, locations, work modes, seniority, minimum salary), the jobs in the shared pool, and their Save and Pass decisions. Discover's filters can replace the saved preferences for one request without saving them, and the **Posted** filter (3, 7, 14, 30 or 365 days; the app defaults to 14) narrows the pool before ranking.

## Eligibility comes first

Both lists use the same eligibility rules before any scoring:

- Only open jobs (unless the user asks to include closed or expired ones), posted within the Posted window, and only canonical rows, so a duplicate never appears twice ([04](04-JOB-INGESTION.md)). A job with no posting date always passes the Posted filter.
- Location and work mode are hard filters when selected. A job with no stated location or work mode does **not** pass a selected location or work mode.
- A minimum salary only filters salaries that can be compared. A job with no salary, a different currency, or a period that cannot be converted passes, so turning the filter on does not hide most listings. Currency is never converted; pay periods are converted to a yearly figure.
- Jobs the user saved or passed on are left out of the lists, along with the canonical row of any of them that has since become a duplicate.

## The keyword ranker

`rank_jobs` builds one query from the profile's summary and headline, its skills (including skills listed on experience entries), its target roles and its role titles. It scores each eligible job on three parts:

- text similarity, weight 0.50;
- the share of the profile's skills found in the job, weight 0.35;
- how well the job title matches a target role, weight 0.15.

A part with no input, such as a profile with no skills, is dropped and the rest are re-weighted. The result is deterministic, uses no model, and records which skills it matched, which is what the "Why it matches" lines on a job card show.

## The semantic ranker ("For you")

1. **Eligibility** as above.
2. **Role and level checks**, before ranking, so the top of the list is never "the nearest jobs minus the ones we then threw away". A job is blocked only on a clear mismatch. That means one of three things:
   - its role family is clearly different from the profile's target roles (adjacent families such as engineering and data pass);
   - it is a different kind of engineering job than the profile targets;
   - its seniority is more than one step away.

   Anything unknown never blocks.
3. **Similarity.** The remaining jobs are ranked by cosine similarity (how closely two vectors point in the same direction) between the profile vector and each job vector. Ties break on job ID, so the order is stable.
4. **Fusion.** The semantic order is merged with the keyword order by reciprocal-rank fusion (`rrf-v1`): each job scores `1/(60 + semantic position) + 1/(60 + keyword position)`, where the keyword position is counted among the jobs that passed the checks. A job the keyword ranker did not list scores only its semantic part. The constant 60 is the value from the original reciprocal-rank-fusion paper and was deliberately not tuned on our data. Fusion changes the order, never who is included, so the checks still decide eligibility. If the keyword ranking cannot be computed, the semantic order is served instead of an error.

Reasons shown on each card come from the matched skills first, then the role and level checks that matched, then a generic "close to the experience in your profile".

### Vectors

- Model: `jinaai/jina-embeddings-v2-small-en`, 512 dimensions, stored in Aurora with the pgvector extension for PostgreSQL (`job_embeddings`, `profile_embeddings`).
- Jobs and the profile are embedded with versioned text builders (`job-v2` and `profile-v2`), so a change in the recipe is visible in the ranking version. Vectors from different models are never compared.
- In AWS, the embed Lambda makes the vectors after an S3 flag and an SQS message ([11](11-EMBEDDING-WORKER.md)); locally the `services/embedder` HTTP service does.
- The comparison is **exact**, done in the API process over an in-memory copy of the job vectors (one matrix product per request), not a database vector index. At the size of this pool an exact comparison is simple and fully accurate, and an approximate index would add tuning and recall questions for no benefit. It would be worth revisiting only if the pool grew a lot.

## Paging

The lists page by `offset` and `limit` (default 20, at most 100). The API recomputes the ranking on each request. A page is therefore consistent for a given profile, preferences and pool, and the pool changes only when a pull or a close happens. There are no stored ranking snapshots or cursors, which keeps the API stateless. The cost is that a page boundary can shift if a pull or a closing date changes the pool between two requests.

## Save, Pass and the tracker

Save and Pass use one idempotent call, `PUT /v1/jobs/{id}/review`, with the decision `saved`, `dismissed` or `none`.

- Saving creates a tracked application in the `saved` status if none exists.
- `none` (Restore on the Passed tab) removes the decision. It never deletes an application the user has worked on: only a tracker row that exists solely because of the save, with no notes, dates or attachments, is removed when the job is unsaved.
- Saved and Passed jobs have their own tabs, so a Pass can be undone.

## Tests and evaluation

- Pytest covers the keyword ranker's filters, salary rule and scores (`test_recommendations.py`), the checks, similarity order and tie-breaking (`test_retrieval.py`), fusion arithmetic (the same file), and the For you route: its switches, fallbacks and reasons (`test_for_you.py`). Browsing never calls a model.
- Relevance has been checked only on a small labelled set. Larger labelling would be needed before drawing conclusions about how much the semantic and fused lists beat the keyword list ([known limitations](../status/PENDING.md)). The staging load tests that exercise both lists are in the [evaluation README](../../eval/README.md).
