# Local POC checkpoint

Updated 5 October 2026 (Singapore).

> **Historical checkpoint.** This page records the local proof of concept as it was on 5 October. Since then the profile bank and import, Cognito sign-in, the staging deployment on AWS, semantic "For you", job fit analysis and a monthly AI allowance were added. For the current state read [PENDING.md](PENDING.md), [FEATURES.md](FEATURES.md) and the [deployment guide](../deployment/README.md). Where the lines below say no AWS infrastructure exists, that was true on 5 October only.

## Implemented

- Private repository: https://github.com/tjsandrew/job-hunter. Source, tests and notes belong here; private files and data volumes are excluded.
- Docker Compose: PostgreSQL/pgvector, migrations/seed, API running as a nonowner role with tenant RLS, and React frontend. Host ports bind to localhost.
- Profiles/preferences, TF-IDF/skill/role recommendations with server search/pagination, a semantic "For you" list (embedder service, stored vectors, role/seniority checks) with the keyword list as fallback, save/pass and application tracking.
- Manual resume editor: structured sections, two templates, autosave, undo/redo, revision review, server PDF preview/export. PDF uploads expose extracted text as a candidate for manual review.
- Live ingestion/import: 70 Singapore-location source identities across Stripe (52), Cloudflare (1), Coinbase (7), Lalamove (10). Four employers, two providers (Greenhouse/Lever). This is below the 300–500 intermediate / 1,000 target and excludes synthetic seeds. No comprehensive category coverage or cross-provider opening deduplication claim.
- 24 October 2026: MyCareersFuture and Adzuna adapters merged or written, cross-source dedup (migration 0016) and the cloud job pull (Discovery and Import Lambdas, Pull jobs workflow) built; none of it is applied to staging yet (see docs/deployment/JOB-PULL-ROLLOUT.md).
- Local normalized snapshot in the document volume; offline replay created no duplicates. JustPostedJobs collection stopped after 429.

## Verification

Backend checks: 75 passing tests against current source and real PostgreSQL, including direct nonowner SQL RLS, revision/ownership, PDF upload/extraction and multipage PDF rendering. A separate empty database applied migrations 0001–0009 and seed successfully. HTTP smoke passed upload/extraction, immutable uploads, owner isolation, review gating, PDF generation and downloads. Frontend checks: 15 passing tests and a successful production build. See component handoffs for exact checks.

## Next bounded work

1. Broaden permitted Singapore job coverage across categories, reusing snapshots and respecting provider limits. Do not collect further from a rate-limited source in the same pass. Label observed counts and gaps.
2. Add stronger category filtering and explicit stale/closed-job reconciliation. Confirm provider expiry rules before changing statuses.
3. Rendering is extracted into preparation/rendering.py; add an embedded CJK font and visual PDF regression coverage. Current font coverage is limited to Latin text.
4. Semantic evaluation on a larger, independently labelled job set, the Bedrock embedding backend (untested), and AI generation and quota accounting, only in their approved stage. They are unavailable in this local slice, not mocked as working AI.
5. Cloud POC: API Gateway/Lambda, EventBridge discovery, SQS/Lambda workers, S3, Cognito, RDS and Bedrock per the design notes. Validate cloud IAM, retries, concurrency and deployment there. No AWS infrastructure has been provisioned by this local implementation.

See component handoffs for contracts and limits. The broader preliminary-report design remains a roadmap; this runnable slice does not implement every feature.

## Runtime check

Final rebuilt API health and HTTP smoke passed. Browser verification confirmed live employer search (Lalamove returned 10 source listings before review), saving Accountant into Alice's tracker, opening the persisted resume editor, and the server PDF preview dialog. Desktop job cards received a final readability adjustment: larger description text and a three-line preview with the source link for full details. The local demo database retains synthetic documents created by tests; they are not personal resumes. PDF bytes/download endpoints were verified; a browser file-save event was not independently verified because the in-app browser download-event wait timed out earlier.

## Latest local feature pass

Application packets now retain immutable reviewed resume PDFs and manual cover-letter text. Browser QA exercised the fictional Backend Engineer role: prepare an ML demo copy, review revision 1, attach it and save a clearly labelled fictional letter. Font family/size, line spacing, margins and A4/Letter are persisted and rendered by the server. Long-editor footer overlap is fixed. Fictional SQL analyst and ML engineer samples are available via the seed script.

Lever normalization now includes responsibilities/requirements lists and closing text. One bounded Lalamove refresh updated six existing Singapore records; the four unseen records were retained, not assumed closed. Overall coverage remains 70 source identities. See FEATURES.md and PENDING.md for the preliminary-report comparison and remaining cloud/AI/evaluation work.

Final rebuilt HTTP smoke passed. Browser checks at 1440×1000 and 390×844 confirmed saved typography settings and no horizontal overflow (scrollWidth equals viewport width). The mobile header was corrected after initial overflow was observed. The SQL demo uses sans serif, 12pt, 1.4 spacing and Letter as a customization example.
