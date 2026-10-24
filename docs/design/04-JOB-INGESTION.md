# 04 — Job discovery, normalisation and shared processing

**Current delivery scope:** [local application first; AWS-native services later](../deployment/DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

**Portability requirement:** follow [LOCAL-TO-AWS.md](../deployment/LOCAL-TO-AWS.md). Keep this component’s logic shared between local Docker execution and AWS; record adapter differences and unverified cloud checks in its handoff.

Read [README](README.md) and [contracts](CONTRACTS.md). Own `ingestion/`, `discover_jobs` and `process_job` handlers. This implements the report's shared job pool rather than a per-user scraper.

## Live discovery is a POC priority

Build live discovery early, before polishing recommendations or generation. The minimum live-discovery milestone is one working, permitted source fetching current job listings end to end; the target is two independent live sources to demonstrate the preliminary report's multi-source discovery. One source is an intermediate milestone, not completion of the multi-source commitment.

The implementer should actively investigate and test access, not stop at fixture adapters:

1. Investigate the report's proposed Adzuna and MyCareersFuture sources first using current official documentation and permitted access methods. Verify Singapore coverage rather than assuming it from the provider name.
2. Run a small live retrieval proof before building the full adapter: fetch a page, inspect actual fields, confirm usable application links and record retrieval time. Distinguish listing publication dates from retrieval timestamps.
3. If credentials or source approval are needed, document the exact setup and request the missing access while continuing other integration work. Do not silently mark a source as implemented using fixture responses.
4. If a proposed source is unavailable or unsuitable, investigate documented employer ATS feeds/APIs such as Greenhouse or Lever for selected employers with Singapore roles. Confirm current access rules and actual coverage. Explain that selected employer feeds provide narrower coverage than a job aggregator; do not promise comprehensive discovery.
5. Once a source works, run it through normalisation, persistence, processing and recommendations. Trigger discovery manually for verification and then verify the scheduled path. Capture source name, live record count, run time, sample provenance and failures in the handoff.

Fixtures keep development and demonstrations reproducible. They do not satisfy the live-discovery milestone. If no live source can be enabled, report live discovery as incomplete with the specific external blocker; complete the tested adapter boundary and remaining POC work without claiming the live requirement passed.

## Sources and access

MCF and Adzuna are proposed sources in the report, not verified working integrations. For each adapter record API documentation, access/credentials, Singapore coverage, pagination, rate limits and allowed use. Do not treat an undocumented endpoint as guaranteed public access. Keep a source disabled until a permitted access path is verified. Provide labelled fixtures for two source schemas and at least one live permitted adapter when available; report the actual live source count honestly.

Adapter interface: `fetch_page(cursor, changed_since, limit) -> {records, next_cursor, exhausted}`. Each record includes source/external ID, source URL, title, employer, location/work mode, description, salary/currency/period if stated, posting/expiry times if available, and fetch time. Preserve missing values as null.

## Discovery algorithm

1. EventBridge invokes discovery every six hours. Each enabled source receives its own run record, lease/checkpoint and bounded request budget. One failed source does not discard another's progress.
2. Default POC cap: 10 pages/source/run and 100 listings/page, subject to provider limits. Stop before the 240-second Lambda budget, persist a continuation cursor, and resume on the next scheduled run. Record backlog/incomplete state; do not claim full coverage. Cursor expiration must have an adapter-specific restart/window strategy.
3. For each page, validate and normalise records. Use transactional upserts and stable source identities so retried pages are safe. Commit jobs/versions/tasks/outbox before advancing the checkpoint.
4. Immediate-send new processing tasks through the shared outbox mechanism. Record discovered/updated/unchanged/malformed/failed counts, API throttles and run latency.
5. Handle 429 and temporary errors with bounded backoff and provider guidance. Do not sleep through the remaining invocation or spin aggressively. Persist progress for the next run.

A larger ingestion backlog may later justify a discovery queue for per-page continuation. Add it only when the bounded scheduled run is demonstrably inadequate; it is not required for the first POC.

## Canonicalisation and deduplication

First deduplicate `(source, external_id)`. Across sources, auto-merge only high-confidence exact evidence: same canonical employer application URL/requisition identity, or matching normalised employer/title/location plus identical cleaned description hash. Similar job titles alone must not merge records. Keep source provenance and source links for every merged record.

Prefer an explicit employer/original listing as the canonical content source; otherwise use a stable configured source priority, then freshness within that source. Do not alternate canonical content simply because sources are polled in different order. A changed canonical description creates a new immutable job version. Retain previous versions used by user analyses.

Close a job on explicit expiry/closure or a documented source-specific stale policy. A missed/partial discovery run is not proof that a job closed. Show fetched time and stale state to users.

## Shared processing

One task processes a new version: clean/validate text → extract structured requirements → generate embedding → commit readiness. Extract hard/soft skills, seniority, domain, and explicitly requested application documents, each with evidence spans in the source text. “Not stated” is valid. Use schema validation and bounded text; do not invent requirements.

Deduplicate processing by `(job_version_id, pipeline_version)`; reuse persisted completed stages on retry. A content-hash match avoids new inference. Track model/prompt versions and inference usage. Initial embedding candidate is Titan V2 at 512 dimensions, subject to preflight. Respect input limits and document truncation/segmentation; do not silently embed arbitrarily truncated listings.

## Unit tests required during implementation

Use pytest and checked-in synthetic provider responses for each adapter's field mapping, null handling, salary currency/period handling, pagination cursor logic, rate-limit/error classification and request-budget stopping. Test normalisation/content hashes, source identity, cross-source duplicate/nonduplicate decisions, stable canonical-source preference, changed-content detection and expiry/staleness rules. Test malformed extraction output and processing checkpoint reuse with fake model/repository adapters.

No unit test should call a live job API. Live retrieval and scheduled ingestion are separately marked integration tests; fixture success never proves a live source works.

## Acceptance

- Repeating the same discovery page creates no new canonical job/version/task.
- A real content update creates one new version; prior analyses still reference the old version.
- Cross-source duplicates merge with provenance; distinct same-title openings remain distinct.
- Source failure, timeout or partial pagination preserves progress and does not close unseen jobs.
- At least one permitted live source fetches current jobs into the shared pool and exposes them through the user workflow; two independent live sources are the multi-source acceptance target. Record which milestone actually passed.
- Two fixture adapters exercise the same pipeline as live adapters; UI/evaluation labels fixture data.
- Job processing occurs once per unchanged content version in the healthy path; retry behaviour and repeated-inference risk are documented.
- Malformed model output fails safely; prompt instructions inside listings do not alter task behaviour.
- Produce a labelled deduplication set with true duplicate and nonduplicate pairs for 08.

Handoff includes source access status, seeded commands, enabled sources, cursor semantics, limits and known coverage gaps.

## Collection sizing agreed during implementation

Target approximately 1,000 live Singapore-location listings across employers and role categories. First useful milestone is 300–500; report the actual achieved count and any shortfall. Count only records whose source location explicitly includes Singapore. Multi-location jobs including Singapore are labelled; description mentions, employer headquarters and worldwide-remote eligibility alone do not qualify. Use bounded documented public feeds, reuse recent retrieved data, stop a source on rate limiting, and do not pad the collection with global jobs or fixtures. Separate synthetic 5,000–10,000-record datasets may be used for load tests and never counted as live coverage. JustPostedJobs returned 429 during its limited review; no further requests in this collection pass.

## As built (October 2026)

The brief above describes the target. What exists today, and where it differs:

- **Sources:** Greenhouse, Lever, SmartRecruiters and MyCareersFuture (keyword search, no key) and Adzuna (keyword search, needs `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`; its description is only a snippet, and Singapore coverage must be confirmed with the first real call). Adapters are in `backend/src/job_hunter/ingestion/discovery.py`.
- **Cloud path:** not an every-six-hours Lambda with checkpoints. A Discovery Lambda outside the VPC reads the feeds and stores one snapshot in S3; an Import Lambda inside the VPC loads the next N new jobs (default 10) and sets the embed flag. The **Pull jobs** GitHub workflow starts it; an EventBridge schedule exists but is off. See [JOB-PULL-ROLLOUT.md](../deployment/JOB-PULL-ROLLOUT.md).
- **Deduplication:** `(source, source_board, external_id)` identifies a row within a source. Across sources, `ingestion/dedup.py` links rows that are the same posting without deleting any: `jobs.match_key` (normalised employer, title, location), `jobs.canonical_job_id` (NULL on the row users see) and `jobs.also_seen_on` (on the canonical row). Two rows of different sources are linked only when they share a listing URL, or share the `match_key` and their descriptions are near-identical text (word-set similarity of 0.6 or more, which also accepts an aggregator's shortened copy). Similar titles alone never merge and rows of one source never merge. The canonical row is chosen by authority (employer board, then MyCareersFuture, then Adzuna), then the earlier posting date, then the id, so the result does not depend on polling order. Discover, For you and embedding skip duplicates; saving a duplicate hides its canonical row for that user.
- **Labelled set:** `backend/tests/fixtures/dedup_pairs.json` has 16 pairs (8 true duplicates, 8 look-alikes that are different postings). The test `test_the_labelled_set_has_no_false_merges_and_finds_the_duplicates` prints precision and recall (currently 1.00 and 1.00 on this small set; it is a regression guard, not a measure of real-world accuracy).
- **Not built:** closing jobs that disappear from a source, per-source run records and checkpoints, structured requirement extraction at ingestion (fit analysis does it on demand), the 1,000-listing collection target.

