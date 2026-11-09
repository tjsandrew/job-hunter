# 03 — Profiles and resume processing

How a resume becomes a confirmed profile that the rest of the app can trust. Related briefs: [10 Profile bank](10-PROFILE-BANK.md) (where the facts are stored), [05 Recommendations](05-RECOMMENDATIONS.md) and [11 Embedding worker](11-EMBEDDING-WORKER.md) (how a confirmed profile becomes a vector). Shared names and paths are in [CONTRACTS](CONTRACTS.md); the AWS picture is in [what runs where](../architecture/aws-overview.md).

## The user's journey

1. The user uploads a resume (PDF or Word), pastes text, or imports an existing Resume Studio resume or a JSON Resume file.
2. The app reads it and shows a **review screen** of proposed facts: basics, experience, projects, education, skills and bullet points.
3. The user accepts, edits or skips each one. **Nothing is saved to the profile until they choose Apply.**
4. The user **confirms** the profile. Confirmation freezes a version that the For you list, fit analysis and cover letters use. All jobs ranks with the current profile, so it works before the first confirm.

Every step is optional. A user whose resume cannot be read can type facts in by hand, so a bad file never blocks the journey.

## What we accept

| | PDF | Word (.docx) |
|---|---|---|
| Size | at most 10 MiB | at most 10 MiB |
| Length | at most 20 pages | no page count; text is capped instead |
| Text cap | 120,000 characters | 120,000 characters |
| Refused | encrypted, corrupt, scanned (no text layer) | encrypted, legacy `.doc`, macro-enabled (`.docm`, `.dotm`), malformed or suspicious archives |

The file's **bytes decide its type**, not its name or declared MIME type, so a renamed file is stored and served as what it really is.

**No OCR.** A PDF with no readable text is rejected with the code `OCR_REQUIRED` and a message that points the user to pasting text or entering facts by hand. A clear refusal is safer than guessed text becoming profile facts.

Word files are opened defensively: the code limits the number of parts, the unpacked size and the compression ratio, refuses files that contain a DOCTYPE or entity declaration, and never follows links. See `profile_bank/importing/docx.py`; the tests in `backend/tests/test_profile_importing_docx.py` cover each refusal.

## How facts are extracted

Extraction runs inside the import request and is bounded (PDF reading gives up after 20 seconds).

1. **Read the text** with page numbers and line positions (`importing/text.py` for PDF, `importing/docx.py` for Word). Two-column layouts and bullet lists are handled by position.
2. **Parse into JSON Resume v1**, an open schema, using local heuristics (`importing/parsers.py`). JSON Resume is the common shape for every import source; a second step maps it to the profile bank's items (`importing/candidates.py`). The reasoning for parsing into an open schema first is in [brief 10](10-PROFILE-BANK.md).
3. **Attach evidence.** Each proposed fact carries the page and source line it came from. Facts the user types or edits are marked as the user's own. A value that no longer matches its evidence loses its "imported" label.

The parser never invents employers, dates, certifications, salaries or achievements. Missing dates stay missing. Text inside a resume is data, not instructions, and the parser does not follow links in it.

### Why heuristics, not a language model

Heuristics are the default everywhere, including AWS (`MODEL_BACKEND=heuristic`). Resume text therefore stays inside the API function and is never sent to a model.

- **Locally**, a developer can try an Ollama model instead. If it is unavailable or returns invalid JSON twice, the import falls back to the heuristics and says so.
- **Amazon Bedrock** was the original plan. The `bedrock` option is a stub that cannot extract: the import falls back to the heuristic parser. Bedrock isn't available on the course AWS account.
- **The school's hosted model** is used for fit analysis, the AI resume rewrite and cover letters ([12](12-FIT-ANALYSIS.md), [14](14-COVER-LETTERS.md)), but resume import does not call it.

## Review and apply

