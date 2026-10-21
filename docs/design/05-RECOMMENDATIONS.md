# 05 — Recommendation and review workflow

**Current delivery scope:** [local application first; AWS-native services later](../deployment/DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

**Portability requirement:** follow [LOCAL-TO-AWS.md](../deployment/LOCAL-TO-AWS.md). Keep this component’s logic shared between local Docker execution and AWS; record adapter differences and unverified cloud checks in its handoff.

Read [README](README.md) and [contracts](CONTRACTS.md). Own `recommendations/` and ranking evaluation fixtures. Preserve the report's keyword-plus-semantic matching, using shared processed listings and confirmed profiles.

## Inputs and outputs

Inputs: authenticated user, active confirmed profile version, preferences revision, ready/open canonical job versions, prior reviews and pagination cursor. Output: ranked cards containing job ID/version, title/employer/location, salary if known, source/freshness, matched skills, evidence, ranking version and a next cursor. Never label a similarity score as a probability of getting hired.

How vectors are produced in the deployed environment (and when they are recomputed) is described in [11 Embedding worker](11-EMBEDDING-WORKER.md).

## Ranking v1

1. Apply explicit constraints first: selected locations/work modes/seniority and salary where comparable. Treat role keywords as ranking signals by default. Missing salary passes unless the user selects “exclude unknown”; never convert currency/period or infer eligibility silently.
2. Exclude dismissed jobs and already-reviewed cards from the discovery deck. Saved/tracked jobs remain accessible through tracking and direct details.
3. Retrieve up to 100 eligible keyword candidates using PostgreSQL full-text search over title/skills/description and up to 100 eligible semantic candidates using cosine distance against the profile vector.
4. Fuse the union with reciprocal rank fusion: `score = 1/(60 + keyword_rank) + 1/(60 + semantic_rank)`, absent ranks contribute zero. Stable tie-break: freshness then job UUID. Make candidate limits and ranking version explicit.
5. If profile/job vectors are unavailable, serve keyword results with `mode=keyword_fallback` and a clear reason. Never manufacture fake semantic results outside the explicitly labelled local fixture mode.
6. Produce deterministic explanations from overlapping validated skill tags and source facts. Deep LLM analysis belongs to 06, not recommendation requests.

Use exact pgvector search initially with indexes on common filters. Benchmark before introducing approximate HNSW search; if added later, evaluate recall under filters. Exact search is pgvector's default. [pgvector documentation](https://github.com/pgvector/pgvector)

For stable pagination, include profile/preference/ranking versions and a candidate snapshot identifier in an opaque, integrity-protected cursor. A simple POC implementation stores the bounded ordered candidate IDs/version IDs in a short-lived database snapshot owned by the user (30 minutes), rather than attempting unstable offsets over changing scores. 02 coordinates the extra snapshot table/RLS. If current job closure/review removes cards, skip them and advance consistently. Profile/preference changes invalidate the cursor with 409 and prompt refresh.

## Review/tracking integration

Swipe right/save and swipe left/dismiss call the same idempotent review endpoint as buttons. Undo removes the review decision; it does not delete application history. Saving ensures a tracked `saved` application exists. The frontend must wait for authoritative persistence or roll back optimistic state on failure.

## Unit tests required during implementation

Use pytest for hard-filter semantics, unknown salary policy, reciprocal-rank-fusion arithmetic, absent candidate ranks, duplicate candidate merging, deterministic tie-breaking, reviewed-job exclusions, fallback decisions, evidence formatting and cursor version/expiry validation. Use tiny manually calculated ranking examples; assert their expected order and scores independently of the implementation. Test that browsing never requests model inference through a spy/fake adapter.

Test SQL filtering, vector queries and persisted snapshot pagination against real PostgreSQL in integration tests. Recommendation-quality experiments are evaluation, not substitutes for correctness tests.

## Acceptance

- Same inputs/snapshot produce stable order; filters, missing-value policy and exclusions behave as documented.
- Semantic example: a relevant “data infrastructure” job can rank for profile “data pipelines”; compare against a keyword-only baseline rather than asserting semantic superiority.
- Preference/profile changes affect results and invalidate old cursors.
- No Bedrock invocation occurs during browsing/review.
- Empty results and pending embeddings have explicit responses and user guidance.
- Saved/dismissed actions persist and do not erase tracked applications.
- Evaluation reports keyword, semantic-only and hybrid relevance at a fixed K using the same labelled data and filters; latency includes database time.

Handoff records scoring parameters, SQL/index choices, snapshot contract and measured results.
