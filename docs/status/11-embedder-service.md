# Handoff 11 — Embedder service

Implemented 15 October 2026 on `noah/embedder-service`. Local commit only; no push or PR. This delivers a standalone
text-to-vector HTTP service. Nothing else in the app calls it yet: vector storage, templates, semantic matching and
evaluation are a separate plan and are not started.

## What was built

- `services/embedder/`: FastAPI service, one endpoint that matters (`POST /v1/embed`), plus `/health` and `/v1/model`.
  Wire format and error codes are in `services/embedder/CONTRACT.md`.
- Three interchangeable backends behind one interface, selected by `EMBEDDER_SERVICE_BACKEND`:
  `fastembed` (default, `jinaai/jina-embeddings-v2-small-en`, 512-d, local ONNX), `bedrock` (Titan Text Embeddings v2
  at 512 dims) and `fake` (deterministic word hashing for tests).
- Opt-in compose service `embedder` under profile `embedder` on `127.0.0.1:8100`. `make up` and CI are unchanged.
- Makefile targets `embedder-up`, `embedder-down`, `test-embedder`.
- Model baked into the image at build; unprivileged runtime user; dependencies pinned in `requirements.lock`.

## Files changed

- New: everything under `services/embedder/`, this handoff.
- Edited: `compose.yaml` (one service block, profile-gated), `Makefile` (three targets and `.PHONY`).

## Verified (commands run in Docker on 15 October 2026)

| Check | Result |
|---|---|
| Contract + backend + config tests (fake backend, mocked Bedrock client) | 28 passed |
| Real-model tests (`-m real_model`, baked jina model) | 3 passed: 512 dims, norm 1.0, deterministic, related pair closer than unrelated |
| Live service: `/health`, `/v1/model`, `/v1/embed` | 200, `dimensions` 512, all norms 1.0, `healthy` in compose |
| Error paths over HTTP | empty list, blank text (names index), 65 texts, malformed JSON all 422 with the documented codes |
| Over-long text | 200 with `truncated: [true]` |
| Backend switch by env var only | `fake` then back to `fastembed`, same contract both times |
| Runtime user | uid 10001, not root |

Measured on this machine (CPU, Docker Desktop), indicative only:

- Single short text: median about 5 ms, p95 about 6 ms.
- 64 texts of about 2,500 characters: about 2.3 s.
- One 30,000-character text (about the cap): about 7.5 s.
- Resident memory about 210 MiB after load; image about 700 MB on disk, of which the model is about 125 MB.

## Finding that matters for the next plan

Similarity scores from this model sit in a high band. In one probe, a related pair scored 0.78 and unrelated pairs
0.64 and 0.65. Rank order is meaningful; **absolute thresholds are not**. The matching plan should rank by relative
score (and fuse by rank), not filter on a fixed cosine cut-off.

## Not verified / known gaps

- **Bedrock is not verified against live AWS.** Only the request/response shape is tested with a mocked client.
  Titan v2 embeds one text per call, so a 64-text batch is 64 calls.
- Quality on real job and profile text is untested; that is the evaluation phase of the next plan.
- No authentication or rate limiting. Fine for `127.0.0.1`, not for a shared deployment.
- Not wired into CI (`checks.yml` builds only `api`). A CI job is a follow-up to agree with the team.
- `make` is not installed on this machine, so the `test-embedder` target was exercised through its underlying
  `docker compose run` command rather than through `make` itself.
- A model-less image (`--build-arg BAKE_MODEL=0`) is supported by the Dockerfile but was not built or run.
- Behaviour near the model's 8,192-token limit beyond the 30,000-character cap was not explored.

## Next

Plan 2 (separate): consumer-side backend client, text templates, vector columns for jobs, backfill, semantic
retrieval, hybrid ranking and evaluation. Template wording waits until the existing profile embedding text has been
reviewed with the team.
