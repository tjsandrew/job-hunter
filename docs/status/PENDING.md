# Product status and remaining work

Updated 24 October 2026 (Singapore). The authentication, AI, matching, profile-extraction and cloud rows below were refreshed against the code on that date; the remaining rows keep their 5 October wording and still need a final audit. This list distinguishes what is built from the target preliminary-report design. Component design briefs describe intended behaviour, not proof that every feature exists.

## Authentication: implemented, with acceptance checks still open

Sign-in uses Amazon Cognito (authorization code with PKCE, admin-created accounts only, no public sign-up). The deployed API takes the user only from the claims that API Gateway's JWT authorizer verified (issuer, client, access-token type, expiry, scope). The Alice/Casey `X-Dev-User` header works only with `AUTH_MODE=local`, and the API refuses to start with that mode unless `APP_ENV` is `local` or `test`. Ownership checks and PostgreSQL row-level security are tested.

Still open: a browser acceptance run with two real accounts (cross-user denial, expiry, logout), Cognito MFA (not enabled), and the cloud display name, which is always "Job seeker". See [final pending-work notes](FINAL-PENDING-NOTES.md) for the checklist.

## Working baseline

Docker PostgreSQL, tenant isolation, Cognito sign-in in the cloud and two local demo identities, profiles with PDF/Word import and review, a structured profile bank, explicit profile confirmation, manual preferences, TF-IDF/skill/role ranking, a semantic "For you" list, job fit analysis, server search/pagination, live source import, job save/pass, application status/notes/dates, structured resume editing, autosave, two PDF templates, review-gated export, rule-based tailoring and an optional AI rewrite. The first live import has 70 Singapore-location source listings across four employers; synthetic examples do not count. A staging deployment is live on AWS but holds no job listings.

## Current tracker work

The initial tracker did not store a resume or cover letter. The current change adds a reviewed resume PDF snapshot and a manual cover letter to each application record. The stored PDF identifies the exact exported revision, independent of later edits to the original resume. These are user-maintained records of application materials; the app does not submit applications or verify what an employer received. Final test evidence is recorded in the component handoffs.

## Pending local product work

| Area | Still missing or limited | Next useful step |
|---|---|---|
| Job coverage | 70 source listings, below the 300–500 intermediate / 1,000 Singapore target; employer/category bias remains | Add permitted sources and employers with explicit Singapore coverage; cache responses and stop on rate limits |
| Job lifecycle | Manual imports; no automatic refresh, robust expiry reconciliation, immutable job-content versions or cross-provider opening deduplication | Record source-specific freshness/closure rules and test repeat imports/changed/removed postings |
| Discovery | Full source descriptions and text search are available; comprehensive category/salary/seniority/work-mode filters remain incomplete | Add filters only where normalized source facts support them; preserve unknown values |
| Matching | Semantic "For you" exists (embedding model, keyword fusion, embedding worker live in staging); still pending: independent relevance labels on a larger job set, job-vector refresh from ingestion, and a decision on caching or a pgvector query (recommendations are recomputed per request). Evidence-grounded fit analysis is built (see AI preparation) | Evaluate against labelled examples; do not present keyword scores or raw similarity as match percentages |
| Profile extraction | PDF and Word import with a review step before anything is applied (heuristic parsing by default; the model path is a placeholder); no OCR, so scanned PDFs are rejected | Add OCR if scanned resumes matter |
| Profile depth | Profile bank (structured items, points/versions, skills, reviewed snapshots, explicit saves) and resume build from the bank (`/v1/documents/from-bank`) are implemented | Check the profile-bank handoffs for remaining limits; see [step 2 handoff](10-profile-bank.md#step-2--profile-page-and-step-1-follow-ups) |
| Resume editor | No inline bold/italic/link editing, entry/bullet reordering controls, section-spacing UI, exact paginated live HTML preview or CJK font coverage | Add bounded schema/UI controls and inspect representative PDF pages; server PDF is authoritative |
| Resume history | Current revision and immutable exported PDFs; no complete document revision history or conflict merge interface | Provide recoverable edits/explicit conflict resolution before collaborative use |
| Cover letters | Manual application text is supported by the current tracker change; no reusable standalone cover-letter library, template PDF export or AI generation | Expand document kinds/rendering when implementing preparation workflows |
| Application history | Current status and saved materials; no timeline of every change, reminders, interview events or proof of external submission | Add revisioned activity history and clearly separate draft materials from recorded sent materials |
| AI preparation | Done: job fit analysis (requirement extraction, evidence-cited judgement, grounding checks, coverage in code, suggestions) and a monthly allowance (5 free / 50 premium, one use per job shared with tailoring); optional AI resume rewrite with a fact-safety check. Missing: AI cover-letter generation; the rewrite supports only fake and Ollama models, so it cannot run in the cloud; no labelled accuracy set for fit analysis | Decide whether tailoring moves onto the shared worker; keep unavailable states honest |
| Tasks | Fit analysis runs as a background task locally and as an S3 request/result file handled by a worker Lambda in AWS, polled by the web app. There is no general task table, retry UI or outbox | Add a generic task layer only if more AI features need it |
| Data management | Profile item archive/Undo, profile JSON export and profile-data deletion are implemented; export-all, broader retention/recovery and durable file-cleanup retries remain pending | Define lifecycle across uploads, profile versions, documents, applications and backups before a real personal-data pilot |
| Quality evidence | Focused unit, PostgreSQL and manual browser checks exist; comprehensive automated browser/accessibility/visual/load evaluation is pending | Add critical end-to-end scenarios, keyboard/modal checks and representative data-scale tests |

## Cloud status

Deployed in staging (Terraform, GitHub Actions release): Cognito, API Gateway and the API Lambda, Aurora Serverless v2 with row-level security, private S3 uploads and downloads, the S3 → SQS → Lambda embedding worker, the fit-analysis worker Lambda, IAM through GitHub OIDC, budget and activity alarms, and pause/resume of the backend. See [deployment/README.md](../deployment/README.md).

Not built or not decided: scheduled job discovery (EventBridge and an ingestion Lambda; the VPC has no internet egress and no NAT gateway), loading jobs into staging, Bedrock (blocked by the university account policy), CloudFront/WAF, security headers such as CSP and HSTS, and measured latency, load and cost numbers. Local tests cannot establish AWS behaviour.

Raw LaTeX source editing, collaboration, large template libraries and automatic application submission are not required for this POC.

## Additions requested during this review

- Application → prepare a job-specific resume → edit/review → attach the exact PDF revision → download.
- Editable manual cover letter saved with its application, with text download; AI generation and PDF letter templates remain separate follow-ups.
- Full job-detail reading and role-focused excerpts; improve visibility of existing source descriptions without inventing requirements.
- A small local content-based recommender using TF-IDF/cosine and explicit skill/role overlap, with synthetic SQL analyst and ML engineer cases. This is a baseline, not semantic-model acceptance or a calibrated fit percentage.
- Resume font family, size, line spacing and A4/Letter controls, reflected in actual PDF export, plus long-editor footer/scroll fixes.

These additions are implemented. Backend verification when they were added (5 October): 75 tests; frontend: 15 tests and production build. By 24 October the suites had grown to roughly 836 backend and 279 frontend tests. Desktop browser checks confirmed customization autosave and application preparation → review → PDF attachment with manual cover-letter persistence. Use component handoffs for limits and further evidence.
