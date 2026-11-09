# 09 — Resume editor and polished document layout

**Resume Studio** edits the structured resume and exports a clean PDF with LaTeX-inspired typography. A person can build and edit a resume with no job selected and no AI use.

The editor is the front end for the documents described in [06](06-APPLICATION-PREPARATION.md) (storage, review, export). Cover letters reuse the same document machinery ([14](14-COVER-LETTERS.md)). Resumes are assembled from the profile bank ([10](10-PROFILE-BANK.md)).

Raw LaTeX source editing is not offered. The goal was LaTeX-style *output*, and a visual editor over structured content gives that without running a LaTeX compiler (see "Why structured JSON and ReportLab").

## What the person can do

- **Start a resume** in four ways: blank; **Build from my profile** (pick items and points from the profile bank, with keyword suggestions for a chosen job); **a tailored copy** of an existing resume for a job (rule-based or AI, see 06); or **Duplicate**. A copy is separate: editing it never changes the original or the profile.
- **Edit** the header (name and contact details), summary, and any number of sections with entries and bullets: add, remove, hide and reorder them using buttons. A section can be experience, education, projects, skills, custom, certifications, awards or volunteering. Points can be picked from the profile bank per entry.
- **See it as they type.** A live preview sits beside the editor (switched with Edit and Preview tabs on a narrow screen). It shows the page size, a page count and dashed page-break lines.
- **Choose a style.** Three presets: *Classic serif*, *LaTeX classic* (Latin Modern, the LaTeX default typeface) and *Modern sans*. Underneath are two templates, `classic` and `modern`. Layout settings cover font size (8–16 pt), margins (10–35 mm), typeface (template default, serif, Latin Modern, sans serif, monospace), line spacing (1.0–1.8) and paper (A4 or US Letter).
  Style settings add heading style, accent colour, bullet character, header alignment, contact separator, section spacing, skills layout and date format.
  A person's preferred defaults are saved with their profile and applied to new resumes.
- **Undo and redo** within the open session (up to 50 steps).
- **Review and export.** Mark the current revision as reviewed, then download the PDF. Any later change clears the reviewed mark. **PDF preview** shows the server's PDF at any time without reviewing it.
- **Attach** a reviewed revision to an application in the tracker.
- **Delete and restore.** Deleting archives a resume: it leaves the library, but exports and application attachments keep working, and it can be restored.

## Saving

The editor saves automatically about 0.7 seconds after the last edit and shows the state: *Unsaved*, *Saving…*, *Saved*, *Conflict* or *Save failed*. Each save sends the revision it was based on. If the server's copy has moved on (for example the same resume was changed in another tab), the save is refused with a conflict, the person's local edits stay on screen, and **Reload latest** fetches the server version. Edits are never silently overwritten, and a failed save never discards what was typed.

The app does not let a person walk away from unsaved changes: leaving the editor, reloading or opening the PDF preview waits for the save, and the browser's Back button is held on the same page with a message until it finishes. Drafts are not kept in browser storage, because a resume holds personal data; the server copy is the only persistent one.

## Storage and API

A resume is a `documents` row: `kind`, `title`, `template`, `content` (JSON), `layout` (JSON), `revision`, `reviewed_revision` and an optional `job_id`. A manual resume needs no job and no AI task. Every content, template or layout change increases `revision`, and `reviewed_revision` only ever matches one exact revision.

| Route | Purpose |
|---|---|
| `GET /v1/documents?kind=resume`, `POST /v1/documents` | The library; create a blank or manual resume |
| `POST /v1/documents/from-bank` | Build from the profile bank (a plan of items, points, skills and an optional job) |
| `POST /v1/resume-builds/suggest` | Suggested items and points for a job (keyword rules, no model) |
| `GET/PATCH/DELETE /v1/documents/{id}`, `POST …/restore` | Read, revision-checked edit, archive, restore |
| `POST …/duplicate`, `POST …/tailor` | A separate copy, optionally linked to a job; a tailored copy |
| `POST …/review`, `POST …/exports`, `GET /v1/exports/{id}`, `GET …/preview.pdf` | Review, export, download, working preview |

Creating, editing, duplicating, building from the bank and exporting never use the AI allowance. Only the AI option of `tailor` does.

The server validates every write: allowed section kinds, bounded text lengths (bullets up to 4,000 characters, up to 30 sections and 100 entries per section), the template name, and layout values inside the ranges above. Content is plain text, not HTML, so there is nothing executable to store. Bullets copied from the profile carry a source reference (item, item revision and the profile text at the time of copying), and the server checks that it points at the caller's own profile item.

A resume edit never changes the profile on its own. Saving a reworded point back to the profile is a separate, explicit action in the point's menu (see 10).

## Why structured JSON and ReportLab

The document is stored as structured JSON, kept apart from the template, so changing the look can never lose text. The PDF is drawn by a deterministic Python renderer (`preparation/rendering.py`, ReportLab) from the saved revision. Bundled fonts mean the PDF looks the same whatever is installed on the server.

Why not LaTeX or a headless browser: either would need a large runtime in Lambda or a separate rendering service, for a visual style we can reproduce with typography choices (a serif or Latin Modern face, rules under headings, tight spacing). ReportLab runs inside the same API image as everything else.

Why two previews: the live preview in the browser is HTML laid out to match, so it updates on every keystroke, but its page breaks are approximate and it is labelled that way. The server's PDF is authoritative for export and preview: export renders it, and **PDF preview** shows it. Review marks the saved revision, not the PDF, and the preview endpoint never marks anything reviewed.

The template does not claim guaranteed compatibility with applicant tracking systems. The PDF has selectable text and a plain structure, which is all we assert.

## Tests

- `apps/web/src/editor.test.ts` covers the content helpers: adding, removing and moving sections, entries and bullets, and the profile-bank sources.
- Component tests under `apps/web/src/studio/` cover the library, the preview and its page counting, the build flow, style settings and saving a point back to the profile.
- `backend/tests/test_resume_rendering.py` renders synthetic resumes and checks that each style setting changes the look but keeps the text. `backend/tests/integration/test_resume_build_api.py` covers building from the profile bank, defaults, other users' items being rejected, and archive and restore. `backend/tests/integration/test_tenant_isolation.py` covers a document staying invisible to another user and an application keeping a snapshot of a reviewed resume and letter.

## Not built

- Inline formatting (bold, italic, links) inside bullets, drag-and-drop reordering, collaborative editing, raw LaTeX input, importing a PDF's layout, and a large template library.
- CJK (Chinese, Japanese and Korean) fonts. The bundled fonts are Latin ones.
- Automated browser tests of the editor. See [PENDING.md](../status/PENDING.md).
