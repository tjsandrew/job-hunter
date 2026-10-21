# Embedding worker: rollout and operations

Design and rationale: [design brief 11](../design/11-EMBEDDING-WORKER.md). This page is the checklist for putting it on AWS and running it.
Status: **nothing here has been run on AWS yet.** Tested so far: unit and database tests, Terraform `validate` and mocked-plan tests,
the worker image (x86 and arm64 builds, handler through the Lambda runtime emulator). Dollar figures are estimates.

Merging this change deploys nothing. Every AWS-facing step below is manual, and each one is small and reversible.

## Cost expectations

- Idle: about $0. SQS and Lambda bill per request or run; the queue, the function and the flag objects have no hourly cost.
- A profile embed is a few seconds of compute (fractions of a cent). Embedding about 1,000 job descriptions is roughly $0.06 at 2 GB; the
  worker runs at 3 GB for about the same cost per job. Both are inside the Lambda free tier at this scale.
- The only way it can cost real money is a loop that keeps Aurora awake or the worker running. Guards: reserved concurrency 2, a run may chain
  only if it made progress, the `embed-runaway` alarm (more than 60 runs in an hour), the `embed-dlq` alarm, and the account budget alert.
- ECR storage for the worker image (about 1.3 GB plus the model) is roughly $0.15 a month.

## Before you start (free checks)

1. Tell the team in the group chat that you are deploying, and do not merge while a deploy is running.
2. Confirm the budget alert exists: `budget_alert_emails` is set in the (untracked) tfvars and the plan includes `aws_budgets_budget.monthly`.
3. Confirm the account's Lambda concurrency allows the reservations (API 10 + migration 1 + worker 2, and AWS keeps 10 unreserved):
   `aws lambda get-account-settings --query AccountLimit.ConcurrentExecutions`. A new account may allow only 10, which cannot hold any reservation.

## Stage 1: queue and permissions (no function yet)

1. `terraform -chdir=infra/aws plan -out embed-stage1.tfplan` and **read the plan before applying**. Expected: the ECR repository, two SQS queues
   and the queue policy, the lifecycle configuration, the worker IAM role, policy and log group, the `embed-dlq` alarm; in-place updates to the
   SNS topic policy, the API role policy (adds `s3:PutObject` on `embed-requests/*`) and the release role policies. **Stop if the plan replaces
   (`-/+`) or destroys anything**, especially Aurora, the bucket or the API function.
2. `terraform -chdir=infra/aws apply embed-stage1.tfplan`.
3. `terraform -chdir=infra/aws output -json deployment | python3 scripts/configure_github_deploy.py` publishes `EMBED_ECR_REPOSITORY`
   (`EMBED_FUNCTION` is still empty and is skipped).

## Stage 2: image, database role, function

1. **Actions → Deploy staging → Run workflow on main.** With `EMBED_ECR_REPOSITORY` set it also builds and pushes the worker image
   (arm64 under emulation plus the model download, about 5 to 10 extra minutes) and prints the digest in the job summary
   (`embed_image_uri = ...@sha256:...`). It does not touch the worker function yet because `EMBED_FUNCTION` is empty.
2. Create the database role (operator, needs the master secret; the release from step 1 must already be deployed):
   `python scripts/bootstrap_database.py --embedder --function <migration function> --secret-arn <master secret ARN> --credentials-secret-arn <credentials secret ARN>`.
   It generates the role's password, stores it in the credentials secret before using it, creates `jobhunter_embedder` and applies its grants and
   its one read-only policy. Existing passwords are reused, not rotated.
3. Put the digest in your untracked tfvars (`embed_image_uri = "...@sha256:..."`), run `terraform plan` and read it. Expected additions: the function,
   the queue mapping, the bucket notification and the `embed-errors` and `embed-runaway` alarms. Apply, then publish the variables again
   (`EMBED_FUNCTION` is now set).
4. **Deploy staging again.** It injects the worker's own database password into the function and updates its code to the digest.

## Stage 3: one controlled test

1. Make sure there is something to embed, for example a confirmed profile (jobs are empty until ingestion exists).
2. Write one flag by hand: `aws s3api put-object --bucket <documents bucket> --key embed-requests/manual-test` (fractions of a cent).
3. Watch the log group `/aws/lambda/jobhunter-staging-embed`. Expect one line like `embedding pass: {'profiles': {'ready': 1}, ...}`. The first run is a cold
   start (image pull and about 7 s of model load, unmeasured on real Lambda): record the time for the report.
4. Check both queues are empty and no alarm fired. The flag object expires on its own after a day.

## Stage 4: switch the API on

Set `embed_on_save = "queue"` in the tfvars, plan (expect only the API function's environment variable to change), apply. From then on a profile
confirm or preferences save writes a flag after the commit and the profile gets its vector a few seconds later. `FOR_YOU_ENABLED` is a separate
switch and stays 0 until ingestion exists.

## Operating it

- **Pause everything:** Actions → Pause or resume staging backend. It now pauses the worker too (reserved concurrency 0), so nothing can wake Aurora.
  Flags that arrive while paused return to the queue; after five receives they move to the dead-letter queue and the `embed-dlq` alarm fires.
  That is harmless (the database is the source of truth): resume, then clear the dead-letter queue with `aws sqs purge-queue`, and write one flag.
- **Stop new work only:** `embed_on_save = "0"`, apply.
- **Backfill or re-embed after a model or text-version change:** write one flag (a changed text version or model is picked up automatically), or for a
  forced full re-embed invoke the function directly with `{"force": true}`.
- **Remove the worker:** set `embed_image_uri = ""` and apply. The function, mapping, notification and function alarms go; the queue stays.
- **Alarms** go to the existing activity topic: `embed-dlq` (a message failed five times), `embed-errors`, `embed-runaway`.

## Still unverified (check on the first real run)

- The S3 to SQS to Lambda path in this account and VPC, and retry behaviour under the reserved-concurrency cap.
- Cold-start time of the image, and arm64 speed (local timings are x86).
- That the bucket lifecycle rule and notification apply cleanly next to the existing bucket settings (a bucket allows one of each).
- That the migration role can set the new role's session limits and grant to it exactly as it already does for the application role (both roles are created by the operator bootstrap; this has not been run against Aurora).
