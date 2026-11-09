# 10 — Profile bank

**Status:** built and deployed. Builds on [03 Profiles and resumes](03-PROFILES-AND-RESUMES.md) and [09 Resume editor](09-RESUME-EDITOR.md). Resume building and recommendations read from it. The AWS picture is in [what runs where](../architecture/aws-overview.md).

## Goal

Each user has one profile page that holds everything they might put on a resume: contact details, experiences with achievement points, education, projects, skills and certificates. Resumes are assembled from this bank instead of being retyped, and the same bank feeds job recommendations.

## Principles

- **A resume is a copy.** Editing a resume never changes the bank, and editing the bank never changes a resume. The only way back is per point, through the point's menu, and the user confirms it.
- **Imported data is a candidate until the user accepts it.** Nothing extracted from a file goes straight into the bank.
- **Every row belongs to one user** and is protected by PostgreSQL row-level security (RLS).

## 1. How it is stored

| Table | Holds |
|---|---|
| `profiles` | Basics only in `draft` (name, headline, email, phone, location, summary, links), plus the revision counters below |
| `profile_items` | One row per experience, education, project, skill, certification, award, volunteering entry or custom entry |
| `profile_versions` | Confirmed snapshots, used by the semantic ranking |
| `profile_imports` | One row per import attempt: frozen input, status, candidates |
| `user_settings` | Per-user resume defaults |
| `uploads`, `documents` | Uploaded files and resumes, as before |

Items keep the common fields as columns (`kind`, `position`, `tags`, `parent_id`, `revision`, `archived_at`) and the kind-specific fields in a `data` JSONB column. Each kind has a Pydantic model that validates it. That mirrors how `documents.content` already works and avoids one table per kind. Skill names are unique per user (a partial unique index).

```jsonc
// experience (abridged)
{ "title": "Data & Backend Engineer", "organisation": "Harbour Metrics", "location": "Singapore",
  "start": "2023-07", "end": null, "current": true, "summary": "", "skills": ["Python"],
  "bullets": [
    { "id": "b_7f3a", "text": "Cut p95 dashboard query time from 4.2 s to 0.9 s ...", "tags": ["backend"],
      "skills": ["PostgreSQL"],
      "alternatives": [ { "id": "v_1", "text": "Made analytics dashboards 4x faster ...", "tags": ["data"] } ] } ] }
```

- **Points live inside their item**, each with a stable `id`. A point is never used without its parent and nothing queries points on their own, so a separate table would add joins for no gain. The UI says *points* and *versions*; the schema says `bullets` and `alternatives`, so they are not confused with `profile_versions`.
- **Tags** on a point are its types (`backend`, `data`, `leadership`). The profile page groups a job's points by their first tag, and the free build can focus on a tag.
- **Versions** are other wordings of the same achievement, such as a technical and a business-impact version. They share the point's `id`, so the profile counts one achievement, and a resume uses at most one wording of it.
- **Projects inside a job:** a project can set `parent_id` to an experience (composite key `(parent_id, user_id)`, so a child always has the same owner). The profile page nests it under the job.
- **Dates** are `YYYY` or `YYYY-MM` with `current`. `end: null` with `current: false` means the end is unknown. Text that cannot be read as a date is kept in `dates_text`.
- **Limits:** 50 active items per kind, 30 points per item, 5 versions per point (including its main wording), 4,000 characters per point.
- **Archiving** is a soft delete. Resumes that copied an item keep their text and only lose the profile helpers.

### Revisions and snapshots

Four counters guard writes:

