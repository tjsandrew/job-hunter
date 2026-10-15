# Handoff 10 — Profile bank step 1

Implemented 14 October 2026 on `profile-bank`. Local commits only; no push or PR. This delivers storage, the backend API and the read contract. Imports/parsing, frontend/editor changes, build plans, rendering extensions, model computation and AWS remain later work.

## What was built

- Migration `0010_profile_bank`: owned bank/import/settings tables, composite owner FKs, indexes, forced RLS, bank revision/epoch and profile embedding metadata. The legacy transform keeps basics in `draft`, normalises dates, retains unknown date text and assigns deterministic item/point IDs. Existing confirmation revision numbers remain unchanged.
- Pure Pydantic item schemas for all eight kinds, date helpers, legacy migration transform, stable snapshot assembler and versioned contact-free embedding text.
- Public database readers: `build_profile_snapshot`, `get_confirmed_snapshot`, `get_bank`, `get_bullet`. Snapshots retain legacy keys/date spelling and add `bank_revision` and flat main-wording `bullets`.
- Thin HTTP routes for owned item CRUD, reorder, points/alternatives, revision-checked restore, settings, whole-bank confirmation and profile deletion. Mutations serialize using the owned user/profile row and bump the bank revision within the same transaction. Settings changes do not bump the bank.
- The sole recommendation behaviour change is its input expression: the route now calls `build_profile_snapshot(db)`. `recommendations.py` is unchanged; keyword ranking still uses live facts.
- Alice's fresh seed includes two alternative wordings of one point, backend/data/leadership tags and a custom section. Casey has no bank items. Existing users are not overwritten on startup; `make reset-demo` explicitly rebuilds Alice's richer demo bank after saving a backup.

## Files changed

- `backend/migrations/versions/0010_profile_bank.py`, `backend/src/job_hunter/domain/models.py`
- `backend/src/job_hunter/profile_bank/{__init__,schema,dates,migration,snapshots,services,settings}.py`
- `backend/src/job_hunter/api/{main,profile_bank}.py`, `backend/src/job_hunter/adapters/database.py`
- `backend/src/job_hunter/{demo,seed}.py`, `scripts/setup_demo_workspace.py`
- `backend/tests/test_profile_bank.py`, `backend/tests/test_profile_bank_regression.py`, `backend/tests/integration/test_profile_bank_api.py`, `backend/tests/integration/test_tenant_isolation.py`
- Four fictional fixtures in `backend/tests/fixtures/`: the three snapshot contracts plus the synthetic recommendation baseline
- `scripts/check_profile_bank_migration.py`, `contracts/openapi.json`, `docs/design/CONTRACTS.md`, this handoff and `10-profile-bank-ranking-evidence.json`

## API contract for step 2

All paths start `/v1`; errors use the existing `error.code/message/request_id/details` envelope. Foreign private IDs return 404. Revision conflicts return 409 `REVISION_CONFLICT`. Limits/invalid input return 422.

| Operation | Body / result |
|---|---|
| `GET /profile/bank` | `{basics, items: [...], grouped: {kind: [...]}, bank_revision, confirmed_revision, profile_epoch}` |
| `POST /profile/items` | `{kind, data, tags?: [], parent_id?: null}` → 201 item |
| `GET/PATCH /profile/items/{id}` | PATCH `{expected_revision, data?, tags?, parent_id?}` → item; `data` replaces the item's data, not a partial nested patch |
| `DELETE /profile/items/{id}` | Archive; optional query `expected_revision`; returns item |
| `PUT /profile/items/order` | `{kind, item_ids, expected_bank_revision}`; IDs must be all active items of that kind, exactly once → bank |
| `POST /profile/items/{id}/bullets` | `{expected_revision, text, tags?, skills?}` → updated item |
| `PUT /profile/items/{id}/bullets/{bullet_id}` | `{expected_revision, text, alternative_id?}`; null/missing alternative ID updates main wording; old text becomes an alternative |
| `POST /profile/items/{id}/bullets/{bullet_id}/alternatives` | `{expected_revision, text, tags?, skills?}` → updated item |
| `POST /profile/items/{id}/revert` | `{expected_revision, data, tags?, parent_id?}`; restore the client-held previous item state, validated like PATCH |
| `GET/PUT /settings` | PUT `{expected_revision, resume_defaults}`; missing row reads `{resume_defaults: {}, revision: 0}` |
| `GET/PUT /profile` | PUT `{expected_revision, draft}` for basics only; GET also supplies bank revision/epoch; accepts legacy `display_name` |
| `POST /profile/confirm` | `{expected_bank_revision}` → `{confirmed, revision, bank_revision, profile_version_id, embedding_status}` |
| `DELETE /profile/data` | `{confirmation: "DELETE", delete_settings?: false}` → `{deleted, bank_revision, profile_epoch}` |

