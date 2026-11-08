# Cloud and system evaluation plan

Drafted 25 October 2026 (Singapore) by @asdxbkssl (cloud and system evaluation). Covers the remaining cloud work and the system evaluation committed to in the preliminary report, section 4.2. Facts below were checked against `main` and the staging account on 25 October 2026.

## Constraints found while planning

- **Fit analysis takes 30–40 s** on `gemma4:26b` ([fit_analysis.py](../../backend/src/job_hunter/api/fit_analysis.py); `ornith1.5:35b`, used since 8 Nov 2026, took 14–23 s for the model calls in a 3-case test and 32 s end to end through S3), against the report's 30 s end-to-end target. Expect to miss it, and explain why rather than move the target.
- **AI requests use the monthly allowance.** Each account has 5 free uses, counted once per job and shared by fit analysis, the AI rewrite and AI cover letters. No API sets an account to premium, so spread AI runs across several free test accounts.
- **Staging limits:**
  - API Lambda reserved concurrency 10;
  - gateway 20 requests/s with burst 40;
  - Aurora at most 1 ACU.

  The account allows **400** concurrent Lambdas, of which 20 are reserved, so there is room to raise the caps for a test window.
- **Billing data is readable** from the team SSO role through Cost Explorer (USD 0.01 a query). October 1–25 cost about **USD 1.91**, mostly Aurora (USD 1.58).
- **The duplicate test set is small:** [dedup_pairs.json](../../backend/tests/fixtures/dedup_pairs.json) has 16 labelled pairs.
- **Each job pull adds at most 10 new jobs** (`discovery_max_new`), so staging holds only a few dozen jobs.

## Ground rules

- **Measure on staging only.** Record the commit, memory, limits and job count with every result.
- **Keep scripts and raw data in `eval/`,** so every number can be reproduced. Never report a number that wasn't measured.
- **Report two kinds of latency** and say which is which:
  - **client-side** from Locust, which includes the network;
  - **server-side** from the API Gateway access logs.
- **Report cold starts and first-request-after-pause separately.** Mixed in, they distort the percentiles.
- **Never load-test the AI endpoints.** They use the allowance and a shared SoClaaS key; time them with a small number of deliberate runs.
- **Announce every load window in the team chat,** and never run one during a user-testing session.

## Part A: cloud prerequisites (25–27 October)

| # | Task | Why the evaluation needs it |
|---|---|---|
| A1 | Merge and apply the hardening PR (ECR cleanup, HSTS, HTTPS-only documents bucket, database maintenance windows, **API Gateway access logs**, capacity variables). Write the Amplify headers in the form Amplify stores, so no `ignore_changes` dance is needed. | The access logs are the server-side source for percentiles and for 429/5xx counts |
| A2 | Grow the job pool to **at least 300 jobs**: raise `discovery_max_new` (e.g. to 100) and run Pull jobs a few times | "For you" is recomputed on every request, so its latency depends on pool size. Also measure at about 100 and 300 jobs to show that trend. |
| A3 | Create about **6 evaluation accounts** in Cognito, each with a fictional confirmed profile, preferences and a profile bank | Spreads the load across accounts; 4 free accounts × 5 jobs gives about 60 AI runs |
| A4 | Refresh-token helper: sign each account in once in a browser, keep its refresh token outside Git, and exchange it at `/oauth2/token` | Locust can't use password sign-in, because those tokens lack the `jobhunter/use` scope the API requires |
| A5 | Raise-and-restore runbook for a test window: the capacity variables plus `put-function-concurrency` for the API (Terraform ignores its concurrency after creation) | Shows whether scaling out moves the saturation point |
| A6 | Acceptance checks: two-account isolation (cross-user denial, expiry, logout), Aurora pausing when idle, one real run of the pause/resume workflow | Part of validating the deployment |
| A7 | Optional: per-source counts in the job-pull result (it reports totals and failures today) | Needed for "volume by source" |

## Part B: system evaluation (preliminary report, section 4.2)

### B1. Responsiveness: synchronous requests (27 October)

| Group | Endpoints | Target |
|---|---|---|
| Read and browse | `/v1/me`, `/v1/recommendations` (All jobs), `/v1/jobs/{id}`, `/v1/jobs/reviewed`, `/v1/applications`, `/v1/profile`, `/v1/profile/bank`, `/v1/documents` | P95 under 500 ms |
| Compute-heavy | `/v1/recommendations/for-you`, `/v1/resume-builds/suggest`, `/v1/documents/{id}/preview.pdf` | P95 under 2 s |

- **Method:** one warm Locust user, at least 200 requests per endpoint. Then separate cold-start runs (right after a deploy) and first-request-after-pause runs (after 35 minutes or more idle).
- **Output:**
  - P50/P95/P99 per endpoint, client-side and server-side, compared with the targets;
  - for any endpoint that misses, the split between gateway and Lambda time, using the access logs' integration latency.

### B2. Responsiveness: AI tasks (28 October)

- **Tasks:** fit analysis, AI cover letter, AI resume rewrite. About 15 runs each, on different jobs, across the free evaluation accounts.
- **Measures:**
  - **Acceptance:** time for the request to return `202` (target under 200 ms).
  - **Completion:** time from the request to `ready`, polling every second (target under 30 s).
