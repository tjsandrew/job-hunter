# Embedding worker: rollout and operations

Design and rationale: [design brief 11](../design/11-EMBEDDING-WORKER.md). This page is the checklist for putting it on AWS and running it.
Status: **deployed to staging since 24 October 2026** (S3 flag, SQS queue with a dead-letter queue, embedding Lambda; semantic "For you" is on). The pipeline was checked end to end on 26 October 2026. The stages below are for operating the worker and for setting it up in a new environment. Tested before rollout: unit and database tests, Terraform `validate` and mocked-plan tests, and the worker image (x86 and ARM64 builds, handler through the Lambda runtime emulator). Dollar figures are estimates.

Merging a change deploys nothing. Every AWS-facing step below is manual, and each one is small and reversible.

## Cost expectations

- Idle: about $0. SQS and Lambda bill per request or run; the queue, the function and the flag objects have no hourly cost.
- A profile embed is a few seconds of compute (fractions of a cent). Embedding about 1,000 job descriptions is roughly $0.06 at 2 GB; the
  worker runs at 3 GB for about the same cost per job. Both are inside the Lambda free tier at this scale.
- The only way it can cost real money is a loop that keeps Aurora awake or the worker running. Guards: reserved concurrency 2, a run may chain
  only if it made progress, the `embed-runaway` alarm (more than 60 runs in an hour), the `embed-dlq` alarm, and the account budget alert.
- ECR storage for the worker image (about 1.3 GB plus the model) is roughly $0.15 a month.

## Before you start (free checks)

1. Check that no Deploy staging run is in progress.
2. Confirm the budget alert exists: `budget_alert_emails` is set in the committed `infra/aws/staging.tfvars` (or in your own tfvars in a new environment) and the plan includes `aws_budgets_budget.monthly`.
3. Confirm the account's Lambda concurrency allows the reservations (the reserved total is 20: API 10, migration 1, embed 2, LLM worker 5, discovery 1, import 1; AWS also keeps at least 100 unreserved, so the account limit must be at least 120):
   `aws lambda get-account-settings --query AccountLimit.ConcurrentExecutions`.

## Stage 1: queue and permissions (no function yet)

1. `terraform -chdir=infra/aws plan -var-file=staging.tfvars -out embed-stage1.tfplan` and **read the plan before applying**. Expected: the ECR repository, two SQS queues
   and the queue policy, the lifecycle configuration, the worker IAM role, policy and log group, the `embed-dlq` alarm; in-place updates to the
   SNS topic policy, the API role policy (adds `s3:PutObject` on `embed-requests/*`) and the release role policies. **Stop if the plan replaces
   (`-/+`) or destroys anything**, especially Aurora, the bucket or the API function.
2. `terraform -chdir=infra/aws apply embed-stage1.tfplan`.
3. `terraform -chdir=infra/aws output -json deployment | python3 scripts/configure_github_deploy.py` publishes `EMBED_ECR_REPOSITORY`
   (`EMBED_FUNCTION` is still empty and is skipped).

## Stage 2: image, database role, function

1. **Actions → Deploy staging → Run workflow on main.** With `EMBED_ECR_REPOSITORY` set it also builds and pushes the worker image
   (a native ARM64 build plus the model download, a few extra minutes) and prints the digest in the job summary
   (`embed_image_uri = ...@sha256:...`). It does not touch the worker function yet because `EMBED_FUNCTION` is empty.
2. Create the database role (operator, needs the master secret; the release from step 1 must already be deployed):
   `python scripts/bootstrap_database.py --embedder --function <migration function> --secret-arn <master secret ARN> --credentials-secret-arn <credentials secret ARN>`.
   It generates the role's password, stores it in the credentials secret before using it, creates `jobhunter_embedder` and applies its grants and
   its one read-only policy. Existing passwords are reused, not rotated.
3. Put the digest in `staging.tfvars` (`embed_image_uri = "...@sha256:..."`), run `terraform plan -var-file=staging.tfvars` and read it. Expected additions: the function,
   the queue mapping, the bucket notification and the `embed-errors` and `embed-runaway` alarms. Apply, then publish the variables again
   (`EMBED_FUNCTION` is now set).
4. **Deploy staging again.** It injects the worker's own database password into the function and updates its code to the digest.

## Stage 3: one controlled test

1. Make sure there is something to embed, for example a confirmed profile or newly imported jobs.
2. Write one flag by hand: `aws s3api put-object --bucket <documents bucket> --key embed-requests/manual-test` (fractions of a cent).
3. Watch the log group `/aws/lambda/jobhunter-staging-embed`. Expect one line like `embedding pass: {'profiles': {'ready': 1}, ...}`. The first run is a cold
   start (image pull and about 7 s of model load).
4. Check both queues are empty and no alarm fired. The flag object expires on its own after a day.

## Stage 4: switch the API on

Set `embed_on_save = "queue"` in the tfvars, plan (expect only the API function's environment variable to change), apply. From then on a profile
confirm or preferences save writes a flag after the commit and the profile gets its vector a few seconds later. `FOR_YOU_ENABLED` is a separate
switch (on in staging).

## Operating it

- **Pause everything:** Actions → Pause or resume staging backend. It now pauses the worker too (reserved concurrency 0), so nothing can wake Aurora.
  Flags that arrive while paused return to the queue; after five receives they move to the dead-letter queue and the `embed-dlq` alarm fires.
  That is harmless (the database is the source of truth): resume, then clear the dead-letter queue with `aws sqs purge-queue --queue-url <dead-letter-queue-url>`, and write one flag.
- **Stop new work only:** `embed_on_save = "0"`, apply.
- **Backfill or re-embed after a model or text-version change:** write one flag (a changed text version or model is picked up automatically), or for a
  forced full re-embed invoke the function directly with `{"force": true}`.
- **Remove the worker:** set `embed_image_uri = ""` and apply. The function, mapping, notification and function alarms go; the queue stays.
- **Alarms** go to the existing activity topic: `embed-dlq` (a message failed five times), `embed-errors`, `embed-runaway`.

## Verification after rollout

Verified:

- The S3 to SQS to Lambda path runs in this account and VPC. On the 26 October pipeline test the worker took 17 s, 7 s of it model load on a cold start (`eval/results/b4-pipeline-20261026/notes.md`).
- The bucket lifecycle rule and notification applied cleanly next to the existing bucket settings (a bucket allows one of each).
- The embedding worker has run against Aurora with its own database role (`jobhunter_embedder`), so the operator bootstrap's grants and session limits work.

Not verified:

- Retry behaviour under the reserved-concurrency cap.
- ARM64 speed compared with other architectures.
