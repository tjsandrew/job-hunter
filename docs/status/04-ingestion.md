# Handoff 04 — Job ingestion

## Implemented locally

`backend/src/job_hunter/ingestion/discovery.py` provides `discover(config)` and `discover_report(config)`. `config` can be a `DiscoveryConfig` or a mapping using the dataclass field names. Normalized records contain `source`, `source_board`, `external_id`, `source_url`, `title`, `employer`, `location`, `work_mode`, plain-text `description`, nullable salary fields, nullable `posted_at`/`expires_at`, retrieval `fetched_at`, and stable source identity `dedup_key` (`source:board:id`). Employer boards fall back to their configured token as employer when the feed omits a company name.

The stdlib CLI prints a small JSON preview, failures, and truncation state. Configure board tokens with repeatable `--greenhouse` / `--lever` arguments or comma-separated `GREENHOUSE_BOARDS` / `LEVER_BOARDS`; there are no credentials. Example:

```sh
PYTHONPATH=backend/src python -m job_hunter.ingestion.discovery --greenhouse stripe --singapore-only --limit 3
```

Greenhouse's documented public list endpoint returns a whole board, without documented pagination; this adapter makes one request per board and caps returned records at 1,000. Lever's documented public postings endpoint supports `skip` and `limit`; this adapter caps pages at 10, page size at 100, and records at 1,000 per board. Both have a configurable timeout capped at 60 seconds. Board failures are isolated and classified in `discover_report`; no retry loop or unbounded backoff is used. Only public GET job feeds are called.

## Live source verification

At `2026-10-04 16:08:13 UTC`, a live GET to Stripe's public Greenhouse board `https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true` returned HTTP 200, 5,541,900 bytes, and 716 jobs (`meta.total=716`). The listing fields included IDs, titles, locations, absolute application URLs, publication/update times, and descriptions. A search across location and description text found 54 Singapore mentions; this count includes description mentions and is not a count of Singapore-located roles.

The adapter itself was then run end to end at `2026-10-04 16:18:48 UTC` with `--greenhouse stripe --singapore-only`. It returned 52 records whose location fields matched Singapore, no failures, and no truncation. Two preview records had titles “Account Executive, Commercial Hunter” and “Account Executive, Cross Border China”, each with a Stripe application URL, Singapore location, retrieval timestamp, and null salary fields. These are a few attributable live examples; no full descriptions are retained in this handoff. The adapter's filtered count differs from the earlier broad text search because it filters the normalized location field only. This is public employer-board coverage, not a comprehensive job aggregator. Adzuna requires registered `app_id` and `app_key` per its official API overview, and no credentials are configured. No MyCareersFuture API access route was verified for this adapter.

Greenhouse's current Job Board API documentation states that GET board data is public without authentication, documents `/v1/boards/{board_token}/jobs`, and supports `content=true` for descriptions and offices: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html). Lever documents its public postings list as published listings with `skip`/`limit` pagination and listing fields including hosted URL, location, description, and optional salary: [Lever Postings API](https://github.com/lever/postings-api). The Lalamove Lever board was live-verified and imported as part of the bounded first collection.

## JustPostedJobs limited page review

This was a bounded page review, not an integration or snapshot feed. The site's `robots.txt` returned HTTP 200 on 2026-10-05 (Singapore local date). It permits `/` and `/jobs/`, and disallows `/api/`, `/search`, `/log_click`, `/stats/`, `/health`, `/enrich/`, and `/queue/`. No API routes were requested or probed. The public `/jobs` page returned HTTP 200 and its metadata described 44,269 Singapore jobs across 33 categories. The rendered page exposed category summaries, including Software Engineering (2,210), Data & Analytics (1,273), and Product Management (1,227); these are category counts, not individual job samples.

An index link labelled “Urgent Jobs” pointed to `/jobs/apply-now-sg-urgent-0`; one request to that route returned 404. One request to the public Software Engineering category page returned 429. No retry or further page request followed the 429. The browser fetch path had separately returned 403 for `/jobs`. Thus this check did not yield verifiable individual job samples, and no copied job descriptions or records are included. The source is a page-level observation only, not live adapter proof.

## Verification and limits

Synthetic tests use no network and cover Greenhouse, Lever, and SmartRecruiters mapping, null handling, timestamps, pagination/request caps, Singapore filtering, malformed bounds, source errors, idempotent upserts, category evidence, and snapshot read/write. Run:

```sh
PYTHONPATH=backend/src python -m pytest backend/tests/test_ingestion.py backend/tests/test_import_jobs.py -q
```

Result before the Lever description follow-up: 32 passed. After adding structured Lever description coverage, the focused ingestion/import suite has 35 passing tests. Docker persistence was verified in the local PostgreSQL database, including an offline snapshot replay with all 70 rows unchanged. The local-to-AWS boundary is the pure Python discovery/config interface and stdlib HTTP client. Lambda packaging, AWS outbound networking/source availability, scheduled discovery, and downstream job processing remain unverified.

## Bounded first collection and import

