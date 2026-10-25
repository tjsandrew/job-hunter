# 14 - Cover letters

Status: built 25 Oct 2026, not yet deployed. No Terraform change; it adds migration `0017_cover_letter_packets`, which the normal release applies.

## 1. What the person sees

"My resumes" has two tabs, **Resumes** and **Cover letters** (`/resumes`, `/resumes/letters`, `/resumes/letters/<id>`). A letter is written for one job. There are three ways to start (`LetterStart.tsx`):

| Start | What happens | Cost |
|---|---|---|
| **Write it for me** | The model writes the body from the confirmed profile and the job description. No draft is needed. Needs a confirmed profile and a job description of at least 40 characters. | 1 AI use |
| **Improve a letter I have** | The model rewrites a saved letter, or pasted text (at least 40 characters), for this job. Uses the profile too, if it is confirmed. | 1 AI use |
| **Start blank, or paste my own** | An empty letter with the contact details, date, recipient and greeting filled in. If the person pastes a letter they already have, it goes into the editor as it is, with no model: a first line like "Dear Ms Lim," becomes the greeting, a short last block like "Yours sincerely, Alex" the closing and signature, and blank-line separated blocks the paragraphs (`parse_own_letter`). | free |

The application window in the tracker no longer has its own cover letter text box: the letter is written, pasted or improved in the editor, so it is typed once. Text saved there earlier stays on the application and can still be downloaded from the window.

The "AI use" is the same monthly slot per user and job that fit analysis and AI resume tailoring share (`preparation/allowance.py`, table `ai_tailor_uses`). A second letter, a fit check or a tailor for a job that already has a slot this month is free. A slot is spent only when the letter is usable; a slow, broken or empty answer creates nothing and costs nothing.

The editor (`LetterEditor.tsx`) has the fields on the left and a live A4 / US Letter preview on the right (`LetterPreview.tsx`), a "Check these before you send" box, and the same review step as a resume: **Mark as reviewed**, then **Download PDF** and **Attach reviewed letter** become possible. Starting points: the Cover letters tab, "Prepare cover letter" in an application (tracker), or "Write another version" in the editor.

## 2. How it is stored

A letter is a `documents` row with `kind = "cover_letter"`; no new table. `content` is `{name, email, phone, location, date, recipient, greeting, paragraphs[], closing, signature}`; `layout` and `template` are the resume's. Archived letters use kind `archived_letter` (resumes use `archived`) so a restore returns the right kind.

Editing, review, export, duplicate, archive and restore are the existing document endpoints, widened from "resume" to `WRITTEN_KINDS` in `api/main.py`. `validate_document(..., kind="cover_letter")` checks the letter fields (text limits, up to 12 paragraphs of 4,000 characters). The PDF comes from `letter_pdf_bytes` in `preparation/rendering.py` (fonts shared with the resume renderer through `_fonts`).

Attaching copies nothing: the application stores `cover_letter_export_id` and `cover_letter_title` (migration 0017, composite foreign key to `document_exports` like the resume snapshot), so an attached letter is an immutable PDF of the reviewed revision. `PUT /v1/applications/{job_id}` takes `cover_letter_document_id` and `expected_cover_letter_revision`; the response and the list carry `cover_letter_packet`. The older plain-text `cover_letter_text` box stays.

## 3. API

| Route | Purpose |
|---|---|
| `POST /v1/jobs/{job_id}/cover-letter` | Body `{mode: blank | write | improve, tone, points, source_document_id | source_text, title}`. Returns `{document, notes, ai}` (201). Errors: 402 `AI_LIMIT_REACHED`, 409 `PROFILE_NOT_CONFIRMED`, 422 `JOB_TOO_SHORT` / `LETTER_TOO_SHORT`, 503 `AI_NOT_CONFIGURED` / `AI_UNAVAILABLE` / `AI_TIMEOUT`. |
| `GET /v1/documents?kind=cover_letter` | The person's letters. |
| the document endpoints | patch, review, exports, duplicate, delete, restore as for a resume. |
| `GET /v1/me` | now also `letter_available`. |

## 4. Where the model runs, and how the answer is checked

One short call, so the API waits for it inside the request (25 s; the API Lambda stops at 29 s), like the AI resume rewrite. In AWS it is task `cover_letter` of the shared LLM worker (`llm/tasks.py`, `preparation/cover_letter.py`, through `llm_transport.ask`); locally it runs in the API process. `MODEL_BACKEND=fake` returns a plain letter built from the profile, to try the screens without a model. If letters turn out to need more than 25 s, switch to the start-and-poll pattern of `api/fit_analysis.py`.

Measured on 25 Oct 2026 (model call only, the school gateway, `gemma4:26b`, reasoning effort none, run from a laptop against 4 real postings of 4,000 to 5,700 characters and the demo profile of 21 evidence items): 10 calls (8 written from the profile in three tones, 2 improved from a letter), none failed. Seconds per call: min 6.4, median 8.0, p90 9.0, max 9.4, so all 10 were inside the 25 s wait. Tokens per call: about 1,470 in, 420 out. Letters averaged 161 words. The AWS path (S3 request, worker wake-up, one-second polling) adds time that has not been measured; the demo profile is small (about 900 characters of evidence), and a full profile can send up to about 9,000 characters.

The job text, the profile evidence, the person's notes and the letter being improved are sent as quoted data. Contact details are not sent: they are added in code. The model returns the paragraphs and a list of **claims**, each with the profile evidence ids that support it. `check_letter` then, in code:

- keeps only evidence ids that exist; a claim with one becomes an "ok" note naming the profile item, a claim without becomes a warning ("could not be matched to your profile");
- warns about any number in the letter that appears nowhere in the profile, the job, the notes or the source letter;
- warns about capitalised names that appear nowhere in that material;
- trims and caps the paragraphs (8 of 1,500 characters).

The notes are shown when the letter is created and are not stored. They are warnings, not blocks: the person reviews every letter before it can be attached.

## 5. Tests

`backend/tests/test_cover_letter.py` (prompt, task, checks, PDF) and `backend/tests/integration/test_cover_letter_api.py` (create, limits, failures, edit, review, export, attach, ownership, archive and restore). Frontend: `letters/Letters.test.tsx`, plus the plan and routing tests.

## 6. Not done

- The notes are not saved with the letter.
- No competitor or quality evaluation of the letters yet; cost per letter is unmeasured (assumed close to a fit check, see doc 13).
- The model is the school gateway's `gemma4:26b`; letter quality has not been compared across models.