A point allows five total wordings: its main text plus four alternatives. An update that cannot preserve the old wording returns 422 `POINT_VERSION_LIMIT`; this step does not silently evict versions or implement the later replacement chooser. There are at most 50 active items per kind, 30 points per item, and 4,000 characters per wording. Only projects may reference an owned active experience as a parent.

Confirmation can reuse the immutable snapshot at the same bank revision, but never at an older bank revision. New snapshots report `embedding_status: unavailable` because no embedding adapter/worker is implemented. `get_confirmed_snapshot` returns `(version_id, revision, data)` or `None`; `get_bullet` returns the owned active point including its alternatives/provenance.

## Validation

Commands ran from the repository root unless noted:

| Command | Result |
|---|---|
| `docker compose up -d --no-build` | Existing pre-migration stack started for the HTTP baseline |
| `make up` | Final API/web images built; PostgreSQL/API health checks passed |
| `make test-backend` | **124 passed**, 3 existing framework deprecation warnings, including real PostgreSQL/RLS tests with `RUN_DB_INTEGRATION=1` |
| `make test-web` | **16 passed** in 2 test files; TypeScript and Vite production build passed |
| `make smoke` | PASS: HTTP identities, recommendations, persistence, isolation, revision conflicts, PDFs, review-gated exports and immutable uploads |
| `docker compose run --rm --no-deps -v "$PWD/scripts:/app/scripts:ro" api python /app/scripts/check_profile_bank_migration.py` | PASS: true legacy 0009 → 0010, exact legacy snapshot/revisions, richer downgrade/upgrade row equality, stable IDs/provenance/nested parents, vector(512), three forced RLS policies; disposable database removed |
| `python3 -m compileall -q backend/src/job_hunter/profile_bank backend/src/job_hunter/api/profile_bank.py scripts/check_profile_bank_migration.py` | PASS |
| `git diff --check` | PASS |

The first full backend attempt failed collection because the pure and integration test files shared the basename `test_profile_bank.py`. Renaming the integration file resolved it; a subsequent run passed 122 tests, and the final run passed 124 after adding limits/settings regressions. Subagents also ran focused pure tests (38 passed) and final API integration tests (8 passed) with readonly source/test mounts and locked `pytest`/`httpx` installed into disposable containers. An initial readonly-source `pip install .[test]` attempt failed writing package metadata; installing only the test dependencies resolved it.

### Recommendations before/after

Before rebuilding/migrating, Alice's `GET /v1/recommendations?limit=100` returned **71** jobs. Captured before/after full responses at `/tmp/profile-bank-http-before.json` and `/tmp/profile-bank-http-after.json`; an assertion compared every ordered job ID and every `reasons` list. **All 71 were unchanged.** The committed [ranking evidence](10-profile-bank-ranking-evidence.json) retains the before projection and equal before/after SHA-256 digests. The synthetic regression fixture additionally checks complete rank outputs for both the migrated legacy profile and the richer new demo; an API integration test checks the route against the legacy ranker on the actual database pool.

## Decisions, deviations and open questions

