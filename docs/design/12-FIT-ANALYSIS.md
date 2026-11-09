# 12 — Fit analysis

Status: **implemented and deployed in staging as a task of the shared LLM worker (section 12).** Section 4 gives the source of every figure.

For one job, the app reads the posting's real requirements, checks each one against the user's confirmed profile, and shows what the profile evidences, what it does not, and what only the user can judge. It also shows a requirements-coverage percentage and a few suggestions.

## 1. What the user sees

- A **Fit analysis** section in the job details dialog (`apps/web/src/FitPanel.tsx`): a "Check my fit" button, a progress line while it runs (about 30 s on `gemma4:26b`, 14–23 s of model time on `ornith1.5:35b`; section 4), then the result.
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
        local  (LLM_WORKER=inline): a background task in the API process calls the model
        AWS    (LLM_WORKER=s3):     writes llm-requests/<id>.json (task "fit") to the private documents bucket
GET /v1/fit-analyses/{id}              (the web app polls every 2.5 s)
  AWS: reads llm-results/<id>.json when it exists
  verifies it again, stores it, spends the slot, caches the job's requirements
GET /v1/jobs/{id}/fit-analysis         (latest analysis for this user and job, for when the dialog opens)
```

One row per user and job: running it again replaces the row. A pending request with no answer after 5 minutes is reported as failed (`TIMEOUT`).

## 3. The analysis (library code, `backend/src/job_hunter/preparation/fit/`)

1. **Extract** (`requirements.py`): the model lists the posting's real requirements (must / nice). Salary, benefits, legal notices and application limits are not requirements. `job_requirements` holds one row per job, with an `input_hash` of the title, description and prompt version. A changed posting is therefore extracted again, and every user shares one extraction.
2. **Judge** (`judge.py`): requirements in groups of 5, each answered `met` / `partly` / `not_evidenced` / `needs_judgement` with the ids of the profile evidence it relies on. Skipped rows are asked again once.
3. **Check** (`grounding.py`): cited ids must exist (bullet ids, `skill:<name>`, `role:<i>`, `education:<i>`, `project:<i>`, `summary`); `met` / `partly` without real evidence becomes `not_evidenced`; notes and suggestions that contain numbers found nowhere in the profile or requirement are dropped; emphasise / reword must point at a real profile evidence id (a bullet, skill, role, education, project or summary); "add" must read as conditional.
4. **Suggest** (`judge.suggest`): a bonus step. If it fails the analysis is still returned.
5. **Score** (`coverage.py`): the percentage is computed here, never asked of the model.

Posting and profile text are quoted as data in every prompt and cannot change the rules (tested with a hostile posting). `PROMPT_VERSION` is stored with each result.

## 4. Where the model runs

- **Bedrock is not available** on the course AWS account. A 3B model on local Ollama was too weak (requirements left unanswered, invented skills in notes).
- **The school's SoCLaaS gateway** (OpenAI-compatible, at `soclaas-api.comp.nus.edu.sg`), model `ornith1.5:35b` since 8 Nov 2026 (`gemma4:26b` before that), `reasoning_effort: none`.
- **Original benchmark (a local benchmark that is not in the repository).** On `gemma4:26b`, every requirement was answered and extraction no longer kept salary lines. One analysis took 28–39 s and about USD 0.0008. Other models tried: `llama3.1:8b` (12–20 s, looser), `qwen3.5:9b` (wrong calls), `qwen3.8:27b` (good, about 5× the cost).
- **Switch to `ornith1.5:35b` (8 Nov 2026).** The figures in this bullet come from a local comparison that is not in the repository.
  - *Why it changed.* SoCLaaS stopped serving `gemma4:26b` (HTTP 503, "no healthy provider backends"), so every fit failed with `MODEL_UNAVAILABLE`.
  - *How the new model was chosen.* Six other chat models (seven in total) were run through `analyse_evidence` on 3 fictional cases: a Java posting against a Go/Python backend profile, a data engineer and a senior DevOps engineer.
  - *Result.* `ornith1.5:35b` gave the most careful verdicts (Java, Tomcat, Oracle and Snowflake correctly not evidenced; must-haves and nice-to-haves told apart). It took 14–23 s per fit, at about the same price as `gemma4:26b` (about US$0.0007 a fit). `qwen3-coder-next` was also accurate at about 3× the cost. `nemotron3.5:30b` was fastest (8–13 s) but too generous with partial matches. `qwen3.5:9b` failed one run.
  - The model is one Terraform variable (`llm_model`), so switching to another served model is a one-line change.
- **Through the deployed app (25 Oct 2026, on `gemma4:26b`, one request at a time, polled every second; `eval/results/b2-ai-tasks-20261025T130734Z/`):** 15 of 15 fit analyses completed, median (P50) 26.1 s, 95th percentile (P95) 34.5 s, 12 of 15 inside 30 s; the request was accepted in 166 ms (median). About 24 s of a run is model time (4.6 model calls, about 3,250 tokens in and 1,140 out). This run has not been repeated on `ornith1.5:35b`.
- The API Lambda is in a VPC with **no internet**, so it cannot call SoCLaaS. A separate **LLM worker Lambda outside the VPC** does (shared with the AI resume rewrite and the AI cover letter, section 12). It never touches the database; the request file carries everything it needs.
- The worker uses the **same container image as the API** (command `job_hunter.llm_worker.handler`), so there is no extra image, ECR repository or build.

## 5. Trust boundaries

- The worker's result file is input like any other. `verify.py` re-runs the grounding checks against the user's own profile version, re-cleans requirements and suggestions, and **recomputes the coverage** before anything is stored. A tampered percentage, invented evidence id or invented number does not survive.
- The request and result files hold the user's profile text. They sit in the private documents bucket and expire after one day.
- Storage: `fit_analyses` has row-level security by user like every per-user table; `job_requirements` is shared like `jobs`.
- `LLM_API_KEY` never reaches the API Lambda or the web app, only the worker. It is never logged (client errors carry no key).

## 6. Allowance

Fit analysis, AI tailoring and AI cover letters (brief 14) share one slot per **user and job per Singapore month**. Free users have 5 slots, premium users 50 (`allowance.LIMITS`; `users.plan` decides). Re-running a job that already has its slot costs nothing. A slot is spent only when an analysis is stored successfully; analyses still running count against the limit so several quick clicks cannot overshoot it. Failures cost nothing. Premium is a demo plan for now: an operator switches an account with `scripts/set_plan.py`. A payment gateway is future work (see brief 13).

## 7. Why embeddings cannot do this

In a one-off check (not kept in the repository), requirement-versus-profile cosine similarity stayed in a narrow band for everything. Filler such as "you are encouraged to apply" scored close to a real requirement. It ranks jobs ("For you", brief 11); it cannot say whether a profile meets a requirement.

## 8. Configuration

| Setting | Where | Value |
|---|---|---|
| `LLM_WORKER` | API | `inline` locally, `s3` on AWS |
| `MODEL_BACKEND=hosted`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_REASONING_EFFORT` | local `.env`; AWS: LLM worker Lambda environment (plain Terraform variables `llm_base_url`, `llm_model`) | SoCLaaS URL, `ornith1.5:35b` (since 8 November 2026; `gemma4:26b` before), `none` |
| `LLM_API_KEY` | local git-ignored `.env`; AWS: GitHub Actions secret, written into the LLM worker environment by `scripts/deploy_aws.py` | the SoCLaaS key |
| `llm_max_concurrency` | Terraform | requests the worker handles at once (default 5) |
| `DOCUMENT_BUCKET` | API and worker | the private documents bucket |

