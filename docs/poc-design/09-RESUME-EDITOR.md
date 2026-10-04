# 09 — Resume editor and polished document layout

## User requirement

Job Hunter includes an actual resume-focused editor with polished, LaTeX-inspired typography. This is a core local POC feature, not merely a text box containing an AI response. A user can build/edit a resume without AI access, without selecting a job, and without AWS.

Read README.md, CONTRACTS.md and DELIVERY-SCOPE.md. This brief extends components 06 (document persistence/rendering) and 07 (editor UI). The interpretation for the first POC is visual editing with LaTeX-style output; raw LaTeX source editing/compilation is an optional future capability, not required by the current request.

## Local editor experience

- Create a blank resume, initialise from a confirmed profile, or open a job-tailored draft.
- Split view: editable content on one side, paginated document preview on the other. On narrow screens switch between editor and preview.
- Edit contact/header, summary, experience, education, projects, skills and custom sections. Add/remove/reorder sections, entries and bullets using buttons and keyboard-accessible controls; drag-and-drop is optional.
- Support basic inline formatting (bold, italic, links) and bullets through a constrained document schema. Do not store arbitrary executable HTML.
- Offer two initial templates: a classic serif academic style and a clean sans-serif professional style. Keep both text-based and single-column initially, with consistent dates, headings, whitespace and readable body sizes. Do not claim guaranteed ATS compatibility.
- Provide bounded font-size, margin, section-spacing and A4/Letter controls. Show page count/overflow; do not silently shrink text to unreadable sizes to fit a page.
- Support undo/redo for the active session, debounced autosave, visible saving/saved/error states, and conflict handling. Never discard local edits on a failed save. Keep unsaved content in memory and warn before navigation; persistent sensitive browser drafts are not required.
- Duplicate a resume into a separate version for a job. Editing that version must not alter the original resume or source profile.
- Preview and export the exact reviewed revision as PDF with selectable text. Template/layout changes also invalidate review/export cache.

## Persistence and API extensions

Component 02 coordinates these additions; component 06 owns document/rendering services and 07 owns editor interactions.

Extend documents to support manual, profile-based and generated origins. A manually created resume has no required task or job ID; its owner and kind remain mandatory. Keep optional source profile/job version references and generation provenance where relevant.

Add `GET /documents?kind=resume` for the user's resume library and `POST /documents` for manual/profile-based creation. Add `POST /documents/{id}/duplicate` for a separate owned copy with an optional validated job association. Manual creation, editing, duplication and PDF export do not consume an AI allowance. Existing AI creation endpoints keep their quota rules.

Store versioned structured content, stable block IDs, template ID/version, layout settings and revision. Use the existing revision-checked PATCH, review and export endpoints. A content or style change increments revision. Initially undo/redo can be client-session history; avoid implementing collaborative editing or an unbounded server history system.

Schema validation must cover allowed blocks, marks, links and bounded style values. Preserve source fact references on unchanged generated bullets; distinguish user edits from model-grounded content. Never silently promote a user's resume edit into a verified profile fact.

## Rendering choice and AWS portability

Use structured JSON as the canonical document. Keep content separate from the template so changing appearance cannot erase text. Start with the existing deterministic Python PDF renderer and render the same saved revision for an authoritative preview. A lightweight browser layout preview may update immediately while a debounced PDF preview catches up; label any approximate preview and verify the final PDF before review/export.

If implementation testing shows that sharing a browser/PDF renderer is materially simpler or more faithful, document that decision and its future Lambda packaging/runtime implications before changing the renderer. Do not introduce a LaTeX server or a browser-rendering cluster merely to imitate a LaTeX visual style.

PDF preview is a non-reviewed working preview; it must not mark a document reviewed or replace a reviewed export. Bound preview frequency/cache by content hash, template version and layout settings. Check ownership on preview/download endpoints. Add a preview endpoint under `/documents/{id}` if needed, coordinated in OpenAPI.

## Required tests and acceptance

Unit/component tests cover block edits/reordering, formatting sanitisation, undo/redo, autosave debounce/failure/conflicts, template switching without content loss, bounded layout values, revision invalidation and duplicate-copy isolation.

Renderer tests use synthetic one-page and multi-page resumes with long bullets, Unicode, dates and links. Inspect extracted PDF text and representative rendered pages for clipping, missing content and unintended page breaks. Do not rely on snapshots alone.

Browser acceptance: create a resume without AI, type/reorder content, switch templates, save/reload, duplicate for a job, edit the copy, review and export. The original/profile remains unchanged; the PDF matches the reviewed content/layout revision. Verify keyboard controls and owned access with two local identities.

The editor must work locally using the filesystem storage adapter and real PostgreSQL. Defer Cognito/S3 integration to the cloud milestone. Defer collaborative editing, raw LaTeX input, arbitrary PDF-layout import and large template libraries beyond this POC.