The CLI in `backend/src/job_hunter/import_jobs.py` uses only `MIGRATION_DATABASE_URL` for its shared-pool write transaction; it does not fall back to the application runtime role. Idempotency uses `(source, source_board, external_id)`, matching the current board-scoped database uniqueness constraint. Existing postings are counted as updated only when listing fields change; a repeated unchanged listing advances `fetched_at` and counts as unchanged. Unseen jobs are never closed. Missing employer, description, location, work mode, and salary data are stored as null. One report is committed in a single database transaction. If a provider fails after another board succeeds, the successful rows can still commit and the provider failure is returned in the result.

Normalized responses are atomically cached at `/data/job-import-snapshots/latest.json` by default. This path is in the local Compose `document_data` volume. Set `JOB_IMPORT_CACHE_FILE` or `--snapshot-out` to change it. `--snapshot-in PATH` imports a cached normalized result without re-fetching source feeds.

The completed bounded import fetched four verified employer feeds between `2026-10-04 16:36:16 UTC` and `16:36:21 UTC`, then committed 70 jobs whose actual normalized location contains Singapore: Stripe Greenhouse 52, Cloudflare Greenhouse 1, Coinbase Greenhouse 7, and Lalamove Lever 10. A read-only database check found 70 rows and 70 distinct `(source, source_board, external_id)` identities across those sources. No cross-source content deduplication was attempted, so this is the distinct source-identity count, not a verified count of unique real-world openings. The imported title taxonomy is a deterministic local inference (`title_keyword_v1`), with the matched title phrase saved as evidence; it was not supplied by the providers. The observed category counts were sales 18, operations 10, engineering 10, people 4, data 4, legal 2, marketing 2, customer success 2, finance 1, and other 17. No product or design roles appeared in these records. Employer ATS coverage is concentrated in technology/fintech and is biased toward employers using these systems. The 70 records are well below the requested 300–500 first-pass / 1,000-job target; they are not comprehensive Singapore coverage.

A documented SmartRecruiters Posting API country=SG query for Grab returned 111 listings, and the first page records had a location city of Singapore. However, the public list response omitted `applyUrl` and `jobAdUrl`; its `ref` points to a JSON detail endpoint. Loading each detail to recover the external application URL would require at least 111 extra requests, so those rows were not imported. No inferred user-facing URL was created. The official API describes the public company postings list, its country/city filters, and pagination in [SmartRecruiters Posting API documentation](https://developers.smartrecruiters.com/docs/endpoints); the company's public careers page identifies the board as Grab.

The first Docker import reported `discovered=70`, `new=70`, `updated=0`, `unchanged=0`, `errors=0`, no source failures, and no truncated feeds. It saved the normalized data to `/data/job-import-snapshots/latest.json` in Compose's persistent `document_data` volume (326,426 bytes). Re-importing that snapshot with no provider requests reported `new=0`, `updated=0`, `unchanged=70`, and `errors=0`; database counts remained 70. This verifies transaction-backed repeat idempotency for this run.

## Lever description completeness follow-up

The Lever normalizer now retains structured content in the provider's documented public response: `descriptionPlain` (or HTML `description` fallback), each labelled `lists[]` section (`text` heading and `content`), and closing `additionalPlain` (or HTML `additional` fallback). HTML headings and paragraphs remain separate lines; list items use readable `• ` lines. Lever sometimes returns a plain-text bullet marker and its item on separate lines, which are rejoined. Empty or absent sections are omitted. This corrects the earlier omission of the separately returned requirements/responsibilities/benefits lists; it does not invent text. See the [Lever Postings API field documentation](https://github.com/lever/postings-api), which describes `lists` as extra named lists and `additionalPlain` as optional closing content.

At `2026-10-04 17:01:29 UTC` (2026-10-05 01:01 Singapore time), a single bounded refresh requested only the first Lalamove Lever page (`page-size=100`, `max-pages=1`, `max-records=100`), using the updated source via a read-only bind mount. The page was marked truncated, so this is not a complete board count. It yielded six explicitly Singapore-located records; all six had descriptions and retained bullets, and the cached descriptions show actual section headings including “What You’ll Do”, “What We Seek”, and “Requirements”. The transactional import reported 6 discovered, 0 new, 6 updated, 0 unchanged, 0 errors, no provider failures, and `lever:lalamove` truncated. Existing unseen rows were left open by design. A read-only database check after import found 10 total Lalamove/Singapore source identities (the six refreshed plus four older rows), nine with descriptions, and six with structured bullets/section breaks. These are source-board identities, not a deduplicated count of real-world openings.

The normalized six-record cache is `/data/job-import-snapshots/lalamove-complete.json` (about 23 KB). The earlier 70-record `/data/job-import-snapshots/latest.json` remained present and unchanged (about 319 KB). After one formatting-only cleanup on the saved six-record snapshot, an offline replay updated those same six descriptions without another provider request. No Greenhouse boards or JustPostedJobs were requested during this follow-up.

The bounded import command is:

```sh
docker compose exec api python -m job_hunter.import_jobs \
  --greenhouse stripe --greenhouse cloudflare --greenhouse coinbase \
  --lever lalamove --location Singapore
```

It filters normalized location fields for the literal word Singapore and also enables the adapter's Singapore-only filtering. Each provider source remains bounded; no JustPostedJobs request was made after its 429 response.
