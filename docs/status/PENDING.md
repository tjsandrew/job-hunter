# Known limitations and future work

What Job Hunter does not do yet, or does only partly, as of 9 November 2026. For what is built, see the [README](../../README.md) and [FEATURES.md](FEATURES.md).

## Authentication

Sign-in uses Amazon Cognito (authorisation code with PKCE, admin-created accounts only, no public sign-up). The deployed API takes the user only from the claims that API Gateway's JWT authorizer verified. The local Alice/Casey `X-Dev-User` header works only with `AUTH_MODE=local`, and the API refuses to start in that mode unless `APP_ENV` is `local` or `test`. On 25 October 2026, 26 of 27 isolation and token checks against the staging API passed and one was informational (`eval/results/a6-*`).

Open points:

- No full browser acceptance run with two real accounts (cross-user denial, expiry, logout), including a check that all private UI state clears on logout or account switch.
- A revoked session's access token stays valid until it expires (at most 60 minutes).
- Cognito MFA is not enabled (Lite tier).
- The display name in the cloud is always "Job seeker".
- Invitations expire after seven days, so test participants need accounts created shortly before they test.

## Product

| Area | Limitation | Possible next step |
|---|---|---|
| Job coverage | Four sources (MyCareersFuture, Adzuna, Greenhouse and Lever boards), Singapore only; coverage is biased towards the employers and searches configured | Add permitted sources and employers with explicit Singapore coverage |
| Job lifecycle | Listings that expire or go unseen for 21 days are closed, but there are no per-source closure rules and no versioned job content | Record source-specific freshness rules |
| Adzuna descriptions | Adzuna returns only a snippet, so jobs found only there may be too short for fit analysis | Duplicate detection already prefers the employer's own posting when a job is on both |
| Duplicate detection | Recall is 0.36: 7 of 11 real duplicates were missed because the employer and title keys differ (for example "Google LLC" and "GOOGLE ASIA PACIFIC PTE. LTD."). Precision is 1.00 and no jobs were wrongly merged (`eval/results/b4-dedup-20261026/summary.md`) | Match on normalised employer names plus description similarity |
| Discovery filters | Text search, posting date, expired, salary, seniority and work-mode filters exist. There is no category filter, and only some sources state the work mode, so that filter misses jobs | Add a category filter only where normalised source facts support it |
| Matching | No independent relevance evaluation of "For you" or All jobs was done; similarity is computed in memory over a per-instance copy of the job vectors, not with a pgvector index | Label a job set to measure relevance; move ranking into SQL with an index if the job pool grows large |
| Fit analysis | No labelled accuracy set; the checks catch invented evidence and numbers, not every wrong judgement | Build a labelled set of postings and profiles |
| Profile extraction | Heuristic parsing by default. A local Ollama model adapter exists; only the Bedrock path is a stub, because Bedrock isn't available on the course AWS account. There is no OCR, so scanned PDFs are rejected | Add OCR if scanned resumes matter |
| Resume editor | No inline bold/italic/link editing, drag-and-drop reordering (up and down buttons exist), exact paginated live preview or CJK (Chinese, Japanese and Korean) fonts | Add bounded controls; the server PDF stays authoritative |
| Document history | Current revision plus immutable exported PDFs; no full revision history or conflict merge | Recoverable edits before any collaborative use |
| Application history | Current status and attached materials; no timeline, reminders or interview events; the app does not submit applications | Add an activity history |
| Payments | Premium is a demo plan for now: an operator switches an account to it | Add a payment gateway (checkout, subscriptions, receipts) |
| Data management | Profile export and deletion exist; export-all, retention rules and durable file-cleanup retries do not | Define a data lifecycle before a real pilot |
| Testing | Unit, PostgreSQL, Terraform and acceptance tests plus load tests exist; no automated end-to-end browser, accessibility or visual tests | Add end-to-end scenarios for the main journeys |

## Cloud

Not built: CloudFront or WAF (a web application firewall) in front of the site, and a Content-Security-Policy header. Amplify already sends Strict-Transport-Security, X-Frame-Options, X-Content-Type-Options and Referrer-Policy (`infra/aws/main.tf`). The AI features use the school's SoCLaaS gateway, as Amazon Bedrock isn't available on the course AWS account. Measured latency, load, pipeline, dedup and cost results are in [eval/](../../eval/README.md).

Out of scope for this prototype: swipe gestures (Save and Pass are buttons), public sign-up, raw LaTeX editing, collaborative editing, large template libraries and automatic application submission.
