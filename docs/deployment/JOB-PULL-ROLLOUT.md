# Job pull rollout

How real job postings get into the staging database, and how to switch it on. Design: [brief 04](../design/04-JOB-INGESTION.md), "As built". Architecture picture: [aws-overview.html](../architecture/aws-overview.html).

## What it is

Aurora is private and the VPC has no internet, so two Lambdas on the API image share the work:

| Function | Where | Does |
|---|---|---|
| `jobhunter-staging-discovery` | outside the VPC | reads Greenhouse, Lever, MyCareersFuture (and Adzuna with keys), Singapore only; stores `imports/<pull id>.json`; invokes the import function and returns its counts |
| `jobhunter-staging-import` | inside the VPC | reads the snapshot over the S3 gateway endpoint, inserts the next N new jobs as role `jobhunter_app`, links duplicates, writes the embed flag after the commit |

A pull adds at most N new jobs (100 in staging, at most 200), newest postings first within each search; jobs already stored are refreshed, the rest are left for the next pull. Each pull also closes listings that expired or went unseen for 21 days. Nothing needs a NAT gateway or a new bucket notification.

## Cost and safety

- Each pull wakes Aurora (0 to 1 ACU, auto-pause), which costs a little and triggers the Aurora activity alarm email. Tell the team before the first one.
- Reserved concurrency: discovery 1, import 1. With the API (10), migrate (1), embed (2) and LLM (5) that is 20 reserved: check `aws lambda get-account-settings` still leaves at least 10 unreserved.
- **Scheduled pulls (EventBridge):** staging pulls twice a day, at 06:00 and 20:00 Singapore time (`discovery_schedule_enabled = true`, `discovery_schedule_expression = "cron(0 22,12 * * ? *)"` in `staging.tfvars`; moved from 08:00, when MyCareersFuture was slow). A board or search that times out or gets a 5xx/429 is retried once; after 3 such failures in a row, that source's remaining searches are skipped for the pull. Each pull wakes Aurora for about 30 minutes, about USD 0.10, so roughly USD 6 a month. To stop it, set `discovery_schedule_enabled = false` and apply.
  - A scheduled pull is never retried (a retry would pull twice). If it cannot start within an hour it is dropped.
  - **Pausing staging stops scheduled pulls too:** the pause workflow sets the discovery function's concurrency to 0 (resume sets it back to 1), so a scheduled pull during a pause is throttled and then dropped instead of waking Aurora.
  - Any failed pull, scheduled or manual, sets off the `jobhunter-staging-discovery-errors` alarm (the same email list as the activity alarm).
- Adzuna keys are GitHub secrets, written into the discovery function by Deploy staging. They are never in Terraform, a snapshot, a log or a failure report.

## First-time rollout (in this order)

1. Check Deploy staging is not running; merge the pull request.
2. Terraform from CloudShell (recipe in [design brief 12](../design/12-FIT-ANALYSIS.md), section 11). `staging.tfvars` has `discovery_enabled = true`. The plan should show only additions (two roles, two log groups, two functions) and small changes to the release role policy, the S3 lifecycle rules and the deployment output. It must not destroy the database, Cognito, Amplify, the embed worker or the LLM worker.
3. Publish the new function names: `terraform -chdir=infra/aws output -json deployment | python3 scripts/configure_github_deploy.py` (adds `DISCOVERY_FUNCTION` and `IMPORT_FUNCTION`).
4. Optional Adzuna (verified on 24 October 2026: its Singapore search returns real postings). Register at developer.adzuna.com, add the GitHub secrets `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`, then set `discovery_adzuna_searches = ["data engineer"]` in `staging.tfvars` and apply again. Each pull makes one Adzuna request per keyword (up to 50 jobs); the free plan allows very few calls per day, so keep the keyword list short. Descriptions are about 500-character snippets.
5. **Deploy staging** on `main`: migration 0016 (duplicate links) runs, the new image goes onto both functions, and the import function gets its database password.
6. **Pull jobs** on `main` with 10. The run summary shows the counts. Open Discover (All jobs); the For you ranking includes the new jobs after the embed worker has run, a few minutes later.
7. Existing rows: `python -m job_hunter.import_jobs --relink` (owner connection) fills the duplicate links of jobs imported before migration 0016. New pulls do it as they go.

## Checking and troubleshooting

- Logs: `/aws/lambda/jobhunter-staging-discovery` and `/aws/lambda/jobhunter-staging-import`. Every pull logs one JSON line with `"event": "pull_finished"`, what started it (`"trigger": "schedule"` or `"manual"`) and its counts (fetched, new, updated, unchanged, deferred, errors, source failures, truncated searches). It is the only record of a scheduled pull's counts.
- Scheduled pulls: `aws events describe-rule --name jobhunter-staging-discovery` shows the schedule and whether it is enabled.
- `Nothing was loaded`: every source failed or returned no Singapore jobs; the summary lists each source problem.
- `import step failed`: read the import function log (database password missing means Deploy staging has not run since the apply).
- `missing_credentials` for adzuna: the two secrets are not set, or Deploy staging has not run since they were added.
- Staging paused: the workflow refuses, and scheduled pulls are throttled and dropped; resume first.
