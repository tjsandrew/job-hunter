# Job pull: operation and new-environment setup

How real job postings get into the staging database. The pull is deployed and scheduled twice a day; this page covers running it, its cost and safety limits, and setting it up in a new environment. Design: [brief 04](../design/04-JOB-INGESTION.md), "As built". Architecture picture: [aws-overview.html](../architecture/aws-overview.html).

## What it is

Aurora is private and the VPC has no internet, so two Lambdas on the API image share the work:

| Function | Where | Does |
|---|---|---|
| `jobhunter-staging-discovery` | outside the VPC | reads Greenhouse, Lever, MyCareersFuture (and Adzuna with keys), Singapore only; stores `imports/<pull id>.json`; invokes the import function and returns its counts |
| `jobhunter-staging-import` | inside the VPC | reads the snapshot over the S3 gateway endpoint, inserts the next N new jobs as role `jobhunter_app`, links duplicates, writes the embed flag after the commit |

A pull adds at most N new jobs. Jobs already stored are refreshed, and the rest are left for the next pull.

- N is 150 for scheduled pulls in staging and 100 by default from the Pull jobs workflow, with a maximum of 200.
- Within each search, the newest postings come first.
- Each pull also closes listings that expired or went unseen for 21 days.
- Nothing needs a NAT gateway or a new bucket notification.

## Cost and safety

- Each pull wakes Aurora (0 to 1 ACU, Aurora Capacity Unit, with auto-pause), which costs a little. One pull does not trigger the Aurora activity alarm: that alarm needs 18 of the last 24 hourly periods above zero capacity (`infra/aws/backend/activity_alarm.tf`). Other operators should still be told before a manual pull.
- Reserved concurrency: discovery 1, import 1. The account total is 20 reserved: API 10, migrate 1, embed 2, LLM worker 5, discovery 1, import 1. AWS keeps at least 100 unreserved, so check that `aws lambda get-account-settings` shows a limit of at least 120.
- **Scheduled pulls (EventBridge):** staging pulls twice a day, at 06:00 and 20:00 Singapore time. This is `discovery_schedule_enabled = true` and `discovery_schedule_expression = "cron(0 22,12 * * ? *)"` in `staging.tfvars`; it moved from 08:00, when MyCareersFuture was slow.
  - A board or search that times out or gets a 5xx or 429 response is retried once. After 3 such failures in a row, that source's remaining searches are skipped for the pull.
  - Each pull wakes Aurora for about 30 minutes, about USD 0.10, so roughly USD 6 a month. To stop it, set `discovery_schedule_enabled = false` and apply.
  - A scheduled pull is never retried (a retry would pull twice). If it cannot start within an hour it is dropped.
  - **Pausing staging stops scheduled pulls too:** the Pause or resume staging backend workflow sets the discovery function's concurrency to 0 (resume sets it back to 1), so a scheduled pull during a pause is throttled and then dropped instead of waking Aurora.
  - Any failed pull, scheduled or manual, sets off the `jobhunter-staging-discovery-errors` alarm (the same email list as the activity alarm).
- Adzuna keys are GitHub secrets, written into the discovery function by Deploy staging. They are never in the Terraform configuration, a snapshot, a log or a failure report. Like the database passwords, Terraform state may hold a copy of the function's environment after a refresh, so protect the state bucket.

## Setting up in a new environment

Staging already has all of this in place. For a new environment, in this order:

1. Check that no Deploy staging run is in progress, then merge the pull request.
2. Run Terraform as described in the Terraform section of [deployment/README.md](README.md#terraform-state) (use `-var-file=` with that environment's tfvars; brief [01](../design/01-INFRASTRUCTURE.md) covers the infrastructure). Set `discovery_enabled = true`. The plan should show only additions (two roles, two log groups, two functions) and small changes to the release role policy, the S3 lifecycle rules and the deployment output. It must not destroy the database, Cognito, Amplify, the embed worker or the LLM worker.
3. Publish the new function names: `terraform -chdir=infra/aws output -json deployment | python3 scripts/configure_github_deploy.py` (adds `DISCOVERY_FUNCTION` and `IMPORT_FUNCTION`).
4. Optional Adzuna. Staging already has it configured (its Singapore search returns real postings, verified on 24 October 2026); a new environment needs its own keys. Register at developer.adzuna.com, add the GitHub secrets `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`, then set `discovery_adzuna_searches = ["data engineer"]` in the tfvars and apply again. Each pull makes one Adzuna request per keyword (up to 50 jobs). The free plan allows very few calls per day, so keep the keyword list short. Descriptions are about 500-character snippets.
5. Run **Deploy staging** on `main`. Migration 0016 (duplicate links) runs, the new image goes onto both functions, and the import function gets its database password.
6. Run **Pull jobs** on `main` with 10. The run summary shows the counts. Open Discover (All jobs); the For you ranking includes the new jobs after the embed worker has run, a few minutes later.

## Checking and troubleshooting

- Logs: `/aws/lambda/jobhunter-staging-discovery` and `/aws/lambda/jobhunter-staging-import`. Every pull logs one JSON line with `"event": "pull_finished"`, what started it (`"trigger": "schedule"` or `"manual"`) and its counts (fetched, new, updated, unchanged, deferred, errors, source failures, truncated searches). It is the only record of a scheduled pull's counts.
- Scheduled pulls: `aws events describe-rule --name jobhunter-staging-discovery` shows the schedule and whether it is enabled.
- `Nothing was loaded`: every source failed or returned no Singapore jobs; the summary lists each source problem.
- `import step failed`: read the import function log (database password missing means Deploy staging has not run since the apply).
- `missing_credentials` for adzuna: the two secrets are not set, or Deploy staging has not run since they were added.
- Staging paused: the workflow refuses, and scheduled pulls are throttled and dropped; resume first.

## Maintenance

- **Duplicate links for old rows:** `python -m job_hunter.import_jobs --relink` fills the duplicate links of jobs imported before migration 0016. It was a one-off backfill, and it needs the owner database connection from inside the VPC (for example through the migration function), so ordinary operators cannot run it. New pulls link duplicates as they go.