- Every proposed item is shown beside what is already in the profile. The user chooses **add**, **merge** or **skip** per item, and picks which basics fields to take.
- **Merges only add.** They never overwrite an existing fact; where the two differ, the difference is reported as a conflict for the user to see.
- Applying runs in **one transaction** and counts as one profile edit. Applying twice returns the first result, so a double click cannot duplicate items. If one item cannot be saved, nothing is applied, and the message names the item.
- The input is **frozen** when the import starts (a SHA-256 of the bytes), and the check is repeated before parsing, so the review always matches the file the user chose.
- Deleting profile data bumps a profile "epoch"; a review opened before the deletion is refused with a clear message instead of reviving old facts.

## Files and storage

- **In AWS**, the API gives the browser a short-lived presigned S3 `PUT` URL (five minutes, with the declared size signed in). The browser uploads straight to the private documents bucket, so large files bypass the API's payload limit. A second call, **finalize**, checks the object's size, records its S3 version ID and hash, and parses that exact version. Bucket versioning means reusing the upload URL cannot change what was parsed.
- **Locally**, the API writes the file to a Docker volume through the same storage code.
- Downloads go through the API, which checks ownership first, then returns a presigned `GET` URL valid for one minute.
- Deleting an upload removes every stored version of the file after the database change commits. Facts already applied to the profile, and the import record that explains where they came from, are kept.
- **Delete profile data** (`DELETE /v1/profile/data`, with an explicit `DELETE` confirmation) removes items, imports, confirmed versions and uploads, and clears the files.

Code: `backend/src/job_hunter/profile_bank/importing/`, `backend/src/job_hunter/api/profile_bank.py`, `backend/src/job_hunter/adapters/storage.py` and, for the screens, `apps/web/src/profile/`.

## Confirmation and what happens next

**Confirming is an explicit action.** It creates an immutable profile version for the current bank revision (with a content hash). Confirming the same revision again reuses that version instead of creating another, and a stale confirmation is rejected with a conflict. Editing the profile afterwards never changes a confirmed version. Fit analysis and cover letters use a confirmed version and do not silently change the user's source facts.

After a confirm, the app asks for a new vector:

- **In AWS**, the API writes an empty flag object to S3 after the database commit, and the embed worker does the rest ([11](11-EMBEDDING-WORKER.md)).
- **Locally**, the API calls the embedder service directly.

Either way the save never fails because of embedding. Until the vector is ready, "All jobs" works as usual and "For you" shows the keyword list with a "we're still preparing your matches" message ([05](05-RECOMMENDATIONS.md)).

The text that is embedded (`profile-v2`) is built from the confirmed profile plus the user's current target roles from their preferences. It covers target roles, headline and summary, skills, role titles, project names and bullet points. **Contact details are removed**, and education is left out. It is capped at 8,000 characters. The same job-side model and dimensions are used for jobs, so the two are comparable.

## Privacy

- Every profile table is protected so that each user's rows are visible only to that user (row-level security in Aurora, [02](02-BACKEND-AND-DATA.md)).
- Contact fields are kept out of the embedding text.
- Original files are private, downloadable only by their owner, and deletable by the user.

## Tests

Pytest covers, with synthetic fixtures only (no real person's resume is committed):

- PDF and Word parsing, including two-column layouts, missing dates and instruction-like text inside a resume (`test_profile_importing.py`, `test_profile_importing_docx.py`);
- unsafe, encrypted, legacy and oversized Word files, and type detection by content;
- schema validation of JSON Resume input and malformed model output with heuristic fallback;
- merge rules, evidence matching and conflict reporting;
- the profile bank, versions and confirmation (`test_profile_bank*.py`);
- the embedding text, including removal of contact fields (`test_profile_text.py`).

## Limits

- No OCR, so scanned resumes need to be pasted or entered by hand.
- Heuristic parsing is best on conventional layouts. Unusual designs produce fewer or messier candidates, which is why the review step exists.
- Legacy `.doc` files must be saved as `.docx` or PDF first.
