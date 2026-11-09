# Features against the preliminary report

This page compares the delivered prototype (9 November 2026) with the commitments in the group's preliminary report. It covers Sections 1.2–1.3 (product and business model), 2 (cloud design), 3 (implementation) and 4 (evaluation). For limitations, see [PENDING.md](PENDING.md).

## Feature list

| Feature | What it does |
|---|---|
| Singapore job discovery | Jobs from MyCareersFuture, Adzuna and public Greenhouse and Lever employer boards, Singapore only, pulled twice a day in AWS. Search, pagination, full description, source links, Save and Pass, Posted filter and "Hide expired listings" |
| Duplicate detection | A job found on two sources is linked to one canonical row and shown once, with "Also on …" |
| Profile | Built from an uploaded PDF or Word resume (reviewed before it is applied) or by hand; kept as a structured profile bank and confirmed explicitly; preferences with canonical seniority levels |
| All jobs | Explainable TF-IDF, skill and role ranking with location eligibility and a cold-start fallback |
| For you | Embedding-based list: eligibility filters, role and seniority checks, then vector similarity, fused with the keyword ranking; falls back to All jobs when there is no profile vector |
| Job fit analysis | Requirement extraction, evidence-cited judgement for each requirement, grounding checks and a coverage percentage computed in code, plus suggestions |
| Resume Studio | Manual creation, job-specific copies, build from the profile bank, sections/entries/bullets, autosave with revision checks, undo/redo, two templates, font/size/margins/line spacing/A4 or Letter |
| Resume tailoring | Rule-based reorder with matched and missing skills (free, unlimited); optional AI rewrite that discards any bullet adding new numbers or names |
| Cover letters | AI draft from the confirmed profile and the job, improve an existing letter, or start blank; editor with checks; PDF export |
| PDF lifecycle | Live HTML preview plus the authoritative server PDF; reviewed exports are immutable |
| Documents and tracker | Resumes, uploads and cover letters in one library; application status, dates, notes and the exact attached resume PDF and cover letter |
| Plans and allowance | Free (5) and premium (50) AI jobs per Singapore calendar month; fit analysis, AI tailoring and an AI cover letter for the same job share one slot; premium is a demo plan for now, switched on by an operator |
| Sign-in and isolation | Cognito, invite-only; identity only from verified token claims; PostgreSQL row-level security on per-user tables |
| Addresses | Every page, list and document has its own URL, so refresh, Back and shared links work |

## Preliminary report commitments

| Preliminary report commitment | Delivered |
|---|---|
| Multi-source Singapore jobs, periodic retrieval | Four sources pulled twice a day by an EventBridge schedule (up to 150 new jobs per pull) and on demand by the Pull jobs workflow; expired and long-unseen listings are closed. A SmartRecruiters adapter exists but is not configured in staging |
| Normalise, deduplicate, process each job once | Source identity upsert plus cross-source duplicate links (`ingestion/dedup.py`, migration 0016); measured on 73 scored real cross-source pairs (of 84 labelled): precision 1.00, recall 0.36 (4 of 11 real duplicates found; [eval](../../eval/README.md), B4) |
| Keyword and semantic matching | Both built: All jobs (keyword) and For you (embeddings with keyword fusion) |
| Swipe-based review | Save and Pass buttons instead of gestures |
| AI fit and gap analysis | Built and deployed on the shared LLM worker (SoCLaaS `ornith1.5:35b` since 8 November 2026, `gemma4:26b` before; the course staff confirmed a shared key may be used). Timings and token counts in [eval](../../eval/README.md) (B2) were measured on `gemma4:26b` and not repeated on `ornith1.5:35b` |
| AI-tailored CV and cover letter, editable | Built: AI resume rewrite and AI cover letters on the same worker, with fact checks in code; both stay editable |
| Application tracking | Status, dates, notes and exact attached materials; no reminders or full activity timeline |
| Freemium: 5 assisted jobs a month | Per-Singapore-month allowance, 5 free and 50 premium (`preparation/allowance.py`); premium is a demo plan for now, and a payment gateway is future work |
| Multi-tenant cloud SaaS | Cognito sign-in, verified-claims identity and row-level security in staging; 26 of 27 isolation and token checks passed on 25 October 2026, and one was informational (A6) |
| Fargate API and workers behind an ALB | Replaced by API Gateway and Lambda: no always-on compute and no load balancer to pay for at prototype traffic |
| SQS, EventBridge, S3, RDS, Bedrock | S3, SQS with a dead-letter queue, EventBridge schedule and Aurora Serverless v2 (instead of provisioned RDS, so it can pause when idle). The LLM worker uses the school's SoCLaaS gateway, as Bedrock isn't available on the course AWS account; no language model is hosted on AWS |
| Form prefilling (optional) | Not built; the app does not submit applications |
| System evaluation (Section 4.2) | Responsiveness, step load to 100 users, AI task timing, job-pull pipeline, dedup accuracy and cost model, measured on staging ([eval](../../eval/README.md)) |

Left out on purpose: large self-hosted language models, collaborative editing, a LaTeX editor, a template marketplace, full document history and OCR for scanned resumes.

## Saving, versions and files

The browser debounces edits and sends a PATCH with the expected document revision. PostgreSQL stores the structured content, layout and current revision; a conflicting edit is rejected rather than silently overwritten. This is persistent autosave, not real-time collaboration.

The API renders PDFs from saved data. A reviewed export is stored as an immutable file with an owned export row recording the document, revision and file. A tracker attachment references that export, so editing the resume later does not change the attached PDF. In AWS, uploads and exports live in the private S3 bucket and are transferred with short-lived presigned URLs; locally they live in the Compose `document_data` volume. Lambda's temporary filesystem is never used for permanent storage.