- Historical migration 0001 imports current ORM metadata. Migration 0010 therefore handles already-created columns/tables on a fresh installation. The migration check explicitly removes these future additions to emulate a true old schema before testing the upgrade.
- A downgrade cannot represent alternatives, custom/archived items, settings/imports or embedding metadata in the old arrays. It preserves them in the reserved `draft._profile_bank_v1` marker alongside restored legacy arrays. Upgrading removes the marker and restores the full data. This is a rollback/round-trip mechanism; reconciling edits made with the old application while downgraded is not implemented.
- `user_settings` uses `user_id` as its PK plus a UUID `id` and `UNIQUE(id,user_id)`, preserving one row/user while satisfying the requested owner-key convention. Imports also store `profile_epoch` for later worker fencing.
- Revert uses a validated client-held prior snapshot, since no item history table is in the agreed schema. It requires the current expected revision and increments revisions; the frontend must keep the prior data for its Undo toast. It is not a server-generated historical lookup.
- Database deletion commits before unlinking upload files so a failed DB transaction cannot destroy bytes. Normal deletion is tested, including retained resumes/application PDFs and optional settings deletion. Filesystem and PostgreSQL cannot commit atomically: an unlink failure is logged and requires local operator cleanup; durable retry for storage cleanup is still needed before a production cloud deletion promise.
- The new basics and confirmation contracts deliberately reject the old form's `skills` array and `expected_revision` confirmation body. **The existing profile screen needs step 2 adaptation**; passing web unit/build checks does not establish that screen's old save/confirm flow still works. No frontend source changed in this step.
- Evidence stays with live bank items rather than confirmed snapshots, as the agreed design specifies. Historical evidence lookup after a later edit/deletion is an open design question for fit analysis; consumers must not present current provenance as proof of an older snapshot.
- Empty/migrated snapshots, source IDs, dates and embedding text are covered by fixtures/tests. Import status/schema fields are storage preparation only; no import routes or parser are delivered here.

## Step 2 and portability

Use `contracts/openapi.json` and the snapshot fixtures to adapt the profile page and client types. Read/write basics separately from items, use `bank_revision` for confirmation, and preserve item revisions/prior snapshots for edits/undo. A profile save does not confirm; keyword matching still follows the live snapshot. Settings only store defaults here: no new style controls or rendering are implemented.

Pure schemas/transforms/snapshot/embedding-text functions and transactional services are shared backend code, without FastAPI or AWS dependencies in the domain package. The existing local identity/PostgreSQL/filesystem adapters remain active. No AWS adapters, task dispatch, model computation, Cognito, S3 or SQS behaviour was built or verified. Cloud portability is partially verified by PostgreSQL/RLS and isolated domain boundaries; storage cleanup retries, task epoch checks/leases, real-service auth/ownership, packaging, timeout and cost checks remain for the AWS milestone.

## Step 2 — Profile page and step 1 follow-ups

Implemented 14 October 2026 on `profile-bank`, locally only. The initial Studio/Profile extraction is its own commit (`76a9e6d`), with all 16 original frontend tests and the production build passing before feature work.

### Built

- Moved Studio, SectionEditor, ContactEditor and ResumePreview into `apps/web/src/studio/`; ProfileView into `src/profile/`; identical shared UI helpers into `src/ui.tsx`.
- Replaced the old profile form with a compact basics card and explicit Save/Cancel editor, structured item sections, grouped point types, points/versions, projects nested beneath experiences, categorized skill chips, revision-checked reorder, archive/Undo, and Update my matches. Skills and other bank arrays are no longer sent through the basics endpoint.
- Added typed bank/item/point/settings/confirmation/deletion/export/upload client functions and types. Profile writes are explicit; errors are displayed, 409s reload current data and announce "This changed elsewhere, reloaded". Basic and skill conflict tests verify that stale edits are not retried or silently written. The item editor clears legacy unknown-date display text when structured dates are changed.
- Kept job preferences, PDF upload and extracted-text review. Your resumes lists owned source PDFs and Studio documents. Original downloads use the API client so the active local identity is included; Studio links open through the existing Studio initialization path. Import controls are disabled and labelled "Import (coming soon)".
- Added the typed DELETE dialog, deletion/retention explanation, required `DELETE` input and optional style-default deletion. Hard deletion is tested with isolated fictional users, not performed on Alice's shared demonstration workspace during browser checks.
- Added pure JSON Resume v1 export and `GET /v1/profile/export.json` with `profile.json` attachment disposition. Standard fields contain main wordings; `meta.jobHunter` preserves active bank items, alternatives, tags, parents, custom sections, source provenance and original basic values. Tests validate output against the pinned official JSON Resume v1 schema, offline.
- Added `GET /v1/uploads` (up to 100 latest owned uploads) and protected original-PDF download to support the existing-resume list.
- Fixed migration tenant enumeration and per-user context before data reads/writes, including downgrade. The DDL migration discovers IDs through a temporary SELECT-only policy scoped to its own role, removed immediately and within the same transaction. Seeding flushes each user's pending facts before switching tenant context. Existing direct demo script writes already set tenant context and required no further change.
- Added a restricted non-superuser/non-BYPASSRLS/non-owner integration fixture to test the real data-migration helper and seed. Neither operation relies on local superuser bypass.
- Added `make openapi` and a stable comparison test that reports "run `make openapi`" for drift. Removed only the unused profile variable from the recommendation route; ranking behaviour/functions are unchanged.

