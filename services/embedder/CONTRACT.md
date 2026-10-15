# Embedder service HTTP contract (v1)

This is the stable surface. Models and backends change behind it; consumers should not.

The service is **generic**: it turns text into a vector. It does not know what the text means (job, profile, query).
The caller owns any text template and should store `model` next to each vector it keeps.

## `POST /v1/embed`

Request:

```json
{ "inputs": ["first text", "second text"] }
```

Response `200`:

```json
{
  "model": "jinaai/jina-embeddings-v2-small-en",
  "backend": "fastembed",
  "dimensions": 512,
  "normalized": true,
  "embeddings": [[0.01, -0.03, "... 512 floats ..."], ["..."]],
  "truncated": [false, false],
  "usage": { "texts": 2 }
}
```

| Field | Meaning |
|---|---|
| `embeddings[i]` | Vector for `inputs[i]` (order is preserved) |
| `normalized` | `true`: every vector has L2 norm 1, so cosine similarity equals the dot product |
| `model` | Identifier of the model that produced the vectors. **Vectors from different `model` values are never comparable**, even when `dimensions` match |
| `backend` | `fastembed`, `bedrock` or `fake` (the fake backend is not semantic; tests only) |
| `truncated[i]` | `true` if `inputs[i]` exceeded the character limit and was cut before embedding |

### Limits

| Rule | Default | Env var |
|---|---|---|
| Texts per request | 64 | `EMBEDDER_MAX_TEXTS` |
| Characters per text | 30,000 (longer is cut, flagged in `truncated`) | `EMBEDDER_MAX_CHARS` |
| Blank / whitespace-only text | rejected | n/a |

## `GET /v1/model`

Metadata only; works while the model is still loading (`ready: false`).

```json
{ "model": "...", "backend": "fastembed", "dimensions": 512, "normalized": true,
  "max_texts": 64, "max_chars": 30000, "ready": true }
```

## `GET /health`

`200 {"status":"ok","backend":...,"model":...}` once the model is loaded, otherwise `503` with a `not_ready` error.

## Errors

Every error has the same shape:

```json
{ "error": { "code": "blank_input", "message": "inputs[1] is empty or whitespace" } }
```

| HTTP | `code` | When |
|---|---|---|
| 422 | `invalid_request` | Malformed JSON, missing `inputs`, wrong types, unknown fields |
| 422 | `no_inputs` | `inputs` is an empty list |
| 422 | `too_many_inputs` | More than `max_texts` |
| 422 | `blank_input` | A text is empty or whitespace (message names the index) |
| 503 | `not_ready` | Model still loading, or failed to load (message says which) |
| 502 | `backend_error` | The model/backend failed or returned malformed vectors |

## Guarantees

- **Deterministic:** the same text and model give the same vector (within floating-point noise).
- **Stateless:** no database, no stored input. Logs contain counts and timings only, never text.
- **Fixed dimensionality:** the service refuses to start a backend whose vectors differ from `EMBEDDER_DIMENSIONS`
  (default 512, matching the database `vector(512)` columns).

## Not in v1

Authentication, rate limiting, per-request model selection, query/document prefixes, async batch jobs.
The service binds to `127.0.0.1` in compose; it needs auth before any shared deployment.

## Backends

| `EMBEDDER_SERVICE_BACKEND` | Model | Notes |
|---|---|---|
| `fastembed` (default) | `jinaai/jina-embeddings-v2-small-en`, local ONNX | 512-d native, Apache-2.0, baked into the image |
| `bedrock` | `amazon.titan-embed-text-v2:0` at 512 dims | Needs the `bedrock` extra, AWS credentials and `AWS_REGION`. **Not verified against live AWS** (mocked-client test only) |
| `fake` | deterministic word hashing | Tests and CI; not semantic |
