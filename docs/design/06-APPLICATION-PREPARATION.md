# 06 — Fit analysis, tailored documents and export

What happens between "this job looks interesting" and "I have a reviewed PDF to send". The stages are fit analysis, resume tailoring, cover letters, and the review-and-export step they all share. The output is editable help grounded in the person's own confirmed experience. Nothing is sent to an employer.

Read the [design README](README.md) and [contracts](CONTRACTS.md) for the shared rules. The resume editor itself is in [09](09-RESUME-EDITOR.md); the profile it draws on is in [10](10-PROFILE-BANK.md).

## The four pieces

| Piece | What it does | Detail |
|---|---|---|
| Fit analysis | Reads one job's real requirements and checks each against the confirmed profile. Shows what the profile evidences, what it does not, and what only the person can judge. | [12](12-FIT-ANALYSIS.md) |
| Resume tailoring | Makes a job-specific copy of a resume. The rule-based version reorders bullets; an optional AI version rewords them. | below |
| Cover letters | Written from the profile, improved from an existing letter, or started blank. | [14](14-COVER-LETTERS.md) |
| Review and export | The person reviews an exact revision, then exports it as an immutable PDF and attaches it to an application. | below |

## Rules that apply to all of it

- **Grounded in the profile.** The model may select, reorder and reword the person's facts. It may not invent numbers, employers, dates or qualifications. Missing evidence is phrased as "not evidenced in your profile", never as "you lack this skill".
- **No hiring probabilities.** There is no chance-of-getting-hired figure and no raw similarity percentage. The one percentage shown is *requirements coverage*, which the application computes itself from checked verdicts and labels as such (see 12).
- **The API never trusts the model.** Every answer is parsed, checked in code and only then stored or shown. A valid evidence id is necessary but not sufficient, so numbers and capitalised names are checked against the source text too. These checks catch invented facts; they do not prove that every paraphrase is faithful, so the person reviews everything.
- **Untrusted text is data.** Job listings and profile text go into prompts as quoted data and cannot change the rules. Fit analysis is tested with a hostile listing (see 12; 14 describes the same handling for letters).
- **A person can always do it by hand.** Manual resume editing, rule-based tailoring and blank letters never use the AI allowance and work without a model.

## Resume tailoring

`POST /v1/documents/{id}/tailor` takes a resume and a job and returns a new copy attached to that job, plus the job's matched and missing skills. The original is never changed.

- **Rule-based (always available, free).** `preparation/tailoring.py` scores each bullet by how many of the job's terms it contains and reorders the bullets inside each entry. It adds nothing and removes nothing, so the copy is safe by construction.
- **AI rewrite (optional).** With `mode: ai`, `preparation/ai_tailoring.py` first builds the rule-based copy, then asks the shared LLM worker (task `tailor`, see [12](12-FIT-ANALYSIS.md), section 12) to reword the bullets for the job. In AWS the API waits up to 25 seconds inside the request, because the API Lambda stops at 29 s and API Gateway at 30 s.
- **Checked in code.** A reworded bullet that adds a number or a capitalised name that was not in the original is discarded and the original bullet kept. A reply with the wrong overall shape is not used, and the rule-based copy is returned instead.
- **Falls back when the model fails.** If the model is slow or unreachable, the person still gets the rule-based copy and the response says why (`ai.status` is `applied`, `unchanged` or `fallback`; a rule-based request returns `off`). Two cases are refused instead of falling back: asking for `mode: ai` when no model is configured returns `503 AI_NOT_CONFIGURED`, and an exhausted monthly allowance returns `402 AI_LIMIT_REACHED`.

Why rule-based first: reordering needs no model, costs nothing and cannot invent anything, so the feature is useful even when the model is down. The rewrite is an optional extra on top.

## Allowance

Fit analysis, AI tailoring and AI cover letters share one slot per user and job per Singapore calendar month (`preparation/allowance.py`). Free users have 5 slots and premium users 50, so the second AI action on the same job in the same month costs nothing.

