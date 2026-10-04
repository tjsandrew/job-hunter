# Local POC checkpoint

Updated 5 October 2026 (Singapore).

## Implemented

- Private repository: https://github.com/tjsandrew/job-hunter. Source, tests and notes belong here; private files and data volumes are excluded.
- Docker Compose: PostgreSQL/pgvector, migrations/seed, API running as a nonowner role with tenant RLS, and React frontend. Host ports bind to localhost.
- Profiles/preferences, keyword recommendations with server search/pagination, save/pass and application tracking.
- Manual resume editor: structured sections, two templates, autosave, undo/redo, revision review, server PDF preview/export. PDF uploads expose extracted text as a candidate for manual review.
- Live ingestion/import: 70 Singapore-location source identities across Stripe (52), Cloudflare (1), Coinbase (7), Lalamove (10). Four employers, two providers (Greenhouse/Lever). This is below the 300–500 intermediate / 1,000 target and excludes synthetic seeds. No comprehensive category coverage or cross-provider opening deduplication claim.
- Local normalized snapshot in the document volume; offline replay created no duplicates. JustPostedJobs collection stopped after 429.
- A 90-minute heartbeat was verified ACTIVE earlier in this session. It can revisit unfinished work when execution is available; it does not bypass quota or keep the machine awake.

## Verification

Backend agent ran 46 passing tests against current source and real PostgreSQL, including direct nonowner SQL RLS, revision/ownership, PDF upload/extraction and multipage PDF rendering. A separate empty database applied migrations 0001–0008 and seed successfully. Parent HTTP smoke passed upload/extraction, immutable uploads, owner isolation, review gating, PDF generation and downloads. Frontend agent ran 10 passing tests and a successful production build. See component handoffs for exact checks.

## Next bounded work

1. Broaden permitted Singapore job coverage across categories, reusing snapshots and respecting provider limits. Do not collect further from a rate-limited source in the same pass. Label observed counts and gaps.
2. Add job detail, stronger category filtering and explicit stale/closed-job reconciliation. Confirm provider expiry rules before changing statuses.
3. Extract preparation/rendering services from the API module as that component grows; add an embedded CJK font and visual PDF regression coverage. Current font coverage is limited to Latin text.
4. Add an actual AI/embedding provider, semantic evaluation and quota accounting only in their approved stage. They are unavailable in this local slice, not mocked as working AI.
5. Cloud POC: API Gateway/Lambda, EventBridge discovery, SQS/Lambda workers, S3, Cognito, RDS and Bedrock per the design notes. Validate cloud IAM, retries, concurrency and deployment there. No AWS infrastructure has been provisioned by this local implementation.

See component handoffs for contracts and limits. The broader preliminary-report design remains a roadmap; this runnable slice does not implement every feature.

## Parent runtime check

Final rebuilt API health and HTTP smoke passed. Browser verification confirmed live employer search (Lalamove returned 10 source listings before review), saving Accountant into Alice's tracker, opening the persisted resume editor, and the server PDF preview dialog. Desktop job cards received a final readability adjustment: larger description text and a three-line preview with the source link for full details. The local demo database retains synthetic documents created by tests; they are not personal resumes. PDF bytes/download endpoints were verified; a browser file-save event was not independently verified because the in-app browser download-event wait timed out earlier.
