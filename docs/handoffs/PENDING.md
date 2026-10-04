# Product status and remaining work

Updated 5 October 2026 (Singapore). This list distinguishes the working local slice from the target preliminary-report design. Component design briefs describe intended behaviour, not proof that every feature exists.

## Working baseline

Docker PostgreSQL, tenant isolation with two local demo identities, profiles and explicit profile confirmation, manual preferences, TF-IDF/skill/role ranking, server search/pagination, live source import, job save/pass, application status/notes/dates, structured resume editing, autosave, two PDF templates, review-gated export, and PDF text extraction for manual review. The first live import has 70 Singapore-location source listings across four employers; synthetic examples do not count.

## Current tracker work

The initial tracker did not store a resume or cover letter. The current change adds a reviewed resume PDF snapshot and a manual cover letter to each application record. The stored PDF identifies the exact exported revision, independent of later edits to the original resume. These are user-maintained records of application materials; the app does not submit applications or verify what an employer received. Final test evidence is recorded in the component handoffs.

## Pending local product work

| Area | Still missing or limited | Next useful step |
|---|---|---|
| Job coverage | 70 source listings, below the 300–500 intermediate / 1,000 Singapore target; employer/category bias remains | Add permitted sources and employers with explicit Singapore coverage; cache responses and stop on rate limits |
| Job lifecycle | Manual imports; no automatic refresh, robust expiry reconciliation, immutable job-content versions or cross-provider opening deduplication | Record source-specific freshness/closure rules and test repeat imports/changed/removed postings |
| Discovery | Full source descriptions and text search are available; comprehensive category/salary/seniority/work-mode filters remain incomplete | Add filters only where normalized source facts support them; preserve unknown values |
| Matching | No real semantic embeddings, hybrid ranking evaluation or evidence-grounded fit analysis | Connect a real model adapter when available and evaluate against labelled examples; do not present keyword scores as match percentages |
| Profile extraction | PDF text only, manual entry of structured facts; no OCR or automatic fact provenance | Add explicit candidate fact review, with source evidence, when model/OCR services are introduced |
| Profile depth | Basic contact/summary/skills form; full structured experience/education/projects profile workflow incomplete | Reuse editor structures with explicit profile confirmation and immutable version references |
| Resume editor | No inline bold/italic/link editing, entry/bullet reordering controls, section-spacing UI, exact paginated live HTML preview or CJK font coverage | Add bounded schema/UI controls and inspect representative PDF pages; server PDF is authoritative |
| Resume history | Current revision and immutable exported PDFs; no complete document revision history or conflict merge interface | Provide recoverable edits/explicit conflict resolution before collaborative use |
| Cover letters | Manual application text is supported by the current tracker change; no reusable standalone cover-letter library, template PDF export or AI generation | Expand document kinds/rendering when implementing preparation workflows |
| Application history | Current status and saved materials; no timeline of every change, reminders, interview events or proof of external submission | Add revisioned activity history and clearly separate draft materials from recorded sent materials |
| AI preparation | No tailored CV/cover-letter generation, grounding checks, provenance, prompt evaluation or allowance enforcement | Implement preparation/task contracts with tests and a real provider; keep unavailable states honest |
| Tasks | No persistent local task runner, retry UI or result idempotency for expensive work | Introduce when AI/background work is connected; use shared task functions for later Lambda workers |
| Data management | No user-facing archive/delete/export-all or retention workflow | Define ownership, recovery and retention before real personal-data pilot |
| Quality evidence | Focused unit, PostgreSQL and manual browser checks exist; comprehensive automated browser/accessibility/visual/load evaluation is pending | Add critical end-to-end scenarios, keyboard/modal checks and representative data-scale tests |

## Deliberately held for cloud POC

Cognito authentication, API Gateway/Lambda packaging, S3 uploads/downloads and lifecycle, EventBridge scheduling, SQS/Lambda workers and DLQ/retry behaviour, RDS setup/backups/connections, Bedrock integration, IAM/secrets, observability, deployment automation and cloud cost/scaling measurements. These need real AWS validation; local tests cannot establish them.

The next milestone is a well-tested local workflow, followed by cloud POC deployment and then a live pilot. Raw LaTeX source editing, collaboration, large template libraries and automatic application submission are not required for this initial POC.

## Additions requested during this review

- Application → prepare a job-specific resume → edit/review → attach the exact PDF revision → download.
- Editable manual cover letter saved with its application, with text download; AI generation and PDF letter templates remain separate follow-ups.
- Full job-detail reading and role-focused excerpts; improve visibility of existing source descriptions without inventing requirements.
- A small local content-based recommender using TF-IDF/cosine and explicit skill/role overlap, with synthetic SQL analyst and ML engineer cases. This is a baseline, not semantic-model acceptance or a calibrated fit percentage.
- Resume font family, size, line spacing and A4/Letter controls, reflected in actual PDF export, plus long-editor footer/scroll fixes.

These additions are implemented. Backend verification: 75 tests; frontend: 15 tests and production build. Desktop browser checks confirmed customization autosave and application preparation → review → PDF attachment with manual cover-letter persistence. Use component handoffs for limits and further evidence.
