# 11 — Embedding worker (AWS)

Status: **design agreed, implementation in progress.** Nothing in this document has been run on AWS. Dollar figures are estimates from public price pages and third-party summaries; check them in the AWS pricing calculator before relying on them.

This brief covers how vectors are produced in the deployed (AWS) environment. Locally nothing changes: Docker Compose keeps the standalone HTTP embedder (`services/embedder`) and the synchronous `EMBED_ON_SAVE` hook.

## 1. Problem and constraints

- Jobs and confirmed profile versions need a 512-dimension vector (`job_embeddings`, `profile_embeddings`) before the semantic "For you" ranking can use them.
- Embedding is CPU-heavy. Measured locally with the baked Jina v2 small model, one long job description takes about 2.3 s at 2 GB (see `services/embedder/LAMBDA.md`), so a 64-job batch takes 147 s at 2 GB or 102 s at 3 GB. That does not fit the API function (1 GB, 29 s timeout, concurrency shared with users).
- The API and migration functions run in a **private VPC with no NAT gateway**. From that VPC the only AWS service reachable without paying is S3, through a **gateway endpoint** (AWS charges nothing for gateway endpoints). Calling another Lambda or SQS from inside the VPC needs a paid interface endpoint (about $9.5 a month per endpoint, figure from the infrastructure owner) or a NAT gateway (about $0.059 per hour plus $0.059 per GB in ap-southeast-1, roughly $43 a month).
- The account has a small shared budget. Anything that bills while idle needs a reason.

## 2. Decision

**S3 flag → SQS queue (with dead-letter queue) → dedicated embed Lambda, with the database as the source of truth.**

```
profile confirmed / preferences saved / ingestion batch finished
  1. rows are committed to Aurora (no vector yet)
  2. AFTER the commit, the API writes an empty flag object to S3: embed-requests/<unique id>
        (free S3 gateway endpoint; best effort, never fails the save)
  3. S3 sends an ObjectCreated notification (prefix embed-requests/) to an SQS queue
        (S3 sends it; the VPC needs no new network path)
  4. Lambda's SQS event source mapping invokes the embed function
        (Lambda sends it; no network path from the VPC needed)
  5. the embed function IGNORES the message contents. It asks the database which jobs and
     profiles lack a current vector, embeds them in-process, writes the vectors and exits
```

Principles:

- **The flag carries no information.** It only means "something may need embedding, go and look". What needs work is recomputed from database state on every run (level-triggered reconciliation). A lost, duplicated, late or reordered message cannot cause a missed or wrong embedding; the next run recomputes.
- **One embedder implementation.** The worker uses the same embedder backend code as the standalone service (`embedder_service.backends`), in-process. The API never loads the model.
- **Backfill is the same code path.** Uploading any object under `embed-requests/` (or invoking the function with an empty event) embeds everything missing.
- **A forced re-embed is never requested through the flag.** An operator invokes the function directly with `{"force": true}`; events that arrive from SQS are ignored for `force`.

### Why not a direct call (NAT or interface endpoint)

| Option | Network cost | Notes |
|---|---|---|
| S3 flag → SQS → worker (chosen) | about $0 | S3 gateway endpoint is free; S3 notifications and Lambda's SQS polling are service-side; SQS has a free tier (verify) |
| API sends to SQS directly | about $9.5 a month for an SQS interface endpoint | one hop fewer; failed sends visible in the request |
| API invokes the embed Lambda directly | about $9.5 a month for a Lambda interface endpoint, or NAT | profile saves would wait on a cold start inside the 29 s API limit |
| NAT gateway | about $43 a month plus data | gives general internet access; not justified for the embedder alone |
| EC2 embedder in the VPC | about $15 to $16 a month, running 24/7 | outside the pause workflow |

A NAT or endpoint would not make the system sturdier by itself. A direct call can still time out, hit a cold start, be throttled or fail in the embedder, so the database-driven "pending rows" reconciliation and a retry path would still be needed. Reliability comes from the queue (retries, dead-letter queue, alarms), not from the network path.

