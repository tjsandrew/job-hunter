# Job Hunter feature list and project alignment

Updated 5 October 2026 (Singapore); rows on fit analysis, tailoring, the free allowance, multi-tenancy and the cloud services refreshed 24 October 2026. Baseline: the group's submitted preliminary report, Sections 1.2–1.3 (product/business model), 2 (cloud design), 3 (implementation) and 4 (evaluation). This is a delivery map, not a claim that all report commitments are finished. The feature table below describes the local application as of 5 October; the Discover tabs (For you, All jobs, Saved, Passed), job fit analysis, profile import and the profile bank have been added since (see [PENDING.md](PENDING.md)).

## Local feature list

| Feature | Scope |
|---|---|
| Singapore job discovery | Bounded public employer feeds, normalized source/location/provenance fields and idempotent imports; 70 live source listings currently |
| Job reading and shortlisting | Search/pagination, full source description view, role-focused excerpt, source links, Save/Pass |
| Personal profile | Editable contact, headline, summary, skills and preferences; explicit save and confirmation; PDF text extraction as a review candidate |
| Local recommendation baseline | Explainable content similarity and explicit skills/role relevance, location eligibility, cold-start fallback; no large-model runtime needed. Shown as "All jobs" and used as the fallback for "For you" |
| Semantic "For you" recommendations | Embedding-based list: eligibility filters, then role and seniority checks, then similarity ranking; profile embedded on confirm and preferences save, jobs embedded by `make backfill`; falls back to the keyword list. See [13-embedding-preparation.md](13-embedding-preparation.md) |
| Synthetic demo cases | One populated fictional Alex Tan profile and complete application resume; no sample chooser. QA resumes are archived out of the library. |
| Resume Studio | Manual creation, job-specific copies, sections/entries/bullets, autosave, revision checks, undo/redo, two templates |
| Resume tailoring | Rule-based: bullets reordered to match the job, with matched/missing skills (free, unlimited). AI: an optional rewrite through the `MODEL_BACKEND` model (hosted SoCLaaS or local Ollama) or, in AWS, the shared LLM worker, limited per Singapore month (5 free, 50 premium) with one use per job shared with fit analysis; reworded bullets that add numbers or names are discarded, and any model failure falls back to the rule-based result |
| Resume customization | Font family and size, margins, line spacing, A4/Letter; honored by server PDF output |
| PDF lifecycle | Approximate live HTML preview plus authoritative server PDF preview; review current revision; export/download immutable PDF |
| Application preparation | Open an application, create/copy a resume for that job, edit/review it, attach its exact exported revision, then return to the application |
| Application materials | Saved resume PDF title/revision and download; manual cover letter and text download; omission preserves existing attachments |
| Tracking | Status, applied date, notes and application materials; records are maintained by the user, not proof of external submission |
| Local persistence | PostgreSQL for structured content/current revisions; Docker document volume for uploaded and exported PDFs; files remain owned and private |
| Test evidence | Unit/component tests, PostgreSQL RLS and migrations, snapshot integrity checks, browser layout/workflow checks; latest counts in component handoffs |

Implemented and tested locally: job detail, ranking, application preparation/materials and font controls. Backend: 75 passing tests; frontend: 15 passing tests and production build (counts on 5 October; by 24 October roughly 836 backend and 279 frontend tests). See component handoffs for validation limits.

## Requirements comparison and what to leave out