### Files changed

`Makefile`; `backend/migrations/versions/0010_profile_bank.py`; backend `seed.py`, `api/main.py`, `api/profile_bank.py`, `profile_bank/services.py`, new `profile_bank/export.py`; backend OpenAPI/RLS/export/API tests and pinned schema fixture; `contracts/openapi.json`; frontend `App.tsx`, `api.ts`, `types.ts`, `ui.tsx`, `studio/*`, `profile/{ProfileView,form}.tsx/ts`, new `profile/profile.css` and `profile/ProfileView.test.tsx`, updated `App.test.tsx` and new `api.test.ts`; this handoff and desktop/mobile screenshot evidence.

### Commands and results

| Command/check | Result |
|---|---|
| `make test-web` after pure extraction | 16 passed; TypeScript and production build passed |
| `make openapi` | Regenerated contract from the current readonly backend source mount |
| `make up` | API/web rebuilt, database and API health checks passed |
| `make test-backend` | **139 passed**, 3 existing deprecation warnings; includes RLS restricted-role writes, export/schema/tenant tests, archive restore/cap/conflicts, promotion at the version limit contract drift and source-PDF list/download ownership |
| `make test-web` final | **30 passed in 4 files** (12 profile cases, 2 API wire-contract cases, and the original 16); TypeScript and Vite production build passed |
| `make smoke` | PASS: all existing HTTP smoke checks |
| `docker compose run --rm --no-deps -v "$PWD/scripts:/app/scripts:ro" api python /app/scripts/check_profile_bank_migration.py` | PASS after RLS fixes: isolated migration/downgrade/re-upgrade, unchanged legacy contract and complete rich-data roundtrip |
| `git diff --check` | PASS |

Focused subagent commands used readonly source/tests mounts and `pip install -q -c requirements.lock pytest httpx`: restricted role tests **2 passed**; exporter plus profile API tests **19 passed**. Early new frontend runs found missing mock API methods/old UI assertions and a mock fixture typing error; those were corrected. The final run passed all required profile and original Studio tests. No new production UI library or model dependency was added.

The running Alice recommendation response was projected to `{job_id,reasons}` and compared to `10-profile-bank-ranking-evidence.json`: **all 71 entries remain identical**, including after the browser point/version edits and restoration of the original item order.

### Browser check

Used the running local app in Chrome with Alice's fictional profile. Added a clearly labelled synthetic browser-check point (the migrated existing bank had no points), edited it explicitly, added a version, moved the experience down and back up, confirmed the whole bank and exported. Wording edits preserved prior text, the count reached three versions, reorder persisted, and confirmation showed "Matching profile up to date". The download-event watcher timed out, but the browser showed "Profile exported" and the actual downloaded `Downloads/profile.json` was parsed and compared to the owned export response: **exact equality**, including the alternatives and metadata. The fictional check point remains available in Alice's bank.

Switched to Casey: empty experience/project/education/skills and resume lists, no Harbour Metrics text and no Alice point. Returned the browser to Alice and reset the temporary viewport override.