## 9. Tests

`tests/test_fit_analysis.py` (library), `tests/test_llm_transport.py` (result checking, task registry, worker, S3 hand-off and `ask` with a fake S3), `tests/test_tailor_llm.py`, `tests/test_allowance.py`, `tests/integration/test_fit_analysis_api.py` (endpoints against PostgreSQL: ownership, quota, premium, cache reuse, failure, S3 path), `apps/web/src/FitPanel.test.tsx`.

## 10. Known limits

- A listing with a very short description is refused (`JOB_TOO_SHORT`) rather than analysed.
- Small models still make some wrong calls; the checks catch invented evidence and numbers, not every wrong judgement. The user decides.
- A note is checked: `check_verdict` blanks a note whose capitalised names (tools, employers, skills) are absent from the cited evidence and the requirement (`preparation/fit/grounding.py`). Names written in lowercase escape the check.
- The course staff confirmed that the deployed group app may use one shared SoCLaaS key; a budget for it was not stated. Without a key the worker cannot reach the model; set `llm_worker_enabled = false` to turn the AI features off (section 11), and they still run locally with a key in `.env`.

## 11. Setting up the worker in a new environment

Staging has been running this since October 2026, after the course staff confirmed that a deployed group app may use one SoCLaaS key. The steps below are for a new environment.

1. GitHub: Settings, Secrets and variables, Actions, **New repository secret** named `LLM_API_KEY` with the SoCLaaS key. It is masked in logs and never written to a file, to Terraform state or to the repository.
2. Check the account allows the reservations: `aws lambda get-account-settings --query AccountLimit.ConcurrentExecutions` must be at least 120 with the defaults. The reserved total is 20 (API 10, migration 1, embed 2, LLM worker `llm_max_concurrency` with default 5, discovery 1, import 1), and AWS requires at least 100 to stay unreserved.
3. Terraform: set `llm_worker_enabled = true` in the staging variables and apply. This creates the `-llm` Lambda (outside the VPC), its S3 invoke permission and bucket notification, the one-day expiry of request and result files, and an `LLM_WORKER=s3` setting on the API. The Lambda starts with no key.
4. Publish the new output to GitHub: `terraform output -json deployment | python3 scripts/configure_github_deploy.py` (adds the variable `LLM_FUNCTION`).
5. Run **Deploy staging** from `main`. The step "Deploy the LLM worker" updates the worker to the API image and writes `LLM_API_KEY` into its environment (`scripts/deploy_aws.py --llm-image`). Without the secret the step still updates the image and leaves any existing key alone.
6. Check: open a job in the web app and press "Check my fit", on a resume pick 'Tailor with AI', and write a cover letter for a job. If either fails with "The AI model could not be reached", look at the `-llm` Lambda's CloudWatch log.