- **Explaining the result:** split completion time into:
  - waiting for the worker to start after the S3 request file lands;
  - the SoClaaS model call itself (from the worker log);
  - the polling delay.
- **Token counts** are recorded for each run, so SoClaaS cost per task can be computed.

### B3. Scalability (29–30 October)

- **Scenario:** a weighted browsing session:
  - `me`, then All jobs and For you;
  - opening a job;
  - Save or Pass, which writes data;
  - the tracker list.

  No AI calls.
- **Steps:** 1, 10, 50 and 100 concurrent users, about 5 minutes each after a 1-minute ramp. Run from **CloudShell in ap-southeast-1**, so the client isn't the bottleneck. Repeat one run from a laptop for perceived latency.
- **Run 1, current limits:** expect early saturation from the deliberate caps. Report 429s (caps) and 5xx (errors) separately.
- **Run 2, raised limits:** in an announced 1–2 hour window (for example API concurrency 50, gateway 200/s burst 400, Aurora 4 ACU), restored the same day. This shows whether scaling out helps, and what the next bottleneck is: likely database connections and capacity, or For-you CPU time.
- **Recorded per step:**
  - throughput and P50/P95/P99;
  - 5xx and 429 rates;
  - Lambda concurrency and throttles;
  - Aurora `ServerlessDatabaseCapacity` and `DatabaseConnections`.

  The **saturation point** is where throughput levels off while P99 and errors climb.

### B4. Job-pipeline performance (runs throughout; analysis 31 October)

- **Volume and reliability:** run Pull jobs once or twice a day for about a week (around 10 runs). Tally per source:
  - new versus duplicate jobs;
  - failures by kind: rate-limited, response too large (the Cloudflare Greenhouse board already hit the 8 MB limit), malformed.
- **Duplicate-removal accuracy:** extend `dedup_pairs.json` from 16 to **about 80 labelled pairs**:
  - real cross-source duplicates (an employer's own board versus MyCareersFuture and Adzuna);
  - hard non-duplicates (the same title at a different company, reposts).

  Report precision, recall and F1 offline, using the pure functions in [dedup.py](../../backend/src/job_hunter/ingestion/dedup.py). Then spot-check the "also seen on" links in staging.
- **Processing latency:** for each pull, the time from discovery starting to:
  1. the import finishing;
  2. the embedding worker finishing;
  3. the job appearing in "For you".

  Use the Lambda log timestamps. The schedule interval is reported separately, as the maximum discovery delay.

### B5. Cost efficiency (1–3 November)

- **Actuals:** daily Cost Explorer figures by service from 1 October, plus SoClaaS spend (billed outside AWS) from the logged token counts times its listed prices.
- **Cloud model:** turn the load-test measurements into resources per request: Lambda run time and memory, API requests, database capacity-hours. Project monthly cost at 10, 100, 1,000 and 10,000 active users, including storage, logs, Cognito, Amplify and LLM tokens.
- **Fixed-capacity comparison:** an equivalent always-on deployment sized for the peak measured in B3, in two forms:
  - **on-premise:** hardware spread over 3 years, plus power, network and admin time, with every assumption stated and sourced;
  - **always-on cloud servers** as a verifiable stand-in (e.g. a small EC2 instance plus a small provisioned RDS instance).
- **Result:** a chart of monthly cost against workload, marking the **break-even point** where serverless stops being cheaper. Every price source is dated.

## Part C: deliverables in `eval/`

- **Scripts:** `locustfile.py`, the token helper, Logs Insights queries, the pipeline-metrics collector, the duplicate-accuracy script and the cost script.
- **`results/`:** raw CSVs and log exports per run, each with a config snapshot.
- **`README.md`:** exact commands and dates. Charts are generated from the CSVs.
- **Report section 4.2 draft:** one table or chart per metric, the targets set against the measured results, and the limitations (one region, staging-sized data, the client's network, SoClaaS shared with other users).

## Budget

Load windows at 4 ACU cost about USD 1–3 per day used, and job pulls about USD 0.10 each. The whole evaluation should stay **under about USD 15** (the monthly alert is at USD 40).

## Schedule

| Date | Work |
|---|---|
| 25–26 Oct | A1–A5: PR, job pool, accounts, token helper, Locust script |
| 27 Oct | A6 acceptance checks; B1 baseline; start daily pulls |
| 28 Oct | B2 AI task timings; extend the duplicate test set |
| 29 Oct | B3 run 1 (current limits) |
| 30 Oct | B3 run 2 (raised window, announced) |
| 31 Oct | B4 analysis |
| 1–3 Nov | B5 cost model and comparison |
| 3–6 Nov | Write up 4.2; rerun anything changed by user-testing fixes (never during sessions) |
| By 9 Nov | Final numbers and charts in the report |

## Needed from others

- **Andrew or @asdxbkssl:** create the evaluation Cognito accounts (check whether the team SSO role allows `cognito-idp admin-create-user`).
- **Team:** agree the load windows (29 and 30 October), and keep user-testing sessions apart from them.
- **Liana or Dao Yi:** per-source counts in the job-pull result (A7), unless @asdxbkssl adds them.