- **1440×1000:** document scroll width 1440; no horizontal overflow.
- **390×844:** document scroll width 390; no horizontal overflow; compact rail/navigation, stacked panels, visible controls.
- Screenshots: [desktop](profile-bank-desktop.png), [mobile](profile-bank-mobile.png). The original always-open basics form was compacted after visual review so bank items are visible sooner and the page follows the mockup's summary/card hierarchy.
- The browser tool blocked the mockup's `file://` URL. Its HTML/CSS source was read directly; the live app was inspected normally over localhost HTTP. No workaround for the blocked local-file browser URL was used.

### Decisions and open questions

- Explicit promotion uses `PUT /items/{id}/bullets/{bullet_id}` with `{expected_revision, alternative_id, text, make_main: true}`. It swaps selected/main wording metadata while retaining stable IDs and the total version count. Without `make_main`, `alternative_id` still means editing that alternative, preserving the earlier save-back contract.
- Archive Undo now restores an owned archived item through `/revert`, checks the current revision, active-kind capacity, duplicate skill and parent validity, and advances the bank revision once. The client supplies the held previous item data; no historical item table was introduced.
- Points are grouped by their first type to avoid displaying an achievement twice; every tag is also visible as a chip. Type input is free-form with suggestions.
- JSON Resume v1 requires a complete certificate `date`; the bank stores partial dates, so no day is invented. Partial certificate dates and other unportable/empty format values stay in metadata rather than invalid standard fields.
- Saving the bank affects the current local keyword snapshot immediately; confirmation stores reviewed facts for consumers that use confirmed versions. No embeddings or AI computation were enabled.
- Authentication is still the existing development Alice/Casey header flow, **not a simulated JWT or real login**. Internal ownership/RLS remains active; Cognito/JWT integration is still the AWS milestone.
- The step 1 filesystem cleanup retry limitation remains: this step changes the deletion UI and archive restore but does not add durable storage-cleanup retry infrastructure.
- The upload list is capped at 100 latest source PDFs; pagination can be added if that library grows beyond the local POC limit. Parent archive keeps project facts; projects whose parent is unavailable remain visible in the Projects section and can be reassigned.

### Step 3 (import) needs to know

Keep the Import buttons disabled until the parser/review flow lands. The page already loads originals and Studio documents through owned APIs. Metadata from our own JSON export is lossless input preparation, not automatic acceptance: all restored/imported facts must still pass the review/apply rules. Use current item revisions for merge decisions, preserve tags/alternatives/parents and stable point IDs, and advance `bank_revision` on apply. `/revert` now supports archived items; `make_main` must only be sent for promotion. Regenerate the OpenAPI contract with `make openapi` after any route/schema change. No build plans, editor point controls, style UI/rendering, angles, AI or AWS work was started.

## Review fixes after step 2

Applied during review on 14 October 2026, locally on `profile-bank`:

- **Second development user renamed from Bob to Casey** (`casey`, "Casey Demo"; same user ID). All code, tests, smoke and docs updated. Existing local databases need the stored name updated once (`users.auth_subject`/`display_name`, and `profiles.draft.display_name`); fresh databases seed Casey directly.
- **Skill categories inferred** by `profile_bank/skills.py::infer_skill_category` (language, framework, tool, soft, otherwise domain) for legacy migration and demo data. Previously every skill defaulted to `tool`.
- **Your resumes** shows the five latest uploads and Studio resumes with *Show all N*, plus a single "Importing these into your profile is coming soon" note instead of a disabled Import button on every row.
- "1 versions" now reads "1 version".
- Alice's local demo was reset with `make reset-demo`, which removed the synthetic browser-check point and archived 16 test resumes. Recommendations for Alice still match the step 1 evidence (71 of 71 identical).

Checks: backend **149 passed** on a fresh disposable database, migration check PASS, web **31 passed**, TypeScript and production build pass, `make smoke` PASS.

## Step 3 — Import

Completed 15 October 2026 on `profile-bank`, locally only. The first implementation pass stopped partway; the review finished it with two helper agents (backend integration tests; profile-page wiring and frontend tests) plus the fixes below.

