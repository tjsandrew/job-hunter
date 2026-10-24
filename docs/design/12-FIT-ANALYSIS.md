# 12 — Fit analysis

Status: **implemented and tested locally against the school's SoCLaaS model; cloud worker written, not yet deployed.** Dollar and timing figures come from our own benchmark runs (4 real postings, one demo profile), not from a price page.

For one job, the app reads the posting's real requirements, checks each one against the user's confirmed profile, and shows what the profile evidences, what it does not, and what only the user can judge. It also shows a requirements-coverage percentage and a few suggestions.

## 1. What the user sees

- A **Fit analysis** section in the job details dialog (`apps/web/src/FitPanel.tsx`): a "Check my fit" button, a progress line while it runs (about 30 s), then the result.
- **Requirements coverage** `= (met + 0.5 × partly) ÷ judged must-have requirements`, computed in code. It is shown with its meaning: "of this job's must-have requirements are evidenced in your profile. This is not a chance of being hired."
- Three groups: *Your profile shows* (met, partly), *Not evidenced in your profile*, *Needs your judgement* (years of experience, degrees, anything the profile cannot show). Each met item quotes the profile text it relies on.
- *Suggestions*: emphasise or reword a real bullet, or "add this **if it is true for you**". Each is tied to a requirement.
- No percentage is shown when fewer than 2 requirements could be judged or more than a quarter went unanswered.
- Never shown: a hiring probability, or a raw embedding-similarity percentage (see section 7).

## 2. Flow

```
POST /v1/jobs/{id}/fit-analysis        (202; the work runs after the response)
  checks: job exists, listing has a real description, profile confirmed, monthly slot available
  stores a fit_analyses row (status pending); builds the request
     {job text, cached requirements or none, the profile's evidence text}
        local  (FIT_BACKEND=inline): a background task in the API process calls the model
        AWS    (FIT_BACKEND=s3):     writes fit-requests/<id>.json to the private documents bucket
GET /v1/fit-analyses/{id}              (the web app polls every 2.5 s)
  AWS: reads fit-results/<id>.json when it exists
  verifies it again, stores it, spends the slot, caches the job's requirements
GET /v1/jobs/{id}/fit-analysis         (latest analysis for this user and job, for when the dialog opens)
```

One row per user and job: running it again replaces the row. A pending request with no answer after 5 minutes is reported as failed (`TIMEOUT`).

## 3. The analysis (library code, `backend/src/job_hunter/preparation/fit/`)

1. **Extract** (`requirements.py`): the model lists the posting's real requirements (must / nice). Salary, benefits, legal notices and application limits are not requirements. Cached per job in `job_requirements`, keyed by a hash of title, description and prompt version, so a changed posting is read again and every user shares one extraction.
2. **Judge** (`judge.py`): requirements in groups of 5, each answered `met` / `partly` / `not_evidenced` / `needs_judgement` with the ids of the profile evidence it relies on. Skipped rows are asked again once.
3. **Check** (`grounding.py`): cited ids must exist (bullet ids, `skill:<name>`, `role:<i>`, `education:<i>`, `project:<i>`, `summary`); `met` / `partly` without real evidence becomes `not_evidenced`; notes and suggestions that contain numbers found nowhere in the profile or requirement are dropped; emphasise / reword must point at a real bullet; "add" must read as conditional.
4. **Suggest** (`judge.suggest`): a bonus step. If it fails the analysis is still returned.
5. **Score** (`coverage.py`): the percentage is computed here, never asked of the model.

Posting and profile text are quoted as data in every prompt and cannot change the rules (tested with a hostile posting). `PROMPT_VERSION` is stored with each result.

## 4. Where the model runs

- **Bedrock is not available**: the NUS service control policy denies `InvokeModel` for the account. A 3B model on local Ollama was too weak (requirements left unanswered, invented skills in notes).
- **The school's SoCLaaS gateway** (OpenAI-compatible, data stays in NUS), model `gemma4:26b`, `reasoning_effort: none`. In the benchmark every requirement was answered, extraction no longer kept salary lines, and one analysis took 28–39 s and about USD 0.0008. Other models tried: `llama3.1:8b` (12–20 s, looser), `qwen3.5:9b` (wrong calls), `qwen3.8:27b` (good, about 5× the cost).
- The API Lambda is in a VPC with **no internet**, so it cannot call SoCLaaS. A separate **fit-worker Lambda outside the VPC** does. It never touches the database; the request file carries everything it needs.
- The worker uses the **same container image as the API** (command `job_hunter.fit_worker.handler`), so there is no extra image, ECR repository or build.

