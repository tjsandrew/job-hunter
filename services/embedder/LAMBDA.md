# Running the embedder on AWS Lambda

`Dockerfile.lambda` packages the same service as a Lambda container image: the AWS Lambda Web Adapter (pinned 1.0.0) turns
Lambda invocations into HTTP requests on port 8100, so the app and the HTTP contract ([CONTRACT.md](CONTRACT.md)) are
unchanged.

The Linux amd64 adapter executable is vendored at
`vendor/aws-lambda-adapter/v1.0.0/linux-amd64/lambda-adapter` from the official
`public.ecr.aws/awsguru/aws-lambda-adapter:1.0.0` image (digest
`sha256:b4da35991627bdac98a81c377d0cc28e6989687359576dfda9f0b64be835d648`).
Its SHA-256 is `a76f42498951cd77c2422999a80ab68a5d959b419993e7cff9cb7eec963bcd7f`,
checked during the image build. Vendoring avoids the anonymous Public ECR rate limit in CI.
This Dockerfile supports amd64 only; an ARM64 build needs a separately verified adapter executable.

```sh
docker build -f Dockerfile.lambda -t embedder-lambda .
# reuse an already-downloaded model instead of fetching it again:
docker build -f Dockerfile.lambda --build-context modelsrc=docker-image://job-hunter-embedder:latest -t embedder-lambda .
```

## Status: tested locally in Docker only, not on real Lambda

Checked on 2026-10-20 with `--read-only --tmpfs /tmp --memory N --cpus M` (Lambda gives about 1 vCPU per 1,769 MB):

- Starts and serves `/health`, `/v1/model`, `/v1/embed` with a read-only root filesystem and `HF_HUB_OFFLINE=1`.
- Vectors are identical to the regular image's (cosine 1.00000000, max difference 0 on 6 real job texts), so nothing needs
  re-embedding.
- **Not exercised locally:** the Web Adapter itself (Docker does not run Lambda extensions), the readiness gate, image pull
  time on real Lambda, and IAM/VPC. Verify these on a real function first.

**CI:** the `embedder` job in `.github/workflows/checks.yml` runs the 30 service tests, builds this image and the regular one with
`--build-arg BAKE_MODEL=0` (no model download), starts each with the fake backend and calls `/health`, `/v1/model` and `/v1/embed`.
That checks packaging and the contract on an x86 runner only: not ARM64, not the Web Adapter, not the real model.

## What the numbers say (batch size 1, job texts capped at 8,000 characters, desktop PC also in use so treat as rough)

| Lambda memory (about vCPU) | start to `/health` 200 | 1 text | 8 texts | 32 texts | 64 texts | peak memory |
|---|---|---|---|---|---|---|
| 1,769 MB (1.0) | 7.8 s | 7.8 s | 39 s | 118 s | 202 s | about 1.0 GB |
| 2,048 MB (1.16) | 7.0 s | 4.9 s | 25 s | 81 s | 147 s | about 1.0 GB |
| 3,008 MB (1.7) | 4.6 s | 3.6 s | 16 s | 51 s | 102 s | about 1.0 GB |

- **Cost per job text is about 1.6 to 4 s of compute**, because job texts are about 2,000 tokens. Short profile texts are
  much cheaper. A full 457-job backfill is several minutes of compute, so it must be split into requests of at most about
  16 texts per invoke and run from a worker, not behind a short timeout.
- **Memory is the trap.** fastembed's default batch size (256) pads a whole request to its longest text. With that, 8 job
  texts ran a 2 GB container out of memory. Even batch size 8 failed at 2 GB (8 texts) and at 3 GB (32 texts). The service now runs `EMBEDDER_BATCH_SIZE=1` by
  default, which keeps peak memory near 1 GB at any request size. Batch sizes 4 to 8 were somewhat faster but needed 4 GB to survive a 64-text request.
- **Set the Lambda timeout generously** (60 s minimum for interactive profile embeds; 300 s or more if a backfill
  sends large batches) and keep a single request small.
- **Cold start** is dominated by the roughly 7 s model load plus image pull, which this test cannot measure. A user-facing
  profile embed that hits a cold function would feel it; provisioned concurrency of 1 removes it if that matters.

## Settings that matter on Lambda

| Setting | Value | Why |
|---|---|---|
| `AWS_LWA_PORT`, `AWS_LWA_READINESS_CHECK_PATH` | `8100`, `/health` | the service loads the model in a background thread and returns 503 until ready; Lambda freezes the process between requests, so wait for readiness during init |
| `HF_HUB_OFFLINE=1`, `HOME`/`HF_HOME` under `/tmp` | set in the image | the root filesystem is read-only except `/tmp`; the model is baked into the image |
| Memory | 2,048 MB or more | peak is about 1 GB at batch size 1; more memory also means more CPU |
| VPC | none | the embedder never touches the database |
| Reserved concurrency | set a cap | bounds cost if something loops |
| Function URL / API Gateway | none if the backend invokes it with IAM | see the auth note below |

## Auth is a separate decision

The service has no authentication. Options are an optional shared `x-api-key` (with `/health` exempt) behind an HTTPS
endpoint, or direct IAM-signed `lambda:Invoke` from the backend with no public URL. The IAM route needs a small native
handler on this side and a `LambdaEmbedder` client on the backend side; neither is built yet.