### Built

- `job_hunter/profile_bank/importing/` (pure, no FastAPI/AWS): `text.py` (pdfplumber extraction with page/line evidence, 10 MiB / 20 pages / encrypted / no-text checks), `parsers.py` (Studio document → JSON Resume; heuristic PDF/text → JSON Resume), `schema.py` (pinned JSON Resume v1 validation, no runtime download), `candidates.py` (JSON Resume → candidates, per-field/per-point evidence, matching, additive merge), `models.py` (`ModelAdapter` with `fake`, optional `ollama`, `bedrock` stub; one retry then heuristic fallback), `services.py` (frozen input, inline run, idempotent apply, discard, retry).
- Routes: `POST/GET /v1/profile/imports`, `GET /v1/profile/imports/{id}`, `POST …/apply|discard|retry`. Migration `0011_profile_import_result` adds `profile_imports.applied_result` and `profiles.basics_provenance`.
- New dependencies: `pdfplumber`, `jsonschema` (lock regenerated in the API image). Config: `MODEL_BACKEND` (default `heuristic`), `OLLAMA_URL`, `OLLAMA_MODEL`.
- Frontend: Import on each upload and Studio resume, **Import from file** and **Paste text** in the header, `ImportReview` (basics conflicts, Add/Merge/Skip, ambiguous target picker, evidence quotes and "Not found in the source" flags, unsorted group, sticky Apply bar), failed-import Retry/Discard, Recent imports (Review/Retry), result toast with counts and conflicts.

### Fixes made during review

- **Stray `applications.applied_result` ORM column** (meant only for `profile_imports`) made every applications query fail with 500 on upgraded databases. Tests missed it because migration `0001` builds tables from current ORM metadata. Removed, and `scripts/check_profile_bank_migration.py` now strips post-0009 columns using `scripts/schema_0009_columns.json`, upgrades to head and **fails if any ORM column lacks a migration** (proven to catch this bug). The check now runs in GitHub Actions.
- **Heuristic dates:** any 3–9-letter word was accepted as a month ("Fictional **Labs** 2023"), losing the employer and dates. Month names are now explicit.
- **Section headings** match by keyword on short lines ("Selected projects", "Technical skills" were unsorted before).
- **Self-import made duplicates:** importing Alice's own Studio resume offered both jobs and projects as *new*. Matching now compares title + core organisation (ignoring "· location" and parentheticals) and start year only when both sides have one; Studio "Company · Location" subheadings are split; skills split on `·`, `•`, `;` as well. Regression test added.
- **False flags:** dates, inferred categories, level and skills lists are no longer checked against the source, and the UI flags only server-checked fields.
- **Pytest import path:** `pythonpath = ["src", "."]` so tests can share helpers (`tests.…`) under `make test-backend` and CI.
- **Mobile:** point text no longer squeezes beside its buttons below 600 px.

### Checks

| Check | Result |
|---|---|
| Backend, fresh disposable DB (standard `make test-backend` invocation) | **174 passed** (incl. 11 import integration tests, 14 import unit tests) |
| `check_profile_bank_migration.py` | PASS, including the new ORM-column guard; FAIL when the stray column is reintroduced |
| `make test-web` | **44 passed**, TypeScript and production build pass |
| `make smoke` | PASS |
| Browser, Alice | Studio self-import: 3 new, 10 duplicate, 5 update; applied → "Added 3, merged 5, skipped 10, personal details updated, 2 conflicts kept"; still 2 jobs / 2 projects; existing point IDs and versions kept; new points carry import provenance |
| Browser, 390 px | no horizontal overflow; review and profile readable |
| Recommendations | after `make reset-demo`: 71/71 identical to the step 1 evidence |

### Known limitations and open questions

