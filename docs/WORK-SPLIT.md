# Work split

Six areas. Target: **18 October**, except cloud infrastructure, which may run later.

| # | Area | Current code | Design brief | What exists |
|---|---|---|---|---|
| 1 | Job discovery / ingestion | `backend/src/job_hunter/ingestion/`, `import_jobs.py` | [04](design/04-JOB-INGESTION.md) | Greenhouse/Lever import, 70 Singapore listings. [Notes](status/04-ingestion.md) |
| 2 | Resume upload | `/v1/uploads`, `/v1/profile` and `/v1/profile/imports` routes; `profile_bank/` | [03](design/03-PROFILES-AND-RESUMES.md), [10](design/10-PROFILE-BANK.md) | PDF and Word upload, import with review, structured profile bank, profile confirm, Cognito sign-in |
| 3 | Tailoring resume / CV | Resume editor: `apps/web/src/App.tsx`, `editor.ts`; `/v1/documents` routes; `preparation/rendering.py`, `tailoring.py`, `ai_tailoring.py` | [09](design/09-RESUME-EDITOR.md), [06](design/06-APPLICATION-PREPARATION.md) | Manual editor, templates, PDF export, job-specific copies, build from the profile bank, rule-based tailoring, optional AI rewrite (fake or Ollama model only, so not available in the cloud) |
| 4 | Recommendations | `backend/src/job_hunter/recommendations.py`, `embedding/`, `/v1/recommendations`, `/v1/recommendations/for-you` | [05](design/05-RECOMMENDATIONS.md), [11](design/11-EMBEDDING-WORKER.md) | TF-IDF/skills/role ranking and a semantic "For you" list (embedding worker live in staging). [Notes](status/05-recommendations.md) |
| 5 | Job fit analysis | `preparation/fit/`, `llm/`, `api/fit_analysis.py`, `fit_worker.py`, `apps/web/src/FitPanel.tsx` | [12](design/12-FIT-ANALYSIS.md) | Built and deployed: requirement extraction, evidence-cited judgement, coverage in code, suggestions, monthly allowance, worker Lambda in staging |
| 6 | Cloud infrastructure | `infra/aws/`, `infra/state/`, `.github/workflows/`, `scripts/deploy_aws.py` | [01](design/01-INFRASTRUCTURE.md) | Terraform and GitHub Actions for the staging deployment: [deployment guide](deployment/README.md) |

## Shared files

Most API routes live in one file (`backend/src/job_hunter/api/main.py`) and most UI lives in one file (`apps/web/src/App.tsx`). To avoid merge conflicts:

- Put new logic in your own module (for example `job_hunter/fit_analysis.py`) and keep route handlers thin.
- Keep pull requests small and merge often.
- Schema changes need a new Alembic migration in `backend/migrations/versions/`. Pull before you create one, because two migrations with the same parent will conflict.
- Changes to shared API shapes ([CONTRACTS.md](design/CONTRACTS.md)) affect the frontend and the other areas, so flag them in the team chat.

## Dependencies between areas

- **3 and 5** both need an AI model adapter. Fit analysis uses the shared `llm/` client (hosted SoCLaaS model, Ollama or a fake); Bedrock is blocked by the university account policy. Tailoring's `build_model()` does not use it yet.
- **4** improves once **1** imports more jobs and **2** produces confirmed profiles.
- **6** packages whatever exists. Areas 1–5 should keep running locally with `make up` so they don't block on AWS.