### Design consideration: switch to a direct SQS send if a NAT or SQS endpoint is provisioned anyway

If the project later provisions a **NAT gateway** (for example because ingestion must fetch job boards from inside the VPC) or an **SQS interface endpoint** for another reason, replace the S3 flag write with a direct `sqs:SendMessage` from the API and ingestion. That is the simpler, more conventional design: one hop fewer, no S3 notification or flag lifecycle rule, and an enqueue failure is visible in the request. The worker, queue and database reconciliation do not change; only the producer does (`embedding/flag.py`).

Rules of thumb:

- NAT exists for other reasons: send to SQS directly. SQS traffic through an existing NAT adds a negligible per-GB charge for tiny messages.
- Only per-service interface endpoints exist (for example for Lambda): endpoints are per service, so SQS needs its own. Add one only if the monthly cost is justified; otherwise keep the S3 flag.
- Do not add a NAT or endpoint only for the embedder.

## 3. Components

| Piece | Where | Notes |
|---|---|---|
| Flag producer | `backend/src/job_hunter/embedding/flag.py`, hooked after commit in `adapters/database.py` | `EMBED_ON_SAVE=queue` selects it; `1/true` keeps the synchronous local behaviour; `0` is off |
| Pending queries | `embedding/pending.py` | SQL selects jobs with no current vector (no row, newer job, different model, retryable status) and loops over confirmed profiles |
| Worker pass | `embedding/worker.py` | advisory lock, time budget, batch loop, progress counters |
| Lambda entry point | `embed_worker.py` (`job_hunter.embed_worker.handler`) | lazy model load, no work means no model load |
| Image | `backend/Dockerfile.embed-lambda` | backend code, `embedder_service` and the baked model; arm64 |
| DB role | `jobhunter_embedder` | least privilege, see section 5 |
| Infrastructure | `infra/aws/backend/embedder.tf` | ECR repo, queue, dead-letter queue, notification, lifecycle rule, function, alarms |

Function settings (initial values, tune after measuring on real Lambda):

| Setting | Value | Why |
|---|---|---|
| Memory | 3,008 MB | local measurements give about the same cost per job as 2 GB (about 4.6 to 4.7 GB-seconds) and about 30% faster; peak memory is about 1 GB at batch size 1 |
| Timeout | 900 s | Lambda maximum; the worker stops early and chains (below) |
| Reserved concurrency | 2 | must be at least the queue mapping's maximum concurrency or messages are throttled |
| Queue mapping | batch size 1, maximum concurrency 2 | |
| Queue visibility timeout | 6 x function timeout | AWS guidance for SQS event sources |
| Dead-letter queue | after 5 receives | alarm on depth > 0 |
| VPC | same private subnets and security group as the API | needs Aurora; needs no internet (model baked in, `HF_HUB_OFFLINE=1`) |
| Log retention | 7 days | same as the other functions |

## 4. Triggers and re-embedding

Flag writers (always after the database commit; `get_db` already runs post-commit work):

| Event | Where |
|---|---|
| Profile confirmed | `confirm_profile` in `api/main.py` |
| Preferences saved | `update_preferences` in `api/main.py` |
| Ingestion run finished | end of the ingestion/import run (one flag per run, not per row) |
| Embedding settings changed (text version or model bumped) | one flag after the deploy |
| Worker ran out of time with work left | the worker writes a new flag itself |
| Operator | upload any object under `embed-requests/`, or invoke the function |

A stored vector is current only if its status is `ready` and its text version, input hash and (when a model is passed in) model all match (`embedding/pipeline.py`, `_is_current`).