| Preliminary report commitment | Current gap | Decision |
|---|---|---|
| Multi-source Singapore jobs, periodic retrieval | Greenhouse, Lever, SmartRecruiters and MyCareersFuture adapters work; an Adzuna adapter is written and needs a free key (snippet-only descriptions). Cloud pulls run in staging: the "Pull jobs" workflow on demand and an EventBridge schedule twice a day (100 new jobs per run, newest first). Expired and long-unseen listings close; Discover's Posted filter defaults to the last 14 days | Keep broadening permitted coverage and add refresh/expiry before a live pilot. MCF/Adzuna are examples, not a reason to block on an unverified API |
| Normalize/deduplicate and process each job once | Source identity upsert exists. Cross-source dedup is built (`ingestion/dedup.py`, migration 0016: duplicates are linked to a canonical row, shown once with "Also on"; 16-pair labelled set, no wrong links); content versions and richer skills/seniority extraction incomplete | Keep as core work; test against labelled duplicate fixtures, not just same-ID re-import |
| Keyword + semantic matching | Keyword baseline and a local-embedding semantic list both run locally; semantic quality is evaluated only on assistant-labelled data, so no accuracy claim yet | Build/evaluate baseline now. Keep semantic matching for a later real embedding adapter; do not label TF-IDF as semantic |
| Swipe-based review | Save/Pass buttons support the decision flow | Keep buttons for POC; gesture animation can be left out unless user tests identify a need |
| AI fit/gap analysis | Implemented and deployed (SoCLaaS `gemma4:26b`): endpoints, web panel, grounding checks, coverage in code, monthly allowance. The worker Lambda runs in staging (the course staff confirmed a shared key may be used); it is verified by a direct S3 test, but not yet through the web app because staging has no jobs | Load jobs into staging and test end to end; keep numbers (latency, tokens, cost) for the report. See design brief 12 |
| AI-tailored CV and cover letter, editable | Manual editing/materials work. An optional AI resume rewrite exists (fake/Ollama model only, so not in the cloud); AI cover-letter generation is not implemented | Decide whether to build cover-letter generation. Manual cover letters and job-specific copies cover the flow meanwhile |
| Application tracking | Status and materials; full activity history/reminders absent | Keep core tracking and exact materials; defer calendar/reminder integrations and exhaustive timeline |
| Freemium 5 distinct assisted jobs/month | Implemented as a per-Singapore-month allowance, 5 distinct jobs for free and 50 for premium, shared by fit analysis and AI tailoring (`preparation/allowance.py`). No payments; the premium price is undecided | Leave paid checkout/billing out of the POC, use test tiers |
| Multi-tenant cloud SaaS | Cognito sign-in, verified-claims identity and PostgreSQL RLS are deployed in staging. A two-account browser acceptance run is still to do | Run the acceptance checks in [FINAL-PENDING-NOTES.md](FINAL-PENDING-NOTES.md) |
| Fargate API/workers + ALB | Current local FastAPI; simplified cloud plan uses API Gateway/Lambda | Leave Fargate/ALB out by default; revisit only for measured workload/runtime limitations. Preserve shared service code |
| SQS/EventBridge/S3/RDS/Bedrock | Deployed in staging: S3, SQS with a dead-letter queue and the embedding Lambda, Aurora Serverless v2 (not provisioned RDS). The job-pull Lambdas (discovery outside the VPC, import inside) with an EventBridge schedule twice a day. Bedrock is blocked by the university account policy, so the LLM worker uses the SoCLaaS gateway | Apply the job pull (docs/deployment/JOB-PULL-ROLLOUT.md) so staging has jobs. Leave LocalStack, local Cognito/S3/queue replicas out |
| Form prefilling (Section 3, optional) | Not implemented | Leave out of initial POC; avoid automatic job submission or browser-automation integrations |
| User evaluation (Section 4.1) | No participant study yet | Keep: profile, discovery, review, fit guidance and tailored-letter tasks, relevance/usefulness ratings, effort/time and feedback |
| System evaluation (Section 4.2) | Focused correctness tests; no measured latency/load/cost report | Keep baseline profiling and 1/10/50/100-user load evaluation, pipeline/dedup metrics and cloud-vs-fixed-capacity comparison. Do not invent measurements |

Also leave out for now: large local language models, collaborative resume editing, a full LaTeX compiler/editor, large template marketplace, exhaustive document history and OCR for scanned resumes. These are not prerequisites to validating the current core workflow. CJK font support matters for a wider Singapore pilot and should be added before promising multilingual output.

## Saving, versions and filesystem

The browser debounces edits and sends a PATCH with the expected document revision. PostgreSQL stores structured content, layout and the current revision; conflicts are rejected rather than silently overwriting another edit. This is persistent autosave, not collaborative real-time editing or a full historical revision store.

The API renders PDFs from saved data. Preview bytes are returned to the browser. Reviewed exports are written into the Compose `document_data` volume under `/data/exports`, and owned export rows record the document/revision/file reference. A tracker attachment references that immutable export, so editing the source document later does not rewrite the attached PDF. Uploaded PDFs are captured separately under `/data/uploads`. Docker restarts preserve these named volumes; deleting volumes deletes the data. Git backs up code, not uploaded files or database contents.

For AWS, PostgreSQL maps to RDS and document storage maps to S3. Use S3 uploads/presigned download transport and keep the same ownership/revision rules; do not use Lambda's temporary filesystem as permanent storage.
