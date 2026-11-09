# 08 — Integration and evaluation

How we checked that Job Hunter works, and what we measured on the deployed staging environment. The tooling, how to run it and the results index are in [eval/README.md](../../eval/README.md). The numbers and findings live with the raw results under [eval/results/](../../eval/results). Most folders have a `notes.md`; the A6 results are four JSON files, and the duplicate-removal result is in `summary.md`.

Read the [design README](README.md) and [contracts](CONTRACTS.md) for the system being tested, and [../architecture/aws-overview.md](../architecture/aws-overview.md) for what runs where.

## Principles

- **Measured is not the same as targeted.** The targets below come from the group's preliminary report and are not guarantees. Each result says whether a target was met or missed.
- **A UI demo is not proof.** Tenant isolation, reliable delivery and failure handling are tested directly, not inferred from a working screen.
- **Mocked flows only prove workflow.** Model quality was judged with the real model, on labelled or realistic cases, not with fakes.
- **Report what was skipped.** Anything not covered is listed in [PENDING.md](../status/PENDING.md).

## Automated tests

Each component shipped with its own tests. The suites are deterministic and need no network, AWS credentials, source credentials or paid model calls.

| Suite | Tests defined |
|---|---|
| Backend (pytest) | 705 |
| Frontend (Vitest) | 342 |
| Release and control scripts | 51 |
| Embedder service | 22 |
| Terraform | 5 files, 21 `run` blocks |

The counts and commands are in the [README](../../README.md#tests). Parametrised tests run more cases than these counts.

The backend suite has two layers. Unit tests use fake model, storage and queue adapters, so failure cases (provider timeout, malformed output, a missing key) can be forced. Integration tests run against a disposable PostgreSQL with pgvector; they cover per-user ownership (row-level security), allowances, import and duplicate linking, and the document, fit analysis and cover letter endpoints.

On every push and pull request to `main`, the **Local POC checks** workflow runs the suites whose paths changed (path filter: `scripts/ci_changes.py`; a push to `main` runs the web, backend, scripts and embedder suites):

- frontend tests and build;
- backend unit and PostgreSQL integration tests, a migration check and an HTTP smoke test against the running stack;
- a production ARM64 Lambda image build with a handler and font check;
- the scripts tests;
- the embedder tests.

The **Terraform validation** workflow runs the Terraform tests.

## Checks against the deployed system

Run against staging with six fictional evaluation accounts (`jh-eval-01` to `-06`, one persona each, on the free plan); see the README for how they are made and cleaned up.

| Check | What it shows | Where |
|---|---|---|
| Isolation and token checks (A6) | 26 of 27 passed on 25 October 2026 and one was informational (a revoked session's access token stays valid until it expires): one user cannot read or change another's data, and token handling (including expiry) behaves. Also covers Aurora pausing and the pause and resume workflow. | `acceptance.py`, `results/a6-*` |
| Responsiveness (B1) | Per-endpoint latency for one warm user | `locustfile.py BaselineUser`, `results/b1-baseline-*` |
| Scalability (B3) | A step load of 1, 10, 50 and 100 users, five minutes each, run once at the normal limits and once in a short announced window with capacity raised | `locustfile.py BrowsingUser`, `results/b3-run1-*`, `results/b3-run2-*` |
| AI tasks (B2) | Time, token counts and failures for fit analysis, the AI resume rewrite and AI cover letters, through the deployed app | `b2_ai_tasks.py`, `results/b2-ai-tasks-*` |
| Job pipeline (B4) | Volume, failures and stage times per pull | `b4_pull.py`, `analyse_b4.py`, `results/b4-pipeline-*` |
| Duplicate removal (B4) | Accuracy on 73 scored real pairs (of 84 labelled) | `dedup_eval.py`, `eval/dedup/`, `results/b4-dedup-*` |
| Cost (B5) | Actual spend 1–25 October 2026, and a cost model against workload with a break-even chart | `cost_model.py`, `results/b5-cost-*` |

## Why the load test is shaped this way

- **Levels of 1, 10, 50 and 100 concurrent users**, from the preliminary report, using one scripted browsing mix (job lists, job detail, tracker, profile, Save and Pass) with short pauses, so runs can be compared.
- **The load tests never call the AI endpoints.** Those spend the monthly allowance and call a shared school model, so they are timed separately in B2, one request at a time, and announced first.
- **Two runs on purpose.** Staging runs with deliberately low limits, so run 1 shows what the deployed limits do under load; deliberate throttling is counted as throttling, not hidden. Run 2 raises the API's reserved concurrency, the gateway rate and Aurora's maximum capacity for a short window, to see where the real bottleneck is. The window is announced, recorded before and after, and restored the same day (steps in the README).
- **Failures are labelled** as throttled (`429`), server error (`5xx`), authentication (`401`) or other, so a deliberate limit is not confused with a fault.
- **Latency is reported as percentiles** (P50, P95, P99), server-side where possible, because the load generator is a laptop and its network adds noise to client-side timings.

Targets taken from the preliminary report: read and browse endpoints under 500 ms at P95, ranked lists (For you) under 2 s, task acceptance under 200 ms, and asynchronous AI completion under 30 s. The notes in each results folder give the verdict per endpoint and say how it was judged and which targets were missed. One speed-up followed from B1 and was re-measured: `results/b1-baseline-20261027/` is the B1 re-run after the ranking speed-up. Pull tallies are in the notes of the B4 pipeline results.

## Why these checks and not others

- **Duplicate removal** is scored on labelled pairs from real staging data, so a wrong merge (precision) and a missed duplicate (recall) are both visible. See [04](04-JOB-INGESTION.md) for the method.
- **AI quality** is judged on the checks in code (grounding, invented numbers and names) plus manual review of benchmark cases; see [12](12-FIT-ANALYSIS.md) and [14](14-COVER-LETTERS.md) for the cases and the models compared. Timing and token counts through the deployed app are in B2.
- **Matching** (For you) has only a small labelled set and no claim of accuracy beyond it; see [05](05-RECOMMENDATIONS.md) and [PENDING.md](../status/PENDING.md).
- **Cost** is evaluated against workload rather than at one point, so the chart shows where the serverless design as built meets fixed-capacity alternatives. The model treats prices, usage and measured figures as dated, separate inputs. It ignores free tiers except Cognito's 10,000 monthly users (see the top of `eval/cost_model.py`), so the serverless figures are an upper bound. Cloud credits are not counted as an advantage of the architecture.

## User evaluation

The tooling in `eval/` does not include a participant study. Other open evaluation points, such as a two-account browser run, are in [PENDING.md](../status/PENDING.md). Usability findings from a small sample would be exploratory and kept apart from recommendation quality.

## Where to look next

- [README](../../README.md): prerequisites, local commands, tests, deployment and cleanup.
- [aws-overview.md](../architecture/aws-overview.md): the architecture as built.
- [Deployment guide](../deployment/README.md): environments, release, pause and resume, cost.
- [FEATURES.md](../status/FEATURES.md) and [PENDING.md](../status/PENDING.md): what is built, and what is not.
- [eval/README.md](../../eval/README.md): the evaluation tooling and results index.
