# Frontend handoff

## Delivered

Implemented the React, TypeScript and Vite app in `apps/web/` with a real `/v1` API client and a development identity selector (`alice` / `bob`, sent as `X-Dev-User`). Discover, Profile, Tracker and Resume Studio use responsive layouts, visible loading/error/empty states, accessible labels, and a restrained, readable type scale. The desktop sidebar collapses accessibly on narrow screens; mobile Tracker uses application cards with a visible details action.

Discover searches the server-side result pool with offset pagination and displays provided job facts, matching reasons, source dates and links. The job title and “Read full description” open a detail dialog with the complete source description and save/pass actions. Ranking language comes from the backend `ranking_status`; scores are not shown as percentages. Profile includes optional fictional SQL-analyst and ML-engineer samples that load into the form as unsaved drafts; the user must explicitly save. Saving profile/preferences refreshes recommendations.

Tracker edits status, applied date and notes in an accessible, guarded details dialog with source link. It stores a manually written cover letter and can attach, replace or clear a reviewed resume export. Selecting a resume document and its reviewed revision asks the API to make an immutable PDF snapshot. The dialog shows the document title and revision and downloads the owned PDF through an authenticated fetch. Saved cover letters download as text. Existing packet fields are omitted from ordinary application updates, so they remain attached unless the user changes them. The UI says plainly that the packet is stored for reference and has not been sent to the employer.

“Prepare resume” in an application opens Resume Studio with the application context. The user can create a blank copy populated from the current profile or choose an existing resume to create a separate, job-specific copy. The context follows job-linked documents when they are reopened. A saved, reviewed revision can be attached to the application and returns the user to Tracker. Unreviewed or unsaved documents cannot be attached.

Resume Studio supports manual creation and duplication, classic serif and modern sans templates, and controls for template/font family, type size (8–16 pt), margins (10–35 mm), line spacing (1.0–1.8) and A4/US Letter. The structured editor supports contact details, summary, sections, entries and bullets, with undo/redo and section/entry removal/reordering. Autosave is debounced; conflicts retain the local draft, and typing during an in-flight save is rebased on the accepted revision. Review, export and preview use authenticated requests; the server PDF preview opens in an in-app dialog. Mutating actions lock the editor briefly, while navigation/reload is guarded against discarding unsaved changes. Resume cards use actual section names rather than illustrative labels.

Profile accepts PDFs up to 10 MiB, displays extracted text as a read-only review candidate, and does not write parsed text into profile facts.

## Run and configuration

```sh
cd apps/web
npm ci
npm run dev
```

Vite listens on `0.0.0.0:5173`. The default `/v1` proxy targets `http://localhost:8000`; Docker Compose can set `API_PROXY_TARGET=http://api:8000`. Set `VITE_API_BASE_URL` only when the browser should call a different public API base. The supplied `Dockerfile` uses Node 22, `npm ci`, and the Vite dev server. Dependencies are pinned in `package.json` and `package-lock.json`.

## API calls

The client consumes `/me`, `/profile`, `/profile/confirm`, `/preferences`, searchable/paginated `/recommendations`, `/jobs/{id}/review`, `/applications`, `/applications/{job_id}`, `/documents?kind=resume`, document create/patch/duplicate/review/export, `/documents/{id}/preview.pdf`, `/exports/{id}`, and `/uploads` → upload content → upload result. Application updates can submit `resume_document_id` with `expected_resume_revision`, or `resume_export_id`, and may include `cover_letter_text`; absent packet properties are preserved. Document create and duplicate accept a `job_id` for job-specific preparation. Requests use snake_case and `X-Dev-User`; PDF preview/download requests use `fetch` with the same identity header.

AI generation and automated applications are unavailable in this local POC. Salary and seniority filters are pending; local recommendations use role, location and work-mode preferences. The resume editor’s on-screen preview is approximate; use the server-rendered PDF preview for final layout review. Browser/runtime verification is handled by the parent agent.

## Checks

- `npm test -- --reporter=dot` — 15 tests pass, covering API-backed Discover and pagination, upload extraction review, profile save gating, resume creation/editing, autosave conflicts and slow saves, identity guard, reviewed export gating, immutable packet attachment and cover-letter storage, preservation of existing packet data, and job-specific preparation through review/attach.
- `npm run build` — TypeScript check and Vite production build pass.

### Tracker resume navigation correction — 5 October
Prepare resume now opens the selected application's attached/job-linked draft when available, rather than always dropping into the general library. Applications without a draft retain the create/tailor flow. Return and successful attachment reopen that exact application's details. Opening an unrelated standalone resume clears stale application context. Regression coverage includes two applications with the same title but different job IDs, plus review/attach return. Production build and 16 tests pass; browser verified Backend Engineer → Alex Tan resume → same application dialog without creating new demo records.

### Template font override correction — 5 October
Selecting Classic serif or Modern sans now resets the explicit typeface override to Template default. Previously a persisted sans-serif override made Classic look sans-serif in both preview and PDF. Users may still choose a custom typeface after selecting a template. Build and 16 frontend tests pass; local web container rebuilt.

### LaTeX typography — 5 October
LaTeX classic selects the classic layout with font_family=latex. Latin Modern Roman regular/bold are bundled locally from lalten/lmweb, with upstream BSD/GUST/LPPL license notices. Browser preview and PDF embed the same font files. API accepts the additive latex value; setuptools includes the font resources for deployment. Existing saved font choices remain unchanged until selected. PDF font embedding contract suite: 27 passed. Application preparation banner now wraps onto its own editor-header row.

### Resume editor usability review — 5 October
Reduced toolbar clutter with expandable layout settings; kept templates visible. Desktop now clearly uses side-by-side editing/preview, with the view toggle reserved for mobile. Consolidated duplicate PDF exports into one footer Download PDF action and clarified review-before-export status. Editor writing/preview panes use the available viewport height with separately scrolling content. Mobile header/banner is tighter and the settings panel is constrained to the toolbar width. PDF preview retains an accessible name when displayed as an icon. Production build and 16 frontend tests pass; desktop/mobile visual checks covered populated content and settings.
