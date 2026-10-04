# Job Hunter feature list and project alignment

Updated 5 October 2026 (Singapore). Baseline: the group's `Preliminary.pdf`, Sections 1.2–1.3 (product/business model), 2 (cloud design), 3 (implementation) and 4 (evaluation). This is a delivery map, not a claim that all report commitments are finished.

## Local feature list

| Feature | Scope |
|---|---|
| Singapore job discovery | Bounded public employer feeds, normalized source/location/provenance fields and idempotent imports; 70 live source listings currently |
| Job reading and shortlisting | Search/pagination, full source description view, role-focused excerpt, source links, Save/Pass |
| Personal profile | Editable contact, headline, summary, skills and preferences; explicit save and confirmation; PDF text extraction as a review candidate |
| Local recommendation baseline | Explainable content similarity and explicit skills/role relevance, location eligibility, cold-start fallback; no large-model runtime needed |
| Synthetic demo cases | Clearly fictional SQL analyst and ML engineer profiles/resumes for testing; never claim these are real applicants |
| Resume Studio | Manual creation, job-specific copies, sections/entries/bullets, autosave, revision checks, undo/redo, two templates |
| Resume customization | Font family and size, margins, line spacing, A4/Letter; honored by server PDF output |
| PDF lifecycle | Approximate live HTML preview plus authoritative server PDF preview; review current revision; export/download immutable PDF |
| Application preparation | Open an application, create/copy a resume for that job, edit/review it, attach its exact exported revision, then return to the application |
| Application materials | Saved resume PDF title/revision and download; manual cover letter and text download; omission preserves existing attachments |
| Tracking | Status, applied date, notes and application materials; records are maintained by the user, not proof of external submission |
| Local persistence | PostgreSQL for structured content/current revisions; Docker document volume for uploaded and exported PDFs; files remain owned and private |
| Test evidence | Unit/component tests, PostgreSQL RLS and migrations, snapshot integrity checks, browser layout/workflow checks; latest counts in component handoffs |

Implemented and tested locally: job detail, ranking, application preparation/materials and font controls. Backend: 75 passing tests; frontend: 15 passing tests and production build. See component handoffs for validation limits.

## Requirements comparison and what to leave out

| Preliminary report commitment | Current gap | Decision |
|---|---|---|
| Multi-source Singapore jobs, periodic retrieval | Two ATS providers work, but narrow employer coverage; no scheduled refresh or closure rules | Keep broadening permitted coverage and add refresh/expiry before a live pilot. MCF/Adzuna are examples, not a reason to block on an unverified API |
| Normalize/deduplicate and process each job once | Source identity upsert exists; cross-provider dedup, content versions and richer skills/seniority extraction incomplete | Keep as core work; test against labelled duplicate fixtures, not just same-ID re-import |
| Keyword + semantic matching | Lightweight lexical/content baseline can run locally; no real semantic embeddings/evaluation yet | Build/evaluate baseline now. Keep semantic matching for a later real embedding adapter; do not label TF-IDF as semantic |
| Swipe-based review | Save/Pass buttons support the decision flow | Keep buttons for POC; gesture animation can be left out unless user tests identify a need |
| Deeper AI fit/gap analysis | Not implemented | Keep on final product roadmap; defer model integration until provider access and grounding/evaluation are ready |
| AI-tailored CV and cover letter, editable | Manual editing/materials work; generation/provenance not implemented | Keep generation as required later. Manual cover letters and job-specific copies let us test the flow locally now |
| Application tracking | Status and materials; full activity history/reminders absent | Keep core tracking and exact materials; defer calendar/reminder integrations and exhaustive timeline |
| Freemium 5 distinct assisted jobs/month | AI allowance disabled | Add transactional quota accounting with AI tasks; leave paid checkout/billing out of the initial POC, use test tiers |
| Multi-tenant cloud SaaS | Local demo identities and real PostgreSQL RLS only | Cannot omit deployed authentication/isolation from final cloud evaluation; defer Cognito provisioning to cloud POC |
| Fargate API/workers + ALB | Current local FastAPI; simplified cloud plan uses API Gateway/Lambda | Leave Fargate/ALB out by default; revisit only for measured workload/runtime limitations. Preserve shared service code |
| SQS/EventBridge/S3/RDS/Bedrock | Not provisioned | Implement native cloud services in cloud POC. Leave LocalStack, local Cognito/S3/queue replicas out |
| Form prefilling (Section 3, optional) | Not implemented | Leave out of initial POC; avoid automatic job submission or browser-automation integrations |
| User evaluation (Section 4.1) | No participant study yet | Keep: profile, discovery, review, fit guidance and tailored-letter tasks, relevance/usefulness ratings, effort/time and feedback |
| System evaluation (Section 4.2) | Focused correctness tests; no measured latency/load/cost report | Keep baseline profiling and 1/10/50/100-user load evaluation, pipeline/dedup metrics and cloud-vs-fixed-capacity comparison. Do not invent measurements |

Also leave out for now: large local language models, collaborative resume editing, a full LaTeX compiler/editor, large template marketplace, exhaustive document history and OCR for scanned resumes. These are not prerequisites to validating the current core workflow. CJK font support matters for a wider Singapore pilot and should be added before promising multilingual output.

## Saving, versions and filesystem

The browser debounces edits and sends a PATCH with the expected document revision. PostgreSQL stores structured content, layout and the current revision; conflicts are rejected rather than silently overwriting another edit. This is persistent autosave, not collaborative real-time editing or a full historical revision store.

The API renders PDFs from saved data. Preview bytes are returned to the browser. Reviewed exports are written into the Compose `document_data` volume under `/data/exports`, and owned export rows record the document/revision/file reference. A tracker attachment references that immutable export, so editing the source document later does not rewrite the attached PDF. Uploaded PDFs are captured separately under `/data/uploads`. Docker restarts preserve these named volumes; deleting volumes deletes the data. Git backs up code, not uploaded files or database contents.

For AWS, PostgreSQL maps to RDS and document storage maps to S3. Use S3 uploads/presigned download transport and keep the same ownership/revision rules; do not use Lambda's temporary filesystem as permanent storage.