A slot is spent only when the result is usable: a stored fit analysis, at least one reworded bullet, or a letter with at least one usable paragraph. Letter warnings (a number or name that could not be matched to the profile) are shown beside the letter and are not treated as a failure. Timeouts, schema failures and empty answers cost nothing, and an analysis still running counts against the limit so quick repeated clicks cannot overshoot it. Premium is a demo plan for now, switched on by an operator; a payment gateway is future work (see [13](13-PRICING-AND-PLANS.md)).

## Review and export

Resumes and cover letters are `documents` rows with one revision counter, and they follow the same steps.

1. **Edit.** Every content, template or layout change goes through a revision-checked `PATCH`. Every `PATCH` increases the revision and normally clears the reviewed mark. A rename alone keeps the reviewed mark, because the title is not printed.
2. **Review.** `POST /v1/documents/{id}/review` marks one exact revision as reviewed. If the document changed meanwhile, the request fails with a conflict.
3. **Export.** `POST /v1/documents/{id}/exports` refuses unless the current revision is the reviewed one. It renders the PDF and stores it as an owned, immutable export. Exporting never calls the model.
4. **Download.** `GET /v1/exports/{id}` checks ownership first; another user's id returns 404. In AWS it returns a presigned S3 link that works for 60 seconds.
5. **Attach.** `PUT /v1/applications/{job_id}` can attach a reviewed resume and a reviewed cover letter to an application. Attaching copies nothing: the application points at the immutable export, so editing the document afterwards does not change what was attached. Attaching the same reviewed revision again reuses the existing export.

A working PDF preview (`GET /v1/documents/{id}/preview.pdf`) is available at any time. It is not a review and does not replace an export.

### Rendering

`preparation/rendering.py` draws the PDF from the saved structured content with ReportLab. Content is stored as JSON, separate from the template, and every piece of text is escaped before it reaches the layout engine, so neither the person's text nor a model's reply can inject markup. The layout is deterministic: nothing depends on the clock or on the server's fonts. Bitstream Vera ships with ReportLab, Latin Modern is bundled in `preparation/fonts/`, and Times is a built-in PDF font, so output does not depend on fonts installed on the server.

For why ReportLab was chosen over a browser or LaTeX, and how the editor uses it, see [09](09-RESUME-EDITOR.md#why-structured-json-and-reportlab).

## Where it runs

All of this runs in the API Lambda except the model calls, which go to the shared LLM worker Lambda and then to the school's SoCLaaS gateway. Amazon Bedrock isn't available on the course AWS account, so no language model is hosted on AWS. The path from the API to the worker and back is described in [../architecture/aws-overview.md](../architecture/aws-overview.md). Locally the same task code runs inside the API process.

One worker Lambda handles every AI task; there is not one Lambda per feature. A new AI feature is a new task in `llm/tasks.py` with its own check on the API side.

## Tests

- Backend unit tests: `test_tailoring.py` (rule-based copy), `test_ai_tailoring.py` and `test_tailor_llm.py` (the rewrite and its fact check), `test_allowance.py`, `test_resume_rendering.py` (PDF output), `test_cover_letter.py` and `test_fit_analysis.py` (the latter includes a hostile listing).
- Backend integration tests against PostgreSQL: `integration/test_tenant_isolation.py` (ownership; an application snapshots a reviewed resume and cover letter), `integration/test_resume_build_api.py`, `integration/test_cover_letter_api.py` and `integration/test_fit_analysis_api.py`.
- Frontend: `FitPanel.test.tsx`, `letters/Letters.test.tsx`, `editor.test.ts` and the tests under `apps/web/src/studio/`.
- Model calls in tests use fake model and fake S3 adapters, so CI needs no model key and no AWS credentials.

## Limits

- The checks catch invented numbers, names and evidence ids. They do not catch every wrong judgement or padded wording; the person is the final check.
- The model's answer for a single request must fit in about 25 seconds for tailoring and letters. Fit analysis takes longer, so it is asynchronous and polled instead.
- AI tailoring rewrites bullets only. It does not change the summary, add sections or pick which experience to include; the profile bank's keyword suggestions do that (see 10).
- For what is not built, see [../status/PENDING.md](../status/PENDING.md).
