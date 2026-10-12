# Work split

Six areas. Target: **18 October**, except cloud infrastructure, which may run later.

| # | Area | Current code | Design brief | What exists |
|---|---|---|---|---|
| 1 | Job discovery / ingestion | `backend/src/job_hunter/ingestion/`, `import_jobs.py` | [04](design/04-JOB-INGESTION.md) | Greenhouse/Lever import, 70 Singapore listings. [Notes](status/04-ingestion.md) |
| 2 | Resume upload | `/v1/uploads` and `/v1/profile` routes in `api/main.py` | [03](design/03-PROFILES-AND-RESUMES.md) | PDF upload, text extraction for manual review, profile confirm |
| 3 | Tailoring resume / CV | Resume editor: `apps/web/src/App.tsx`, `editor.ts`; `/v1/documents` routes; `preparation/rendering.py` | [09](design/09-RESUME-EDITOR.md), [06](design/06-APPLICATION-PREPARATION.md) | Manual editor, templates, PDF export, job-specific copies. No AI tailoring yet |
| 4 | Recommendations | `backend/src/job_hunter/recommendations.py`, `/v1/recommendations` | [05](design/05-RECOMMENDATIONS.md) | TF-IDF/skills/role ranking. No embeddings yet. [Notes](status/05-recommendations.md) |
| 5 | Job fit analysis | Not started | [06](design/06-APPLICATION-PREPARATION.md) | Nothing yet; the UI shows AI as unavailable |
| 6 | Cloud infrastructure | `infra/aws/` (to create) | [01](design/01-INFRASTRUCTURE.md) | Plan only: [deployment start page](deployment/README.md), [Lambda notes](deployment/LAMBDA-NOTES.md) |

## Shared files

Most API routes live in one file (`backend/src/job_hunter/api/main.py`) and most UI lives in one file (`apps/web/src/App.tsx`). To avoid merge conflicts:

- Put new logic in your own module (for example `job_hunter/fit_analysis.py`) and keep route handlers thin.
- Keep pull requests small and merge often.
- Schema changes need a new Alembic migration in `backend/migrations/versions/`. Pull before you create one, because two migrations with the same parent will conflict.
- Changes to shared API shapes ([CONTRACTS.md](design/CONTRACTS.md)) affect the frontend and the other areas, so flag them in the team chat.

## Dependencies between areas

- **3 and 5** both need an AI model adapter (Bedrock, or a fake for local tests). Agree one interface rather than building two.
- **4** improves once **1** imports more jobs and **2** produces confirmed profiles.
- **6** packages whatever exists. Areas 1–5 should keep running locally with `make up` so they don't block on AWS.