| Change | Result |
|---|---|
| Job text, profile or preferences edited | hash differs, re-embedded on the next run |
| New or reopened job | no row yet, embedded |
| `JOB_TEXT_VERSION` / `PROFILE_TEXT_VERSION` bumped | rows are keyed by (item, version), so everything is embedded under the new version; old-version rows stay for rollback. For you reads only its own version, so jobs without new-version vectors drop out of the semantic list until the worker finishes |
| Embedding model swapped | the worker passes the configured model name as `expected_model`; a different stored model counts as pending |
| `failed` / `pending` rows | retried after a back-off (one hour) or when the job is newer |
| `no_content` rows | retried only when the job changes |
| Force everything | operator invokes the function with `{"force": true}` |

A full re-embed of about 1,800 jobs is roughly 70 minutes of compute at 2 GB (about $0.11 by estimate), spread across several runs.

## 5. Database role and row-level security

Per-user tables are protected by `FORCE ROW LEVEL SECURITY` with the policy `user_id = app.user_id`. The API sets `app.user_id` from the verified login. Jobs and job embeddings are shared data with no policy.

The worker must find users whose confirmed profile needs embedding, which the normal application role cannot do. It therefore uses its own role:

- `jobhunter_embedder`, created by the operator bootstrap like the application and migration roles, with a generated password stored in the same credentials secret. It must not be a superuser and must not bypass row-level security (the managed admin cannot grant that attribute).
- Explicit grants only: SELECT on `jobs`, `profiles`, `profile_versions`, `preferences`; SELECT, INSERT and UPDATE on `job_embeddings` and `profile_embeddings`.
- One extra read-only policy, on `profiles` only: `CREATE POLICY embedder_list_users ON profiles FOR SELECT TO jobhunter_embedder USING (true)`. It lets the worker list the users with a confirmed profile.
- For each such user the worker sets `app.user_id` before reading profile data or writing the vector, exactly as `backfill_profiles` does, so writes still pass through the per-user policy.
- Longer statement and idle-transaction timeouts than the application role (embedding keeps a transaction open while the model runs).

## 6. Guardrails

- **Concurrency safety:** a Postgres advisory lock makes overlapping runs safe. A run that cannot take the lock exits successfully; the running worker releases the lock and then checks for pending work once more, so rows saved just before the release are still picked up.
- **No runaway chaining:** the worker writes a new flag only if time ran out, work remains and this run embedded at least one previously pending row. Every chained run must therefore make progress, and progress is bounded by the finite pending set.
- **Cheap no-op runs:** if nothing is pending the function exits before loading the model.
- **Pause:** the existing pause/resume control must include the embed function (reserved concurrency 0 when paused).
- **Aurora cost:** the flag is written right after a save, so the database is already awake. Do not add a frequent poller; it would stop Aurora pausing to zero. An optional once-a-day reconcile schedule is deliberately off.
- **Deploy safety:** the new steps in the deploy workflow and `scripts/deploy_aws.py` are skipped unless the embed variables are set, so merging this change deploys nothing new by itself.

## 7. Rollout (staged, each step reviewable and near-free)

1. `terraform plan` only, reviewed by a human. Then apply the first stage: ECR repository, queue and dead-letter queue, queue policy, lifecycle rule, IAM, alarms. No function yet.
2. Set the GitHub variables for the embed repository and function; Deploy staging builds and pushes the embed image.
3. Set `embed_image_uri`, plan and apply the second stage: function, queue mapping and bucket notification.
4. Run the operator bootstrap with the new role's password, then Deploy staging so the grants and policy exist.
5. Upload one flag object by hand against a small data set and watch the function logs, the queue and the dead-letter queue.
6. Only then set `EMBED_ON_SAVE=queue` and, when ingestion exists, `FOR_YOU_ENABLED=1`.

## 8. Not yet verified

- The S3 to SQS to Lambda path inside this account and VPC, including retry behaviour under the reserved-concurrency cap.
- Cold start of the container image on real Lambda (local model load is about 7 s), and ARM64 speed (local timings are x86).
- All dollar figures above.
