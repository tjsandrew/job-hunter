# 10 — Profile bank

**Status:** first release implemented locally on `profile-bank` (15 October 2026); see [the status note](../status/10-profile-bank.md). Revised 14 October 2026 after review; see [Decisions and first release](#decisions-and-first-release). Builds on [03 Profiles and resumes](03-PROFILES-AND-RESUMES.md) and [09 Resume editor](09-RESUME-EDITOR.md). Area 2 (resume upload) in the [work split](../WORK-SPLIT.md); area 3 (tailoring) consumes it.

## Goal

Each user gets one profile page that holds everything they might put on a resume: contact details, experiences with achievement bullets, education, projects, skills and their uploaded resumes. Resumes are then assembled from this bank instead of being retyped.

## Decisions and first release

### User journey

1. **Fill the profile** in any of three ways: import old resumes (reviewed, duplicates merged), type into the profile, or just start writing a resume and save good points back as you go.
2. **Shape the bank:** reword points, keep several versions of the good ones, tag points by job type, keep a skills list.
3. **Job → application:** pick a job → *Prepare resume* → tick the suggested points → land in the editor → reword, reorder or hide sections, add custom sections such as "Fun facts", choose style and date format → review → export PDF → attach to the application.
4. **Save back, rarely and explicitly:** a point's **⋮** button or right-click (same menu) → **Save to profile ▸** → **Update in profile**, **Save as new version** or **Save as new point**. Each point also has persistent **↑ / ↓** buttons for reordering. Only points save back. Titles, dates, organisations and layout are resume-only formatting.

### First release

| In | Later |
|---|---|
| Profile page: basics, experience, education, projects, skills, custom sections | Angles (saved selections per job) |
| Points with types and versions | **Pull update** from profile into an existing resume (needs the 3-way merge below) |
| Import from Studio resumes, `resume.json` and PDF, with review, including basics | Model-backed parsing on SQS, item-level embeddings |
| Build for a job with `keyword-v1` suggestions; free build | AI pick, reword, summary and fit analysis |
| Editor: point picker per entry, point ↑ / ↓ reorder and ⋮ menu (right-click opens the same), section hide and reorder, date formats, style options | Power-user templates in Typst (built-ins stay on ReportLab) |
| Confirm (*Update my matches*) for recommendations | Named style presets |
| Resume defaults per user (`user_settings`) | |

Fields for the later features (`angles`, `source.angle_id`) are reserved now, and `bullet_sources[].base_text` is stored from the first release, so Pull update needs no migration.

### Review fixes folded in

1. **One profile revision.** `profiles.bank_revision` increments in the same transaction as every item create, edit, archive, reorder and import apply. Confirm takes `expected_bank_revision`, snapshots basics plus all active items at that revision, and never reuses an older snapshot. The profile page shows *Update my matches* while `bank_revision` is ahead of the confirmed revision.
2. **Copy history for resume points.** `bullet_sources[]` stores `base_text`, the profile text at the moment of copying. Edited = `text != base_text`; profile changed = profile text `!= base_text`. That is enough for a later 3-way merge (base → profile → resume) without an item history table.
3. **Additive merge rules.** Merging an import into an existing item fills empty fields, appends bullets it doesn't already have (normalised-text match), keeps existing bullet IDs, versions and angles, and lists conflicting fields for the user instead of overwriting. Apply sends each matched item's `expected_revision`, is idempotent (a second apply of an `applied` import returns the same result), and match status gains `ambiguous` when several items could match.
4. **Per-point evidence.** Each imported bullet and field carries `evidence {source_sha256, page, text}` when it can be located in the source text. Points that can't be located are **flagged** in review ("not found in the PDF, check this"). Flags don't block, because it's the user's own resume. **After apply, evidence moves into the item:** each bullet and field keeps `provenance {origin: "import" | "user", import_id, evidence}`. Editing an imported point so that it no longer matches its evidence text sets `origin: "user"` while keeping `import_id` and the original excerpt, so "improved latency" → "improved latency by 80%" is no longer claimed as backed by the PDF. Confirmed snapshots keep bullet IDs, so fit analysis can look provenance up. Evidence isn't copied into snapshots.
5. **Basics are importable.** A `basics` candidate (name, headline, contact, summary, links) appears in the same review, with per-field conflict display against the current profile.
6. **Studio import isn't exact.** Entries the converter can't classify (custom sections, ambiguous headings) go to an "unsorted" group for the user to file or skip. Their text is preserved.
7. **Imports and the shared task design.** `profile_imports` gets `task_id` and captures exact input (upload `sha256` or document `id` + `revision`). It moves onto the shared `tasks`/`outbox` tables when those land in the AWS milestone. The API adds explicit JSON and text inputs, `POST …/discard` and `POST …/retry`.

### Other refinements

- **Dates** are `{ "start": "2023" | "2023-07", "end": "2024-02" | null, "current": true | false }`. `end: null` with `current: false` means unknown.
- **Naming:** the UI says *points* and *versions*; the schema says `bullets` and `alternatives` (so they aren't confused with `profile_versions`).
- **Skills in resumes** render as grouped lines ("Languages: Python, SQL") built from profile skills by category, and stay editable.
- **Archiving** a profile item never touches resumes that copied it. They just lose the profile helpers.
- **Privacy (PDPA):** *Export my profile* (`resume.json`) and *Delete my profile data*. See [Deletion scope](#deletion-scope).
- **Limits:** 50 items per kind, 30 points per item, 5 versions per point, 4,000 characters per point.
- **Demo data:** Alice's profile gets versions, mixed point types and a custom section.

## Principles

- A resume is a **copy**. Editing a resume never changes the bank, and editing the bank never changes a resume. The only route back is per point, through the point's context menu, confirmed by the user.
- Imported data is a **candidate** until the user accepts it. Nothing extracted from a PDF goes straight into the bank.
- Every row belongs to one user and is protected by PostgreSQL row-level security (RLS), as today.

## 1. How it is stored

### What exists today

| Table | Holds | Keep? |
|---|---|---|
| `profiles` | `draft` JSON with everything: name, headline, skills, experience, education, projects | Yes, but only for **basics** (name, headline, contact, summary, links) |
| `profile_versions` | Immutable confirmed snapshots used by recommendations | Yes, unchanged |
| `uploads` | Uploaded PDFs with `extracted_text` | Yes, plus a `(id, user_id)` unique key |
| `documents` | Resumes, as `content` JSON: sections → entries → bullets | Yes, plus optional source links on entries |

### New: `profile_items`

One row per experience, education, project, skill and so on. The common fields are columns; the fields that differ by kind live in a `data` JSONB column validated by a Pydantic model per kind. This matches how `documents.content` already works and avoids a table per kind.

```sql
CREATE TABLE profile_items (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users(id),
  kind        text NOT NULL CHECK (kind IN
                ('experience','education','project','skill','certification','award','volunteering','custom')),
  position    integer NOT NULL DEFAULT 0,        -- order within its kind on the profile page
  data        jsonb NOT NULL,                     -- kind-specific, see below
  tags        text[] NOT NULL DEFAULT '{}',       -- user labels such as 'backend', 'data', 'leadership'
  origin      text NOT NULL DEFAULT 'manual'      -- 'manual' | 'import'
                CHECK (origin IN ('manual','import')),
  import_id   uuid,                               -- set when origin = 'import'
  parent_id   uuid,                               -- project inside a job; FK (parent_id, user_id)
  revision    integer NOT NULL DEFAULT 1,         -- optimistic concurrency, bumps on every edit
  archived_at timestamptz,                        -- soft delete; resumes that copied it keep working
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, user_id)                            -- lets other tables reference (id, user_id) together
);
CREATE INDEX ix_profile_items_user_kind ON profile_items (user_id, kind, position);
CREATE UNIQUE INDEX uq_profile_skill_name ON profile_items (user_id, lower(data->>'name'))
  WHERE kind = 'skill' AND archived_at IS NULL;   -- no duplicate skills
```

`data` by kind (dates follow [Other refinements](#other-refinements): `YYYY` or `YYYY-MM`, plus `current`):

```jsonc
// experience
{ "title": "Data & Backend Engineer", "organisation": "Harbour Metrics", "location": "Singapore",
  "start": "2023-07", "end": null, "current": true, "summary": "",
  "bullets": [
    { "id": "b_7f3a", "text": "Cut p95 dashboard query time from 4.2 s to 0.9 s with partial indexes ...",
      "tags": ["backend"], "skills": ["PostgreSQL"],
      "alternatives": [ { "id": "v_1", "text": "Made analytics dashboards 4x faster, so daily ops reviews ran on live data",
                      "tags": ["data","impact"] } ] }
  ],
  "angles": [                                     // saved versions of this job; optional
    { "id": "a_backend", "name": "Backend focus", "title": "Backend Engineer",
      "summary": "", "picks": [ { "bullet_id": "b_7f3a" }, { "bullet_id": "b_91c2" } ] },
    { "id": "a_data", "name": "Data focus", "title": null,
      "picks": [ { "bullet_id": "b_7f3a", "alternative_id": "v_1" }, { "bullet_id": "b_44d0" } ] }
  ],
  "skills": ["Python","PostgreSQL"] }
// education
{ "qualification": "BSc Computer Science", "institution": "NUS", "start": "2018-08", "end": "2022-05", "current": false,
  "grade": "Honours (Distinction)", "bullets": [] }
// project
{ "name": "Job discovery pipeline", "role": "", "url": "", "start": null, "end": null, "bullets": [], "skills": [] }
// skill
{ "name": "PostgreSQL", "category": "tool", "level": "advanced" }   // category: language|framework|tool|domain|soft
```

Bullets sit inside their item, each with a stable `id`, because a bullet is never used without its parent and nothing needs to query bullets on their own. A separate `profile_bullets` table is the fallback if per-bullet search or tagging grows.

**One job, several stories.** The same role can be pitched differently per application, so an experience holds more than any one resume shows:

- **Bullets** are a pool of achievements, each with one or more **types** in `tags` (`backend`, `data`, `leadership`, `mentoring` and so on). One job usually mixes several kinds of work. The profile page groups a job's bullets by type, and filtering by type in Resume Studio shows only matching bullets across all jobs. A resume uses a subset.
- **Alternatives** (shown as "versions" in the UI) are other wordings of the *same* achievement, such as technical and business-impact versions. They share the bullet's `id`, so the profile counts one achievement, and a resume uses at most one wording of it.
- **Angles** are named, saved selections ("Backend focus", "Data focus"): which bullets, which alternative of each, and an optional title or summary override. An angle is a shortcut. Picking bullets by hand still works.
- **Projects inside a job:** a project item can set `parent_id` to an experience item (for example "Reporting migration" under Harbour Metrics). A resume shows it nested under the job or as a standalone project. `parent_id` uses a composite FK `(parent_id, user_id)`, so a child always has the same owner.
- **Promotions** (two roles at one employer) are separate experience items with the same `organisation`. The profile groups them, and a resume can show them under one company heading.

Embeddings use the main bullet text only, so alternatives don't count an achievement twice. Item-level embeddings can later score each bullet and alternative against a job to suggest an angle.

### New: `profile_imports`

One row per import attempt, holding its exact input, status and candidates. **The input is frozen when the import is created:** uploads are already immutable (bytes stored once, `sha256` recorded, re-upload refused), so they're referenced. A Studio document's `content` at the chosen revision, a `resume.json` body or pasted text is copied into `input_payload`, and `sha256` verifies it. Parsing and retries always read the frozen input, never the live document. `input_payload` is cleared when the import is applied or discarded, or after 30 days. Locally the parser runs inline. On AWS the work runs as a task on the shared `tasks`/`outbox` tables and the row links to it through `task_id` ([review fix 7](#review-fixes-folded-in)).

```sql
CREATE TABLE profile_imports (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users(id),
  source_type text NOT NULL CHECK (source_type IN ('upload','document','json_resume','text')),
  upload_id   uuid,      -- FK (upload_id, user_id) -> uploads(id, user_id)
  document_id uuid,      -- FK (document_id, user_id) -> documents(id, user_id)
  input_ref   jsonb NOT NULL,  -- {upload_id, sha256} | {document_id, document_revision, sha256} | {sha256}
  input_payload jsonb,         -- immutable copy of the input for document, JSON and text imports (≤ 1 MiB); null for uploads
  task_id     uuid,      -- shared tasks table once it exists (AWS milestone)
  status      text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','ready','failed','applied','discarded')),
  parser      text,      -- 'document-v1' | 'json-resume-v1' | 'heuristic-v1' | 'bedrock-<model>-v1'
  candidates  jsonb NOT NULL DEFAULT '[]',
  error_code  text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  applied_at  timestamptz
);
```

### Basics stay in `profiles.draft`

`profiles.draft` keeps `name`, `headline`, `email`, `phone`, `location`, `summary` and `links`. `profiles` also gains `bank_revision integer`, bumped by every basics or item change (see [review fix 1](#review-fixes-folded-in)), and `profile_epoch integer`, bumped by *Delete my profile data* (see [Deletion scope](#deletion-scope)). The arrays `skills`, `experience`, `education` and `projects` move into `profile_items` through a one-off data migration.

### Recommendations keep working

`build_profile_snapshot(db)` assembles the same dict shape that recommendations read today (`headline`, `summary`, `skills` as names, `experience` as `{role, company, dates, skills}`, `education`, `projects`) from basics plus active items. The ranking function in `recommendations.py` needs no change, **but the route does**: `GET /v1/recommendations` currently passes `profile.draft` straight into `rank_jobs` (`api/main.py`), and after the move `draft` holds only basics.

Recommendations are **owned by area 4** ([work split](../WORK-SPLIT.md)). This plan only guarantees their input; ranking decisions stay with them.

- **The one change we make to their code:** the route calls `build_profile_snapshot(db)` instead of reading `profile.draft`, with the regression test below. That keeps today's behaviour (the draft is ranked without confirming). We agree this one-line change with the area 4 owner before merging.
- **Suggested default (area 4 decides):** keyword ranking reads the live snapshot, so edits show up immediately; semantic ranking reads the confirmed snapshot (`profiles.confirmed_revision`), and *Update my matches* is the confirm action. Before the first confirm, ranking stays keyword-only as today.
- **Migration of revisions:** the data migration sets `profiles.bank_revision = profiles.revision`. Existing `profile_versions.revision` values and `profiles.confirmed_revision` keep their numbers and are reinterpreted as bank revisions, so existing confirmed snapshots stay valid. After the migration, `profiles.revision` only versions basics edits through `PUT /v1/profile`.
- **Test:** the migrated demo profile returns the same ranked jobs and reasons before and after the migration.

### Contract for other areas

These functions in `job_hunter/profile_bank/` are the **only** way other areas read profile data, so the bank's internal storage can change without breaking them:

| Function | Returns | Used by |
|---|---|---|
| `build_profile_snapshot(db) -> dict` | Today's dict shape (`headline`, `summary`, `skills`, `experience[{role, company, dates, skills}]`, `education`, `projects`), plus additive keys `bank_revision` and `bullets[{id, item_id, text, tags, skills}]` | Area 4 (recommendations), area 3 (tailoring) |
| `get_confirmed_snapshot(db) -> (version_id, revision, dict) \| None` | The active confirmed `profile_versions` row | Area 4 (semantic ranking), area 5 (fit analysis) |
| `profile_embedding_text(snapshot) -> str` | Versioned text for embedding, without contact fields | Area 4 |
| `get_bank(db)` and `get_bullet(db, item_id, bullet_id)` | Items with bullets, alternatives, tags and provenance | Area 3 (build plans), area 5 (evidence) |

- **Stability rule:** the snapshot shape only gains keys; it never renames or removes them. A breaking change needs a new `snapshot_version` and a heads-up in the team chat.
- **Fixtures:** `tests/fixtures/profile_snapshot_*.json` (empty profile, demo profile, profile with versions) let other areas test against realistic input without the bank tables.
- **Ownership:** the profile bank owns these functions and their tests. Area 4 owns `recommendations.py`, the ranking route's behaviour and the embedding pipeline. Area 3 owns `suggest_plan` strategies beyond `keyword-v1`. Area 5 owns fit analysis.

### Embeddings

*Owned by area 4; this section records the interface this plan assumes.*

The bank feeds the planned semantic ranking ([05](05-RECOMMENDATIONS.md), [CONTRACTS](CONTRACTS.md): one `vector(512)` space shared with jobs) through the same confirmed snapshot, so there is one source of truth for "what this user is":

| Level | Stored on | Built from | Used for |
|---|---|---|---|
| **Profile** | `profile_versions.embedding vector(512)` plus `embedding_model`, `embedding_dims`, `embedding_text_version`, `embedding_status` | `profile_embedding_text(snapshot)`: headline, summary, role titles, skills, and experience and project bullets. **No name, email, phone, links or location.** | Job recommendations (profile ↔ `jobs.embedding`) |
| **Item** (optional, later) | `profile_items.embedding vector(512)` plus the same metadata columns | Each item's title, organisation, bullets and skills | Picking the most relevant experiences and bullets for a job (area 3), and evidence for fit analysis (area 5) |

- `profile_embedding_text()` is a pure, versioned function next to `build_profile_snapshot()`, with unit tests that contact fields never appear in the output. Changing it bumps `embedding_text_version` and triggers re-embedding.
- **Confirm** creates the version, then queues `EMBED_PROFILE_VERSION` (inline locally with a fake model, SQS on AWS). Recommendations fall back to keyword ranking while `embedding_status` isn't `ready`, as they do today.
- Editing the bank doesn't re-embed. Only confirming does, so embedding cost follows explicit user actions, and a recommendation can always say which profile version it used.
- Vectors from different models or text versions are never compared. Jobs and profiles must share `embedding_model` and `embedding_dims`.

## 2. How to import from existing resumes

### Don't build a parser into our schema: parse into JSON Resume, then map

[JSON Resume](https://jsonresume.org/schema) (MIT, v1.0.0) is an open standard resume format that already has almost every field we need: `basics`, `work[]` (with `highlights[]` as bullets), `education[]`, `projects[]`, `skills[]`, `certificates[]`, `awards[]` and `volunteer[]`. Every importer produces JSON Resume, and **one small mapper** turns JSON Resume into `profile_items` candidates. That gives us:

- One mapper to write and test, instead of one per source.
- LLMs already know JSON Resume well, so extraction prompts are short and output is reliable.
- Free imports from people who already have a `resume.json`, and a free **export** of the bank as `resume.json`.
- **Export policy:** standard fields carry each point's main wording, so any JSON Resume tool can read the export. Everything JSON Resume doesn't model (alternatives, point types, angles, custom sections, provenance, parent links) goes under `meta.jobHunter`. Importing our own export restores it all, and other tools ignore it.
- Our extras (point types, alternatives, angles) are added after import. They aren't needed to read a resume.

### Sources

| Source | Path | Cost | Ship |
|---|---|---|---|
| A resume already in Resume Studio | `documents.content` → JSON Resume; unclassifiable entries go to an "unsorted" group | Free | First |
| A `resume.json` file | Validate against the JSON Resume schema, then map | Free | First |
| An uploaded PDF or pasted text | Text extraction → LLM extraction to JSON Resume → validate | Model cost per resume (Bedrock); free locally with Ollama | Second |
| Fallback when no model is configured | Small heuristic parser (headings, date ranges, bullet markers) → JSON Resume | Free | Second |

### Libraries checked (October 2026)

| Library | Licence | Status | Verdict |
|---|---|---|---|
| [pypdf](https://github.com/py-pdf/pypdf) | BSD | Already used | Keep for basic text |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | MIT | Active | **Use**: layout-aware text, handles two-column resumes better than pypdf; pure Python, fine on Lambda |
| [Instructor](https://github.com/567-labs/instructor) | MIT | Active | **Optional**: Pydantic-validated LLM output with retries, works with Bedrock, Anthropic and Ollama. Calling Bedrock's tool use directly is also fine. |
| [JSON Resume schema](https://github.com/jsonresume/jsonresume.org) | MIT | Active (moved to a monorepo in 2026) | **Use** as the interchange format |
| [Docling](https://github.com/docling-project/docling) | MIT | Very active | Good PDF → structured Markdown, but ships ML models; too heavy for Lambda. Revisit only if text extraction is the bottleneck. |
| [OpenResume](https://github.com/xitanggg/open-resume) | **AGPL-3.0** | Last push Oct 2024 | Its [documented parsing algorithm](https://www.open-resume.com/resume-parser) is a good reference for our fallback heuristics. Don't copy its code: AGPL would apply to our hosted service. |
| [pyresparser](https://github.com/OmkarPathak/pyresparser) | **GPL-3.0** | Stale since 2023 | Avoid: copyleft, old spaCy, weak on experience and education |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | **AGPL-3.0** | Active | Avoid for the same licence reason |
| [pyresume](https://github.com/wespiper/pyresume) | MIT | Small, last push Aug 2025 | Too new and unproven to depend on |

No free, maintained, permissively licensed library parses arbitrary resume PDFs well without a model. The LLM-to-JSON-Resume route is the reliable option, with a heuristic fallback so imports still work without one.

### Pipeline (pure functions, no AWS imports)

```python
def extract_text(pdf: bytes) -> ExtractedText: ...                       # pdfplumber; pages + line positions for evidence
def llm_to_json_resume(text: ExtractedText, model: ModelAdapter) -> dict: ... # Bedrock / Ollama / fake, same interface
def heuristic_to_json_resume(text: ExtractedText) -> dict: ...             # fallback, no model
def document_to_json_resume(content: dict) -> dict: ...                    # Resume Studio documents
def json_resume_to_candidates(resume: dict, text: ExtractedText | None) -> list[Candidate]: ...
def match_candidates(cands: list[Candidate], items: list[ProfileItem]) -> list[Candidate]: ...
```

- **Model adapter:** `MODEL_BACKEND=fake|ollama|bedrock`. Tests use `fake`, local development can use a free Ollama model, and AWS uses Bedrock. The prompt asks for JSON Resume only, the output is validated with Pydantic, and invalid output gets one retry before falling back to the heuristic parser. Resume text is treated as data and never as instructions.
- **Evidence, per point and field:** after extraction, each bullet and field is located in the original text (normalised fuzzy match) and gets `evidence {source_sha256, page, text}`, so the review screen can show "From the PDF: …". Anything that can't be located is flagged "not found in the PDF, check this" rather than trusted ([review fix 4](#review-fixes-folded-in)).
- **Matching:** each candidate is labelled `new`, `duplicate` (same organisation + title + start, or same skill name), `update` (same item, different bullets) or `ambiguous` (several items could match; the user picks), with the bank item it matches. Merging follows the additive rules in [review fix 3](#review-fixes-folded-in).
- **Basics** come through as one `basics` candidate with per-field conflicts against the current profile.
- `profile_imports.parser` records which path ran (`document-v1`, `json-resume-v1`, `heuristic-v1`, `bedrock-<model>-v1`), so import quality can be compared later.

Candidate shape:

```jsonc
{ "candidate_id": "c3", "kind": "experience", "data": { /* same schema as profile_items.data */ },
  "evidence": { "title": { "source_sha256": "…", "page": 1, "text": "Data Analyst, Straits Commerce  Jul 2022 – Jun 2023" },
                "bullets": { "b_1": { "page": 1, "text": "Developed SQL cohort analyses ..." }, "b_2": null } },  // null = flagged
  "match": { "status": "duplicate", "item_id": "…", "item_revision": 3 } }
```

**Flow:** upload or pick a resume → `POST /v1/profile/imports` → status `ready` with candidates → the review screen lists them with **Add**, **Merge into existing** or **Skip**, editable inline → `POST /v1/profile/imports/{id}/apply` (with each matched item's `expected_revision`) writes all accepted items in one transaction, bumps `bank_revision` and marks the import `applied`. A repeated apply returns the same result. Nothing is written to the bank before *apply*.

## 3. How the bank is used in resume drafts

### How the editor works today

- A resume is `documents.content`: contact fields, `summary`, and `sections[]`. Each section has a free-text `title` and `entries[]` (`heading`, `subheading`, `dates`, `bullets: string[]`).
- `SectionEditor` in `App.tsx` edits entries field by field. Bullets are textareas keyed by their **position**, with add and remove (no reorder). Pure helpers in `editor.ts` (`updateEntry`, `updateBullet`, …) have unit tests.
- Every change goes through `pushContent`: it records undo/redo history (50 steps), clears the review mark and autosaves after 700 ms with `expected_revision`. A 409 conflict keeps local edits and asks the user to reload.
- The server (`validate_document`) checks shapes and limits. It ignores extra keys and requires bullets to be strings.
- Sections have no type. "Experience" is only a title, so the editor can't tell which profile items fit a section.
- New resumes start blank, including contact details that the profile already has.

### Changes to fit the profile in

All additive. Old resumes keep working and need no migration.

```jsonc
// documents.content.sections[]
{ "id": "s1", "title": "Professional experience",
  "kind": "experience",                                   // new, optional: experience|education|projects|skills|custom
  "entries": [
    { "id": "e1", "heading": "Backend Engineer", "subheading": "Harbour Metrics · Singapore",
      "dates": "Jul 2023 – Present",
      "bullets": ["Built FastAPI services ...", "Made analytics dashboards 4x faster ..."],
      "source": { "item_id": "…", "item_revision": 4, "angle_id": "a_backend" },   // new, optional
      "date_range": { "start": "2023-07", "end": null, "current": true },          // new, optional: lets date_format re-render
      "bullet_sources": [ { "bullet_id": "b_1", "base_text": "Built FastAPI services ..." },
                          { "bullet_id": "b_7f3a", "alternative_id": "v_1", "base_text": "Made analytics dashboards 4x faster ..." } ] } ] }
                                                          // new, optional; same length as bullets, null = written here
```

- **`bullets` stays `string[]`**, so the preview, PDF renderer, validation and existing data don't change. `bullet_sources` sits alongside it. The `editor.ts` helpers that add, remove or **move** bullets keep both arrays aligned, with tests for that.
- **Edited** is `text != base_text`. It isn't shown as a badge. It only decides which context-menu options apply.
- **`kind`** tells the editor which profile items to offer. For old resumes it's inferred from the title ("Experience", "Work history" → `experience`) and saved on the next edit.
- **Contact and summary:** new resumes are pre-filled from profile basics, and the summary field gets **Use profile summary**.
- Because profile actions go through `pushContent` like typing does, **undo/redo and autosave cover them**. Undoing an insert just works.

### In the editor

*The mockup's screen 3 predates the context-menu decision; this text is current.*

**Rule: once content lands in a resume, it belongs to that resume.** Rewording, trimming, reordering, deleting, changing dates and writing new points are ordinary edits. They autosave to the resume and never change the profile.

Per entry linked to a profile item:

- Each point is editable. **N versions** lists the other versions of that achievement, and choosing one swaps the text.
- **More from this job in your profile** lists unused points with **+ Add**.
- **Point controls, always visible** (not only on hover), beside each point's text box:

  ```
  [ ↑ ] [ ↓ ]  Built FastAPI services and PostgreSQL data models …        [ ⋮ ]
  ```

  - **↑ / ↓ move the point** within its entry. Reordering points is a key feature. Today's editor can't do it, so `editor.ts` gains `moveBullet()`, which moves the matching `bullet_sources` entry too (unit-tested). The buttons disable at the top and bottom. Keyboard: Alt+↑ / Alt+↓ while in the point.
  - **⋮ (more actions) opens the point menu.** It's the standard per-item "more" symbol; ☰ is avoided because it reads as site navigation. Tooltip "More actions", screen-reader label "More actions for this point". **Right-click opens the same menu**, so both routes always show identical options. The Menu key or Shift+F10 also opens it.
  - There is still **no "save to profile" button** on the point. Saving back lives inside the menu.

- **Point menu.** One level of submenu, never deeper:

  ```
  ├─ Versions ▸           Version 1: "Cut p95 query time…"  ✓   (swap the wording in this resume)
  │                       Version 2: "Made dashboards 4x faster…"
  ├─ Move up / Move down
  ├─ Remove from resume
  ├─ ───────────
  └─ Save to profile ▸    Update in profile          (only if it came from the profile)
                          Save as new version        (only if it came from the profile)
                          Save as new point…         (asks which experience)
  ```

  - **Top level acts on this resume** (frequent). **Save to profile ▸ acts on the profile** (rare), placed last so it isn't hit by accident.
  - **Options that don't apply are hidden, not greyed out.** A point written in the resume shows only *Save as new point…*.
  - **Update in profile** replaces **the version the point came from** (the main wording, or the alternative recorded in `bullet_sources[].alternative_id`). The replaced wording is kept as another version, so nothing is lost.
  - **Order of writes and failure handling:** (1) the profile write goes to the API with the item's `expected_revision`, taken from `source.item_revision` or the latest profile fetch. A 409 shows "This point changed in your profile since you added it", with the current profile text and the options *Save as new version* or *Cancel*. Stale resume wording never silently replaces a newer profile point. (2) Only after a 2xx does the editor update `base_text` and `source.item_revision` through `pushContent`, so it autosaves like any edit. If that autosave fails, the point simply still counts as edited and is offered again, which is harmless. The confirmation appears only after step 1 succeeds.
  - **Version limit (5):** if keeping the old wording would exceed it, the save opens a small chooser: *"Your profile keeps 5 versions of a point. Replace which one?"*, with *Don't keep the old wording* as an option. It never drops one silently.
  - **Save as new point…** opens a small confirm box: *which experience* (pre-selected when linked; otherwise pick one or "new experience").
  - **Undo is separate from the editor's undo stack.** The editor's Ctrl+Z covers resume edits only. Each profile save shows a toast with **Undo**, which calls a revert with the item's new `expected_revision`. If anything changed the item since, the revert returns 409 and the toast says "Can't undo: this point changed since". Reverting never overwrites later edits. Only points can be saved back.
  - **Touch:** the ⋮ button (or a long-press) opens the same options as a bottom sheet, with "Save to profile" as a section instead of a submenu. ↑ / ↓ stay as buttons.
  - **Keyboard:** arrow keys move, Right opens the submenu, Esc closes. Built with ARIA `menu`/`menuitem` roles.
- *Later:* **Updated in profile** with **Pull update**, using `base_text` for a 3-way merge that never overwrites customised wording.

Per section: **reorder**, **hide** (`hidden: true`, kept but not rendered) and **delete**. A section with a `kind` has **Add from profile**. Custom sections ("Fun facts", "Interests") are free-form, and their points can be saved to a `custom` profile item.

### Resume style and date formats

Per-resume settings in the existing `layout` JSON, autosaved like font size today:

| Setting | Values |
|---|---|
| `date_format` | `Jul 2023` · `July 2023` · `07/2023` · `2023` |
| `present_label` | `Present` · `Current` · `Now` |
| `heading_style` | `rule` · `small-caps` · `bold` |
| `accent_color` | Small palette (black, navy, teal, maroon) to stay readable when printed |
| `bullet_char` | `•` · `–` · `▪` |
| `header_align` | `center` · `left` |
| `contact_separator` | `·` · `|` · new line |
| `section_spacing` | `compact` · `normal` · `airy` |
| `skills_layout` | `inline` · `grouped` · `columns` |

Entries with `date_range` re-render in the chosen format. Dates typed by hand stay as typed: editing an entry's date text **removes its `date_range`**, so a later format change can't bring back the old dates. The entry then shows its typed text in every format, and the date field offers *Use structured dates* to restore a picker. Both the live preview and the server PDF renderer read the same settings.

### Resume defaults per user

A new `user_settings` table (one row per user, RLS like every user table) holds `resume_defaults` JSONB and a `revision`. It's kept separate from `preferences`, which holds job-search preferences read by recommendations and is replaced wholesale on save.

```jsonc
// user_settings.resume_defaults
{ "template": "classic",
  "layout": { "font_family": "latex", "font_size": 11, "margin": 18, "line_spacing": 1.15, "page_size": "A4",
              "date_format": "Jul 2023", "present_label": "Present", "heading_style": "rule",
              "accent_color": "navy", "bullet_char": "•", "header_align": "center",
              "section_spacing": "normal", "skills_layout": "grouped" },
  "sections": [ { "kind": "skills" }, { "kind": "experience" }, { "kind": "projects" },
                { "kind": "education" }, { "kind": "custom", "title": "Fun facts", "hidden": true } ],
  "header_fields": ["email", "phone", "location", "links"],
  "build": { "points_per_item": 4, "include_profile_summary": true } }
```

- **Applied once, when a resume is created** (blank, free build or build for a job). The resume then owns its copy, and changing defaults never restyles existing resumes.
- **Editor style panel:** **Save as my default** (stores this resume's `template`, `layout` and section order) and **Apply my defaults** (an ordinary undoable edit).
- **Missing keys** fall back to today's built-in defaults, so users without settings see no change.
- **API:** `GET /v1/settings` and `PUT /v1/settings` with `expected_revision`.
- *Later:* named style presets and a default template per job type.

### Templates and the renderer

Templates only read resume content and `layout`, they never own data: `render(content, template, layout) -> PDF`. The built-in ReportLab templates sit behind that interface today.

**Decision: built-in templates stay on ReportLab. Power-user templates (future) use [Typst](https://typst.app).**

- **Why Typst over LaTeX:** compiles in milliseconds, has no shell-escape equivalent, and has existing resume templates. It can reuse the bundled Latin Modern fonts for a LaTeX look. A TeX installation would be hundreds of MB on Lambda, and user LaTeX needs heavy sandboxing.
- **Packaging:** the [`typst` Python package](https://github.com/messense/typst-py) (Apache-2.0, actively maintained) ships prebuilt Linux x86_64 and arm64 wheels. It installs with `pip` into the existing backend image, with no separate binary.
- **How it would work:** a user template is a Typst file that receives resume `content` and `layout` as JSON input. `render()` picks ReportLab or Typst by template type.
- **Guardrails, even though Typst is safer:** compile with only the bundled fonts and the template itself (no other file access, no network), with time and page limits, in the API Lambda's `/tmp`.
- **Exact live preview later:** [typst.ts](https://github.com/Myriad-Dreamin/typst.ts) (Apache-2.0) compiles Typst in the browser, so a Typst template's preview could match its PDF exactly.

Nothing about templates changes the data model.

### Server checks

`validate_document` gains: `kind` must be a known value; `hidden` is a boolean; `bullet_sources` must be the same length as `bullets`; new `layout` keys must use the listed values; every `source.item_id` must belong to the user. RLS hides other users' items, so a foreign ID is rejected as not found.

### Code layout

`App.tsx` holds most of the UI in one file. Before adding the profile page and these panels, move `Studio`, `SectionEditor` and `ResumePreview` into `src/studio/` and the new profile page into `src/profile/`. That limits merge conflicts with the other areas (see the [work split](../WORK-SPLIT.md)).

### Two ways to build a resume

Both paths produce the same thing: a **build plan** (which items, which angle, which bullets and wordings, in what order), turned into an ordinary `documents` row whose entries carry `source` links. **Add from profile** in the editor produces a plan fragment too, so there is one code path. A new resume starts from the user's [resume defaults](#resume-defaults-per-user) (template, style, section order).

```jsonc
// build plan, the body of POST /v1/documents/from-bank
{ "title": "Backend Engineer – Stripe", "template": "classic", "job_id": "…" /* or null */,
  "summary": { "mode": "profile" },                      // or { "mode": "custom", "text": "…" }
  "sections": [
    { "kind": "experience", "items": [
        { "item_id": "…", "angle_id": "a_backend",
          "picks": [ { "bullet_id": "b_7f3a" }, { "bullet_id": "b_91c2", "alternative_id": "v_2" } ] } ] },
    { "kind": "skills", "skill_ids": ["…", "…"] } ] }
```

| | **Free build** | **Build for a job** |
|---|---|---|
| Starts from | Resume Studio → *New resume* → *From my profile* | A job card or tracker application → *Prepare resume* (today's tailored-copy flow) |
| Choose | Template, and optionally a focus (point types such as `backend`; angles later) | Template; the job is fixed |
| Pre-selection | Everything matching the focus, newest first, capped per job (`points_per_item` from resume defaults, default 4) | **Suggested plan** ranked against the job, with a reason for each pick |
| Extra panel | None | Job requirements: skills covered by your profile, skills missing, and *Add to profile* for each gap you actually have |
| Result | General resume, `job_id = null` | Resume with `job_id`, ready to attach to the application |

A third start, **Copy an existing resume**, already exists and keeps working.

**Suggested plan** = `suggest_plan(job, bank, strategy) -> (plan, reasons)`, a pure function:

- `keyword-v1` (now, free): score each bullet and item by overlap between its skills and tags and the job's skills and title, reusing the skill normalisation in `recommendations.py`. Reasons are concrete, such as "matches PostgreSQL, FastAPI".
- `embedding-v1` (later): cosine similarity between item-level embeddings and the job embedding.
- `llm-v1` (later): the model picks and orders items from the bank, citing IDs. It can only select existing items, never invent them.

The user always sees the suggestion and confirms it before a document is created. `POST /v1/resume-builds/suggest {job_id}` returns the plan without saving anything.

### AI features later: where they plug in

Each one sits behind the same model adapter (`fake | ollama | bedrock`) and produces **suggestions the user accepts**. Nothing AI-written lands in the profile or a resume without a click. Each records its model and prompt version.

| Feature | Input | Output | Stored as | Area |
|---|---|---|---|---|
| Import extraction | Resume text | JSON Resume | Import candidates | 2 |
| Pick for a job | Job + bank | Build plan with reasons | Not stored until accepted | 3, 4 |
| Reword for a job | One bullet + job | New wording of that bullet | An **alternative** with `origin: "ai"`, `model`, `accepted_at` | 3 |
| Tailored summary | Basics + chosen items + job | Summary paragraph | Resume `summary` (or a saved summary alternative) | 3 |
| Fit analysis | Job + bank | Strengths and gaps, each citing bullet IDs | Fit analysis record ([06](06-APPLICATION-PREPARATION.md)) | 5 |
| Gap prompts | Missing job skills | "Have you used Kubernetes?" questions | New bank items, if the user answers | 2, 5 |

**Guardrails** shared by all of them:

- **Grounding:** generated wording may only use facts from its source bullet or item. A validator rejects new numbers, organisations, dates or skills that aren't in the source, and the UI shows the source next to the suggestion.
- **Allowance:** AI actions count against the monthly allowance in [CONTRACTS](CONTRACTS.md) (distinct jobs per month), checked in the same transaction that queues the task.
- **Async:** each one is a task row processed inline locally and by the personal-task SQS worker on AWS, the same pattern as imports.

### Deletion scope

*Delete my profile data* (`DELETE /v1/profile/data`, with a typed confirmation) runs in one transaction:

| Deleted | Kept, and why |
|---|---|
| Basics (`profiles.draft` reset to `{}`), all `profile_items` (hard delete, including archived) | Resumes (`documents`) and their exports: separate documents the user manages and deletes in Resume Studio. The dialog says so and links there. |
| All `profile_versions` with their embeddings; `confirmed_revision` set to null | Application records and attached PDFs: deleted with the application. |
| All `profile_imports`, including `input_payload` | `user_settings` (style preferences, not profile facts); offered as a checkbox in the same dialog. |
| Uploaded resume files and their `uploads` rows (bytes removed from disk or S3) | |

- `bank_revision` increments, and a `profile_epoch` counter on `profiles` increments too. Every import, embedding or AI task records the epoch it started under and discards its result if the epoch has changed, so a pending worker can't recreate deleted data.
- Resumes keep their text but lose profile helpers, because their `source.item_id` no longer resolves. That's the same behaviour as archiving.

## 4. Keeping users separate

The same mechanism as every existing user table, so local and cloud behave identically:

1. **`user_id` on every row** of `profile_items`, `profile_imports` and `user_settings`.
2. **RLS**: `ENABLE` and `FORCE ROW LEVEL SECURITY` with the existing `tenant_isolation` policy (`user_id = current_setting('app.user_id')::uuid` for both `USING` and `WITH CHECK`). The API connects as `jobhunter_app`, which cannot bypass RLS. A forgotten `WHERE user_id = …` therefore returns nothing rather than another user's data.
3. **Composite foreign keys** `(upload_id, user_id)` and `(document_id, user_id)`, so an import can't point at someone else's file even through a bug. This needs `UNIQUE (id, user_id)` on `uploads` and `documents`, the same pattern `applications` → `document_exports` already uses.
4. **Identity comes from the server**, never from a request body. Locally that's the dev header. On AWS, `app.user_id` is set from the verified Cognito `sub` and nothing else changes.
5. **Files:** S3 keys are prefixed `users/{user_id}/…`, and downloads check ownership in the database first.
6. **Tests:** extend `tests/integration/test_tenant_isolation.py` so Casey can't list, read, edit or import from Alice's items or uploads, and can't put Alice's `item_id` in a resume `source`.

## API

| Method and path | Purpose |
|---|---|
| `GET /v1/profile/bank` | Basics plus all active items, grouped by kind |
| `POST /v1/profile/items` | Create an item |
| `PATCH /v1/profile/items/{id}` | Edit, with `expected_revision` (409 on conflict) |
| `DELETE /v1/profile/items/{id}` | Archive (soft delete) |
| `PUT /v1/profile/items/order` | Reorder within a kind |
| `POST /v1/profile/confirm` | Existing route, now with `expected_bank_revision`; snapshots the whole bank (*Update my matches*) |
| `POST /v1/profile/imports` | Start an import from `upload_id`, `document_id`, a `resume.json` body or pasted text |
| `GET /v1/profile/imports/{id}` | Status and candidates (the frontend polls this on AWS) |
| `POST /v1/profile/imports/{id}/apply` | Apply the add, merge and skip decisions in one transaction; idempotent |
| `POST /v1/profile/imports/{id}/discard`, `…/retry` | Drop an import, or re-run a failed one |
| `GET/PUT /v1/settings` | Resume defaults, with `expected_revision` |
| `POST /v1/documents/from-bank` | Create a resume from a build plan |
| `POST /v1/resume-builds/suggest` | Suggested build plan and reasons for a job (saves nothing) |
| `GET /v1/profile/export.json` | The bank as JSON Resume; see export policy in §2 |
| `DELETE /v1/profile/data` | Delete all profile data; see [Deletion scope](#deletion-scope) |
| `POST /v1/profile/items/{id}/revert` | Undo a save-back, with `expected_revision` |
| `POST /v1/profile/items/{id}/bullets/{bullet_id}/alternatives` | Add a version (user-written now, AI-suggested later) |
| `PUT /v1/profile/items/{id}/bullets/{bullet_id}` | Update a point's main wording; the old wording becomes a version |
| `POST /v1/profile/items/{id}/bullets` | Add a new point to an item |

Existing `GET/PUT /v1/profile` keep serving basics, so the current UI keeps working during the change.

## Cloud readiness

- The parser and matcher are pure functions in `job_hunter/profile_bank/`. Routes stay thin.
- An import is a database row with a status. Locally the route parses inline and returns `ready`. On AWS the route returns `pending` and publishes to SQS, a worker runs the same `run_import(import_id)`, and the UI polls. The client code is identical in both cases.
- No new infrastructure beyond what's already planned: RDS tables, the S3 uploads bucket, and the existing personal-task queue.

## Build order

1. **Storage:** migration for `profile_items`, `profile_imports` and `user_settings` with RLS; `profiles.bank_revision` and `profile_epoch`; the `(id, user_id)` unique keys on `uploads`/`documents`; the data migration from `profiles.draft`; embedding metadata columns on `profile_versions`. CRUD and settings APIs, confirm with `expected_bank_revision`, the [contract functions](#contract-for-other-areas) with snapshot fixtures, and the one-line recommendations route change (agreed with area 4). Unit and tenant-isolation tests, plus a test that recommendations return the same results for the migrated demo profile. Seed Alice's richer demo profile.
2. **Profile page** (in `src/profile/`, after moving Studio components into `src/studio/`): basics, experience, education, projects, skills and custom sections, editable in place; points with types and versions; *Update my matches*; a list of the user's uploaded and Studio resumes; export and delete.
3. **Import:** the JSON Resume mapper and review screen (basics, per-point evidence, additive merge, ambiguous matches), fed first by Studio resumes and `resume.json` files, then by PDFs (pdfplumber + model adapter, heuristic fallback).
4. **Use in resumes:** build plans, `POST /v1/documents/from-bank`, free build and build-for-a-job with `keyword-v1` suggestions, resume defaults applied on create, **Add from profile** per section, versions per point, `bullet_sources` with `base_text`, persistent ↑ / ↓ / ⋮ point controls, and the point menu (right-click = ⋮).
5. **Editor flexibility:** section hide, date formats with `date_range`, the style settings, and **Save as my default** / **Apply my defaults**, in both the live preview and the ReportLab renderer.
6. **Later:** angles, Pull update (3-way merge), async imports on SQS, item-level embeddings, AI suggestions (area 3/5), named style presets, Typst power-user templates.