## 5. Trust boundaries

- The worker's result file is input like any other. `verify.py` re-runs the grounding checks against the user's own profile version, re-cleans requirements and suggestions, and **recomputes the coverage** before anything is stored. A tampered percentage, invented evidence id or invented number does not survive.
- The request and result files hold the user's profile text. They sit in the private documents bucket and expire after one day.
- Storage: `fit_analyses` has row-level security by user like every per-user table; `job_requirements` is shared like `jobs`.
- `LLM_API_KEY` never reaches the API Lambda or the web app, only the worker. It is never logged (client errors carry no key).

## 6. Allowance

Fit analysis and AI tailoring share one slot per **user and job per Singapore month**. Free users have 5 slots, premium users 50 (`allowance.LIMITS`; `users.plan` decides). Re-running a job that already has its slot costs nothing. A slot is spent only when an analysis is stored successfully; analyses still running count against the limit so several quick clicks cannot overshoot it. Failures cost nothing. Premium is a demonstration entitlement, not a payment flow.

## 7. Why embeddings cannot do this

Requirement-versus-profile cosine similarity ranges 0.67–0.84 for everything, with filler such as "you are encouraged to apply" at 0.71 and a real requirement at 0.84. It ranks jobs ("For you", brief 11); it cannot say whether a profile meets a requirement.

## 8. Configuration

| Setting | Where | Value |
|---|---|---|
| `FIT_BACKEND` | API | `inline` locally, `s3` on AWS |
| `MODEL_BACKEND=hosted`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_REASONING_EFFORT` | local `.env`; AWS: fit-worker Lambda environment (plain Terraform variables) | SoCLaaS URL, `gemma4:26b`, `none` |
| `LLM_API_KEY` | local git-ignored `.env`; AWS: GitHub Actions secret, written into the fit-worker environment by `scripts/deploy_aws.py` | the SoCLaaS key |
| `DOCUMENT_BUCKET` | API and worker | the private documents bucket |

## 9. Tests

`tests/test_fit_analysis.py` (library), `tests/test_fit_transport.py` (result checking, worker, S3 hand-off with a fake S3), `tests/test_allowance.py`, `tests/integration/test_fit_analysis_api.py` (endpoints against PostgreSQL: ownership, quota, premium, cache reuse, failure, S3 path), `apps/web/src/FitPanel.test.tsx`.

## 10. Known limits

- A listing with a very short description is refused (`JOB_TOO_SHORT`) rather than analysed.
- Small models still make some wrong calls; the checks catch invented evidence and numbers, not every wrong judgement. The user decides.
- Named skills inside the model's free-text notes are not fact-checked against the profile.
- Whether a deployed group app may use one student's SoCLaaS key, and its budget, is not confirmed with the course staff. If it is not allowed, the feature runs locally for the demo and the AWS worker stays off (leave the worker image unset).

## 11. Turning it on in AWS (cloud owner)

Do this only after the course staff confirm that a deployed group app may use one SoCLaaS key, and what its budget is.

1. GitHub: Settings, Secrets and variables, Actions, **New repository secret** named `LLM_API_KEY` with the SoCLaaS key. It is masked in logs and never written to a file, to Terraform state or to the repository.
2. Terraform: set `fit_worker_enabled = true` in the staging variables and apply. This creates the `-fit` Lambda (outside the VPC), its S3 invoke permission and bucket notification, the one-day expiry of request and result files, and a `FIT_BACKEND=s3` setting on the API. The Lambda starts with no key.
3. Publish the new output to GitHub: `terraform output -json deployment | python3 scripts/configure_github_deploy.py` (adds the variable `FIT_FUNCTION`).
4. Run **Deploy staging** from `main`. The new step "Deploy the fit-analysis worker" updates the worker to the API image and writes `LLM_API_KEY` into its environment (`scripts/deploy_aws.py --fit-image`). Without the secret the step still updates the image and leaves any existing key alone.
5. Check: open a job in the web app and press "Check my fit". If it fails with "The AI model could not be reached", look at the `-fit` Lambda's CloudWatch log.

To turn it off again, set `fit_worker_enabled = false`; the API then answers fit requests with 503 and the rest of the app is unchanged. To rotate the key, change the GitHub secret and run Deploy staging again, then revoke the old key in SoCLaaS.

The key is visible in the Lambda's configuration to anyone allowed `lambda:GetFunctionConfiguration`, the same exposure the database passwords have today. Revoking it in SoCLaaS ends any misuse.