- **Near-duplicate wordings** become separate points: "Built FastAPI services … with ownership checks" and the resume's "Built FastAPI services … for an internal analytics workspace; added validation …" don't match exactly, so the import appends a second point instead of a version. Suggest offering "add as a version of …" when similarity is high (planned "similar points" helper).
- Evidence for short repeated values (e.g. a location that appears on several lines) can quote the first matching line rather than the entry's own line.
- Imports run inline; the async SQS path keeps `task_id` and frozen input ready but is unbuilt. Ollama is optional and untested against a real model here. Bedrock is a stub.
- Code style in the new `importing/` modules is denser than the rest of the backend; worth reformatting when next touched.

### Step 4 needs to know

Build plans and the editor can rely on bank items carrying stable point IDs, alternatives, tags and provenance after import. Imported points have `provenance.origin = "import"` until edited away from their evidence. Run `make reset-demo` after browser checks; `make smoke` creates test documents in Alice's account.

## Hardening — adversarial review of import

A high-effort review of `main...profile-bank` (focus: untrusted input, isolation, apply races, merge safety, contract) reported 8 findings, all fixed with regression tests in commit `6633075`: crafted `resume.json` metadata crashed imports (now a clean failed import); malformed Studio draft emails blocked imports (now skipped); import bodies are capped at 2 MiB and 64 nesting levels before parsing; unexpected parser errors become retryable failed imports; PDF extraction has a 20 s budget and early text cap; evidence matching uses one prebuilt index (~0.04 s for 200 lookups on 12k lines); supplied field provenance is re-verified; size is checked before schema validation.

## Word (.docx) import

- Accepted types: **PDF and .docx**, identified by content (PDF `%PDF-`; DOCX = ZIP whose `[Content_Types].xml` declares the WordprocessingML main document). A renamed file is detected and stored with its real type.
- Refused with clear codes: legacy `.doc` (`LEGACY_DOC`, "Save it as PDF or .docx and upload again"), password-protected (`DOCX_ENCRYPTED`), macro-enabled (`MACRO_ENABLED`), RTF/ODT/others (`UNSUPPORTED_FILE`), corrupt (`INVALID_DOCX`).
- Safety before parsing: ≤200 entries (read from the central directory first), ≤25 MiB uncompressed, ≤100:1 compression per entry ≥16 KiB, `word/document.xml` ≤5 MiB, no absolute/`..`/backslash/drive paths or duplicate names, any part with `<!DOCTYPE`/`<!ENTITY` or UTF-16 refused, external relationships never followed, images never loaded, table nesting ≤4, plus the existing text and time limits. python-docx 1.2.0 / lxml 6.1.3 (`resolve_entities=False`).
- Extraction: header text first, body in order, tables row by row, list paragraphs as bullets. Downloads now serve the stored content type (previously always PDF).
- Limitation: text inside Word text boxes and footers isn't extracted.

## Step 4 — Building resumes from the profile

Completed 15 October 2026 locally, by three parallel helper agents against a fixed contract, then integrated and browser-tested.

### Built