- **`profiles.revision`** goes up on every edit of the basics. Edits send `expected_revision`, and a mismatch is a 409.
- **`profile_items.revision`** goes up on every edit of an item. Edits send `expected_revision`, and a mismatch is a 409, so a stale tab never overwrites newer text.
- **`profiles.bank_revision`** goes up in the same transaction as every basics edit, item create, edit, archive, revert, reorder and import apply. Reordering sends `expected_bank_revision`.
- **`profiles.profile_epoch`** goes up only when the user deletes their profile data. It acts as a deletion fence. See [Deletion scope](#deletion-scope).

**Live vs confirmed.** `build_profile_snapshot(db)` assembles the profile from basics plus active items. It has the same shape the recommender has always read, with two extra keys: `bank_revision` and a flat `bullets` list. Keyword ranking reads this live snapshot, so edits show up at once. *Update my matches* calls `POST /v1/profile/confirm` with `expected_bank_revision` and stores that snapshot as a `profile_versions` row (one per revision). Semantic ranking reads the confirmed snapshot via `get_confirmed_snapshot(db)`, so a recommendation can always say which version of the profile it used. The profile page offers *Update my matches* while `bank_revision` is ahead of `confirmed_revision`.

The snapshot only ever gains keys. Snapshots carry point IDs but not provenance.

### Embeddings

Confirming a profile, or saving preferences, triggers a re-embed of the confirmed snapshot. The text is built by `embedding/profile_text.py` (version `profile-v2`): target roles from preferences, headline and summary, skills, role titles, project names and point text. Name, email, phone, links and location are scrubbed out. The model is `jinaai/jina-embeddings-v2-small-en` (512 dimensions), and vectors are stored in `profile_embeddings` against the profile version.

Locally, the API can embed in the request through the HTTP embedder. On AWS the API writes a small flag object to S3 after the commit, S3 notifies SQS, and the embed Lambda does the work ([11](11-EMBEDDING-WORKER.md)). A failed embed never fails the save. Editing the bank does not re-embed. Only confirming the profile or saving preferences does, so embedding follows an explicit user action.

### Moving from the old profile

Migration `0010_profile_bank` split the old `profiles.draft` (which held skills, experience, education and projects) into `profile_items` and left only basics in the draft. Existing revisions were carried over, so existing confirmed snapshots stayed valid. The migration is reversible: a downgrade packs the bank into a `_profile_bank_v1` key in the draft, so no data is lost. Migration `0011` added `profile_imports.applied_result` and `profiles.basics_provenance`.

## 2. Importing from existing resumes

### Parse into JSON Resume, then map

[JSON Resume](https://jsonresume.org/schema) (MIT, v1.0.0) is an open resume format that already covers almost everything the bank holds: `basics`, `work[]` with `highlights[]`, `education[]`, `projects[]`, `skills[]`, `certificates[]`, `awards[]` and `volunteer[]`. Every import source produces JSON Resume, and **one mapper** (`importing/candidates.py`) turns that into bank candidates. The reasons:

- One mapper to write and test instead of one per source.
- Language models already know the format, so extraction prompts stay short and output validates easily.
- People who already have a `resume.json` can import it directly, and the bank can export itself in the same format.

No maintained, permissively licensed library parses arbitrary resume PDFs well without a model, so unreadable structure is handled by review rather than guessed at. Text is extracted with `pdfplumber` (page and line positions are kept for evidence). Word `.docx` files are read with a bounded reader (size, entry and compression-ratio limits, no macros, no legacy `.doc`).

### Sources

| Source | Path |
|---|---|
| A resume in Resume Studio | `documents.content` converted to JSON Resume. Entries the converter cannot classify go to an **Unsorted** group the user files or skips; their text is kept |
| A `resume.json` file | Validated against the JSON Resume shape, then mapped. A file exported from the bank restores everything (see Export) |
| An uploaded PDF or Word file | Text extraction, then the parser below |
| Pasted text | Same as an uploaded file |

**Parser.** With a model, the text goes to the model asking for JSON Resume only, and the output is validated; an invalid answer gets one retry. Without a model, or after a failed retry, a heuristic parser (headings, date ranges, bullet markers) runs instead. `profile_imports.parser` records the path (`document-v1`, `json-resume-v1`, `heuristic-v1`, or the model backend's name).

`MODEL_BACKEND` selects the model. The values are `fake` (tests), `ollama` (a developer machine) and `heuristic` (no model, used on AWS). A `bedrock` value exists, but its adapter is a stub that only raises an error. Amazon Bedrock isn't available on the course AWS account, so the AWS profile sets `MODEL_BACKEND=heuristic` for the API Lambda (`infra/aws/backend/main.tf`). Imports there always use the heuristic parser. Resume text is treated as data, never as instructions.

### Review before apply

An import is created with `POST /v1/profile/imports` and returns a list of **candidates**: one `basics` candidate plus one per item. The review screen shows each with **Add**, **Merge** or **Skip**, editable inline. Nothing is written until `POST …/apply`. Review exists because extraction is imperfect and the bank is the source for every later resume, so a wrong date or an invented bullet would spread.

- **Frozen input.** Uploads are referenced by their `sha256`. A Studio document, `resume.json` body or pasted text is copied into `input_payload` and hashed, so parsing and retries always read what the user chose, never a document edited since. `input_payload` is cleared when the import is applied or discarded.
- **Evidence per field and point.** After extraction, each field and point is located in the source text (normalised match) and gets `evidence {source_sha256, page, text}`. The review screen shows "From the source: …". Anything that cannot be located is flagged "Not found in the source, check this". A flag does not block, because it is the user's own resume.
- **Provenance after apply.** Evidence moves into the item as `provenance {origin: "import" | "user", import_id, evidence}`. Editing an imported point so that it no longer matches its evidence text switches `origin` to `"user"` (keeping the original excerpt), so a reworded or extended claim is no longer presented as backed by the file.
- **Matching.** Each candidate is labelled `new`, `duplicate` (same organisation and title, or same skill name, with the same points; when both entries have a start date they must also share the start year), `update` (same item, different points) or `ambiguous` (several items could match, so the user picks). Basics always compare field by field against the current profile.
- **Additive merge.** Merging fills empty fields, adds skills and tags, appends points not already present (normalised-text match), keeps existing point IDs and versions, and lists conflicting fields instead of overwriting them. Dates merge as one unit, so a merge cannot make an entry both current and ended.
- **Apply is safe to repeat and to race.** It runs in one transaction and counts as one bank revision. Merges send each target's `expected_revision`, and the request carries the `profile_epoch` it started under, so a review left open across a deletion is refused. A second apply of an applied import returns the stored result. If any accepted item cannot be saved (for example it would pass a limit), nothing is applied and the message names the entry.
- **Imports run inside the request** in both local and AWS profiles; there is no queue. The input limit is 1 MiB and an import is capped at 400 items plus the basics candidate.

### Export

`GET /v1/profile/export.json` returns the bank as JSON Resume. Standard fields carry each point's main wording, so any JSON Resume tool can read the file. Everything JSON Resume cannot model (versions, point tags, custom sections, provenance, parent links) goes under `meta.jobHunter` as a full copy of the active bank. Importing our own export restores all of it; other tools ignore the extra key.

## 3. Using the bank in resumes

### What a resume stores

A resume is still `documents.content`: sections of entries of `bullets: string[]`. The bank adds optional fields, so old resumes validate unchanged:

```jsonc
// documents.content.sections[]
{ "id": "s1", "title": "Experience", "kind": "experience", "hidden": false,
  "entries": [ { "id": "e1", "heading": "Backend Engineer", "subheading": "Harbour Metrics · Singapore",
      "dates": "Jul 2023 – Present",
      "date_range": { "start": "2023-07", "end": null, "current": true },
      "source": { "item_id": "…", "item_revision": 4 },
      "bullets": ["Built FastAPI services ...", "Made dashboards 4x faster ..."],
      "bullet_sources": [ { "bullet_id": "b_1", "base_text": "Built FastAPI services ..." },
                          { "bullet_id": "b_7f3a", "alternative_id": "v_1", "base_text": "Made dashboards 4x faster ..." } ] } ] }
```

- **`bullets` stays plain text**, so the preview, the PDF renderer and existing data do not change. `bullet_sources` runs alongside it, one entry per bullet (`null` for a point written in the resume).
- **`base_text`** is the profile wording at the moment of copying. A point counts as edited when its text differs from `base_text`. That is the history the save-back rules need, without an item history table.
- **`date_range`** lets the date format re-render. Editing an entry's date text removes `date_range`, so a later format change cannot bring back old dates.
- **Server checks** (`api/document_checks.py`): section `kind` must be known, `hidden` a boolean, `bullet_sources` the same length as `bullets`, `date_range` well-formed, and layout choices from the allowed lists. Every `source.item_id` must belong to the caller. RLS hides other users' items, so a foreign ID reads as missing. IDs already stored in the resume are not re-checked, so a resume whose item was deleted stays editable.

### Two ways to build

Both produce a **build plan** (which items, which points, which wording of each, in what order), turned into an ordinary `documents` row by `POST /v1/documents/from-bank`. The plan is checked as a whole: an item must fit its section kind, a resume uses one wording per point, and an unknown, archived or foreign item or point is refused, so no half-built document is saved.

| | **From my profile** | **For a job** |
|---|---|---|
| Starts from | Resume Studio → *New resume* → *From my profile* | A job → *Prepare resume*, or *New resume* → *For a job* |
| Pre-selection | Items and points matching the chosen focus (point tags), in profile order, up to `points_per_item` points per item (default 4) | A suggested plan ranked against the job, with a reason for each pick |
| Extra panel | None | Job skills covered and not covered by the profile, with *Add to profile* for gaps the user really has |
| Result | General resume | Resume linked to the job (`job_id`), ready to attach to the application |

The user always sees and edits the plan before anything is created. New resumes start from the user's resume defaults, with contact details and (optionally) the summary filled from profile basics. Skills become one editable line per category ("Languages: Python, SQL").

**Suggestions** come from `suggest_plan(job, bank, "keyword-v1")`, a pure function that saves nothing (`POST /v1/resume-builds/suggest`). It scores each item and point by the overlap between its skills, tags and title and the job's skills and title. It reuses the skill normalisation the recommender uses, and it picks the best wording of each point. Reasons are concrete ("listed in the job requirements"). It caps how much it suggests per section and includes the newest education by default. Keyword scoring is cheap, deterministic and explainable, which suits a suggestion the user will review anyway.

### In the editor

Once content lands in a resume it belongs to that resume. Rewording, trimming, reordering and deleting are ordinary edits that autosave and never touch the profile.

Each point has **↑ / ↓** buttons, always visible, its text box, and a **⋮** button. Alt+↑ and Alt+↓ move the point from the keyboard. **⋮** and right-click open the same menu (so do the Menu key and Shift+F10); on narrow or touch screens it opens as a bottom sheet. The menu has one level of submenu:

```
Versions ▸         swap this resume's wording for another version (only if the profile point has others)
Move up / Move down
Remove from resume
─────────
Save to profile ▸  Update in profile      (only if linked and edited)
                   Save as new version    (only if linked and edited)
                   Save as new point…     (asks which item, or a new one)
```

The top level acts on this resume and is used often. **Save to profile** acts on the profile, is used rarely, and sits last so it is not hit by accident. Options that do not apply are hidden rather than greyed out. Titles, dates, organisations and layout never save back; only points do.

**Saving back is guarded:**

- **Update in profile** replaces the version the point came from. First the editor checks that the profile wording still equals `base_text`; if it does not, nothing is written and the user sees the current profile text and can *Save as new version* instead. The write also carries the item's `expected_revision`, so a race gives a 409, not a silent overwrite. The replaced wording is kept as another version unless the user chooses otherwise.
- **Version limit:** if keeping the old wording would pass the 5-version limit, the user picks which other version to replace. The main wording is never dropped silently.
- **Undo** is a toast on each profile save, separate from the editor's own undo. It calls `POST /v1/profile/items/{id}/revert` with the item's new revision, so if anything changed the item since, the undo fails with a 409 rather than overwrite later edits.
- Only after the profile write succeeds does the editor update `base_text` and `source.item_revision`, through the normal edit path, so undo and autosave cover it.

Per section, the user can reorder, hide (`hidden`: kept but not rendered) or delete. A section with a known `kind` has **Add from profile**, which lists unused points with a version picker. Custom sections are free-form and their points can be saved to a `custom` item.

### Style, date formats and defaults

Style lives in the resume's `layout` JSON and autosaves with it. Both the live preview and the server PDF renderer read the same settings, so what the user sees is what they export.

| Setting | Values |
|---|---|
| `date_format` | `Jul 2023` · `July 2023` · `07/2023` · `2023` |
| `present_label` | `Present` · `Current` · `Now` |
| `heading_style` | `rule` · `small-caps` · `bold` |
| `accent_color` | `black` · `navy` · `teal` · `maroon` (small palette that stays readable in print) |
| `bullet_char` | `•` · `–` · `▪` |
| `header_align` | `center` · `left` |
| `contact_separator` | `·` · `|` · new line |
| `section_spacing` | `compact` · `normal` · `airy` |
| `skills_layout` | `inline` · `grouped` · `columns` |

**Resume defaults** are one `user_settings` row per user (`resume_defaults` JSONB with its own `revision`), kept apart from `preferences`, which hold job-search filters. They store template (`classic` or `modern`), layout, section order and titles, header fields and build options (points per item, whether to use the profile summary). They apply **once, when a resume is created**, so changing defaults never restyles an existing resume. Missing keys fall back to built-in defaults. The style panel has *Save as my default* and *Apply my defaults* (an ordinary, undoable edit). API: `GET`/`PUT /v1/settings` with `expected_revision`.

Templates only read content and layout and never own data. Both built-in templates render through ReportLab.

## Deletion scope

*Delete my profile data* (`DELETE /v1/profile/data`, typed confirmation) runs in one transaction. It is the erase for profile facts, in the spirit of Singapore's Personal Data Protection Act (PDPA).

| Deleted | Kept, and why |
|---|---|
| Basics (`draft` reset), all `profile_items` including archived | Resumes and their exports: separate documents the user manages in Resume Studio. The dialog says so |
| All `profile_versions`, with their embeddings; `confirmed_revision` cleared | Applications and attached PDFs: deleted with the application |
| All `profile_imports`, including frozen input | `user_settings` (style preferences, not profile facts), unless the user ticks the box to delete them too |
| Uploaded resume files and their `uploads` rows (bytes removed after the commit) | |

`bank_revision` and `profile_epoch` both go up. An import records the epoch it started under and refuses to retry or apply under a different one, so a stale review cannot recreate deleted data. Resumes keep their text but lose profile helpers, because `source.item_id` no longer resolves; archiving behaves the same way.

## 4. Keeping users separate

The bank uses the same mechanism as every other user table, so local and cloud behave identically:

1. **`user_id` on every row** of `profile_items`, `profile_imports` and `user_settings`.
2. **RLS:** `ENABLE` and `FORCE ROW LEVEL SECURITY` with a `tenant_isolation` policy (`user_id = current_setting('app.user_id')`, for both `USING` and `WITH CHECK`). The API sets `app.user_id` with `set_config(..., true)` at the start of each transaction. The value comes from the authenticated user (the dev header locally, the verified Cognito `sub` on AWS), never from a request body. The API connects as `jobhunter_app`, which is not a superuser and cannot bypass RLS (the AWS migration job checks this). A forgotten `WHERE user_id = …` returns nothing instead of another user's data.
3. **Composite foreign keys** `(upload_id, user_id)`, `(document_id, user_id)` and `(parent_id, user_id)`, so a row cannot point at someone else's file, document or parent even through a bug.
4. **Tests:** `backend/tests/integration/test_tenant_isolation.py`, `test_profile_bank_rls_writes.py` and the profile API tests cover cross-user reads and writes.

## API

| Method and path | Purpose |
|---|---|
| `GET /v1/profile/bank` | Basics plus active items, grouped by kind, with revisions |
| `GET`/`PUT /v1/profile` | Basics, with `expected_revision` |
| `POST /v1/profile/items`, `GET`/`PATCH`/`DELETE /v1/profile/items/{id}` | Create, read, edit (409 on a stale revision), archive |
| `PUT /v1/profile/items/order` | Reorder within a kind |
| `POST /v1/profile/items/{id}/revert` | Restore earlier item data (undo of a save-back), with `expected_revision` |
| `POST …/items/{id}/bullets`, `PUT …/bullets/{bullet_id}`, `POST …/bullets/{bullet_id}/alternatives` | Add a point; update a point's wording (old wording kept as a version); add a version |
| `POST /v1/profile/confirm` | *Update my matches*, with `expected_bank_revision` |
| `POST /v1/profile/imports`, `GET /v1/profile/imports`, `GET …/imports/{id}` | Start, list, read an import |
| `POST …/imports/{id}/apply`, `…/discard`, `…/retry` | Apply decisions (idempotent), drop, or re-run a failed import |
| `GET`/`PUT /v1/settings` | Resume defaults, with `expected_revision` |
| `POST /v1/documents/from-bank` | Create a resume from a build plan |
| `POST /v1/resume-builds/suggest` | Suggested plan, reasons and skill coverage for a job (saves nothing) |
| `GET /v1/profile/export.json` | The bank as JSON Resume |
| `DELETE /v1/profile/data` | Delete all profile data |

## Not built

Left out on purpose, to keep the scope finishable:

- **Angles** (saved selections per job) and **Pull update** from the profile into an existing resume. The schema and API accept `angles` and `source.angle_id`, but no screen produces them and nothing reads them.
- **Background imports.** Parsing runs inside the request; `profile_imports.task_id` is unused.
- **Model-backed parsing on AWS.** The code path exists (`ollama`), but the AWS profile uses the heuristic parser.
- **Item-level embeddings, AI suggestions** (reword, tailored summary, pick for a job) and an `embedding-v1` suggestion strategy.
- **Typst templates** and user-saved named style presets (the three built-in styles exist; see [09](09-RESUME-EDITOR.md)). Templates stay on ReportLab.