**History:** the first version was a fit-only worker (`-fit`, prefixes `fit-requests/` and `fit-results/`). Staging was moved to the shared `-llm` worker in October 2026. The old prefixes keep their one-day expiry rules (`llm_legacy_prefixes` in `llm_worker.tf`) so any leftover request files, which hold profile text, are purged. The `llm_legacy_prefixes` list in `llm_worker.tf` can be deleted once no old files remain.

To turn it off again, set `llm_worker_enabled = false`; the API then answers AI requests with 503 and the rest of the app is unchanged. To rotate the key, change the GitHub secret and run Deploy staging again, then revoke the old key in SoCLaaS.

The key is visible in the Lambda's configuration to anyone allowed `lambda:GetFunctionConfiguration`, the same exposure the database passwords have today. Revoking it in SoCLaaS ends any misuse.

## 12. The shared LLM worker: tasks and how to add one

There is one worker Lambda for every feature that needs a language model, not one per feature. A request file is `{"request_id", "task", "input"}` (`job_hunter/llm_transport.py`); the worker (`job_hunter/llm_worker.py`) looks `task` up in `TASKS` (`job_hunter/llm/tasks.py`), runs it with the model client and writes `llm-results/<id>.json`, or `{"error": "<code>"}` when something fails (`MODEL_UNAVAILABLE`, `NO_REQUIREMENTS`, `UNKNOWN_TASK`, `ANALYSIS_FAILED`). The same `run_task` runs locally (`LLM_WORKER=inline`), so local and AWS behave alike.

| Task | Input | Answer | Used by | How the API waits |
|---|---|---|---|---|
| `fit` | job text, cached requirements or none, profile evidence text | requirements, verdicts, suggestions, coverage | `api/fit_analysis.py` | stores a pending row; the web app polls |
| `cover_letter` | the confirmed profile's evidence, the job text, tone, the person's notes or the letter to improve | paragraphs and claims tied to profile evidence | `preparation/cover_letter.py` for `POST /v1/jobs/{id}/cover-letter` (brief 14) | waits up to 25 s inside the request, like `tailor` |
| `tailor` | the resume's bullet lists and the job's title, skills and description (first 4,000 characters) | `{"entries": [[reworded bullets]]}` | `ai_tailoring.WorkerRewriter` for `POST /v1/documents/{id}/tailor` with `mode: ai` | waits up to 25 s inside the request (`llm_transport.ask`); the API Lambda stops at 29 s and API Gateway at 30 s, so a slower answer falls back to the rule-based copy |

The API never trusts an answer. Fit passes through `verify_result`; the rewrite passes through `ai_tailoring.rewrite_content` and its `_safe` check (a reworded bullet that adds a number or a capitalised name is dropped); the letter passes through `check_letter` (brief 14). A slot is spent only when something usable came back (fit: a stored analysis; tailor: at least one bullet changed; cover letter: a usable letter).

**Adding a task** (for example another AI suggestion feature):

1. Write `run_<name>(client, payload) -> dict` in `llm/tasks.py` (raise `TaskError(code)` for a failure the user should see by name) and register it in `TASKS`. Keep imports of feature code inside the function. The worker has no database and no `job_hunter.config`, so the task must work from `payload` alone and must not import settings.
2. In the API, send it with `llm_transport.build_request("<name>", id, payload)` and read the answer with `get_result` (long task: store a pending row and poll, like fit) or `ask` (short task: under about 25 s).
3. Check the answer on the API side before storing or showing it.
4. Add tests with `FakeLlm` and a fake S3 (see `tests/test_llm_transport.py`). No Terraform change is needed: the Lambda, the `llm-requests/` and `llm-results/` prefixes, the IAM policy and the key are shared.

`tailor` quality, from a local benchmark that is not in the repository (4 real postings, one fictional 8-bullet resume; measured on `gemma4:26b`, not repeated on `ornith1.5:35b`): with the original prompt `gemma4:26b` returned a usable reply for 2 of 4 postings (it nested the list one level too deep and the shape check rejected the whole reply); with two added sentences (the exact shape plus an example, `tailor_llm.SHAPE_RULES`) 4 of 4, 29 of 32 bullets reworded, 5-7 s. Local `llama3.2` gave 1 usable reply in 16 attempts. Known weaknesses of the check, not changed here: padding such as "to ensure reliable deployments" passes, and the model sometimes changes UK spelling to US.