- **Backend:** `profile_bank/build.py` (`suggest_plan` keyword-v1 with reasons and skill coverage; `plan_to_document`; defaults), `api/resume_build.py` (`POST /v1/resume-builds/suggest`, `POST /v1/documents/from-bank`), `api/document_checks.py` (new content/layout validation; source items must be the caller's own; existing links aren't re-checked on PATCH so resumes stay editable after "Delete my profile data"). Blank resumes start from resume defaults and profile basics. `profile_bank/dates.py` formats `date_range` for every `date_format`/`present_label`.
- **Renderer (ReportLab):** honours `hidden`, date formats, heading style (incl. small caps), accent colour, bullet character (`▪` via ZapfDingbats), header alignment, contact separator, section spacing and skills layouts. Documents without the new keys are **byte-identical** to before (six golden hashes).
- **Editor:** always-visible `↑ ↓ ⋮` per point; ⋮, right-click and Menu/Shift+F10 open the same ARIA menu (*Versions ▸*, move, remove, *Save to profile ▸* with Update in profile / Save as new version / Save as new point…); bottom sheet on narrow/touch screens; "More from this job in your profile"; *Add from profile* per section; section Hide/Show; `bullets`/`bullet_sources` kept aligned by tested helpers in `editor.ts`.
- **Build flow:** new-resume chooser (Blank · From my profile · For a job · Copy a resume); free build with focus and per-item cap; build for a job (also from the tracker's *Prepare resume → Build from my profile*) with reasons, coverage and "I have this · add to profile"; style settings for all nine new layout keys plus *Save as my default* / *Apply my defaults*; live preview honours every new key.
- **Integration fix:** the `.gitignore` rule `build/` (meant for Python build output) also hid `apps/web/src/studio/build/`; scoped to `/backend/build/`.

### Checks

| Check | Result |
|---|---|
| Backend, fresh disposable DB | **368 passed** |
| Migration guard | PASS |
| Frontend | **178 passed** (16 files), TypeScript and production build pass |
| `make smoke` | PASS |
| API, real backend | suggest → reasons ("matches Python, PostgreSQL", "tagged backend"), coverage 2/2 → from-bank creates a resume with linked points, formatted dates, grouped skills |
| Browser, Alice (desktop) | Studio → New resume → For a job → Backend Engineer → Match my profile → Create → editor with attach banner; ⋮ menu hides Save to profile until a point is edited, then offers all three; *Save as new version* reached the profile and updated the resume link; date format setting saved; server PDF renders the built resume correctly |
| Browser, 390 px | no horizontal overflow (editor, style settings) |
| Recommendations | after `make reset-demo`: 71/71 identical to the step 1 evidence |

Test resumes created during the browser check were archived and Alice's demo was reset.

### Known gaps and follow-ups

Resolved in "Step 4 follow-ups" below: resume delete, version-limit chooser, Undo on profile saves, certifications/awards/volunteering, keeping manual choices on re-suggest. Still open:

- `suggest_plan` doesn't suggest custom sections; projects are grouped under their job in pickers only (resume content stays flat).
- Profile `links` aren't placed on resumes (resume content has no links field).
- Near-duplicate wordings from imports become separate points (see step 3).
- DOCX text boxes/footers not extracted.

### Before merging to `main`

Run the GitHub checks (they now include the migration guard), share the branch with area owners whose code it touches (recommendations route input; documents validation; renderer), and note that real login (Cognito) and AWS deployment remain the cloud milestone.

## Step 4 follow-ups

Completed 15 October 2026 locally by two helper agents, integrated and browser-checked.

- **Delete a resume:** `DELETE /v1/documents/{id}` archives it (`kind = "archived"`, 204, idempotent) and `POST /v1/documents/{id}/restore` undoes it; owner-scoped (foreign → 404). Library cards and the editor header have a delete action with a confirmation dialog and a 9-second **Undo** toast. Archived resumes can't be edited, reviewed, exported or duplicated until restored; existing exports and application PDF snapshots are unaffected.
- **Use profile summary** button on the editor's summary field (undoable, autosaved; disabled when the profile has no summary).
- **Certifications, awards and volunteering** are resume section kinds end to end (build plans, suggestions — certifications only — Add from profile, kind inference, renderer).
- **Re-suggest keeps manual choices** (ticks, versions, order, skills) for items still present; free build also keeps its focus.
- **Projects grouped under their job** in build pickers and Add from profile; resume content stays flat.
- **Version-limit chooser:** at 5 wordings, *Save as new version* / *Update in profile* open "Replace which one?" (main wording can't be dropped; *Don't keep the old wording* for updates). API: `replace_alternative_id` on add-alternative and update-point, `keep_previous` on update.
- **Undo for profile saves** (all three save types), revision-checked; 409 shows "Can't undo: this point changed since"; the resume link is restored too.
- **Integration fix:** *Save as new point* into a new experience now creates the item with its point in one request, so a failure can't leave an empty item behind.

| Check | Result |
|---|---|
| Backend, fresh disposable DB | **386 passed**; migration guard PASS |
| Frontend | **216 passed** (18 files); TypeScript and build pass |
| `make smoke` | PASS |
| Browser | delete → confirm → Undo restores; Use profile summary present; new blank resume pre-fills the profile summary; 390 px without horizontal overflow |
| Recommendations | after `make reset-demo`: 71/71 identical |
