# Embedder service

A small, standalone HTTP service: text in, fixed-size vector out. No database, no imports from the rest of the repo.
The wire format is in [CONTRACT.md](CONTRACT.md).

## Run

From the repo root (`make up` already starts it; these are for working on the service alone):

```sh
make embedder-up        # docker compose up --build -d embedder
curl -s localhost:8100/health
curl -s localhost:8100/v1/embed -H 'content-type: application/json' \
  -d '{"inputs": ["Python backend engineer"]}'
make embedder-down
```

The default image bakes the model in (about 125 MB), so it starts offline in a few seconds.

## Test

```sh
make test-embedder      # contract + backend + config tests, no model needed
```

Real-model checks (dimension, norm, determinism, related-vs-unrelated) are marked `real_model` and run inside the
image against the baked model:

```sh
docker compose run --rm --no-deps --user root \
  -v "$PWD/services/embedder/tests:/app/tests:ro" embedder \
  sh -c 'pip install -q -c requirements.lock pytest httpx && pytest /app/tests -m real_model -o addopts= -q'
```

## Configuration

| Env var | Default | |
|---|---|---|
| `EMBEDDER_SERVICE_BACKEND` | `fastembed` | `fastembed`, `bedrock` or `fake` |
| `EMBEDDER_MODEL_NAME` | `jinaai/jina-embeddings-v2-small-en` | fastembed model id |
| `EMBEDDER_DIMENSIONS` | `512` | startup fails if the backend disagrees |
| `EMBEDDER_MAX_TEXTS` / `EMBEDDER_MAX_CHARS` | `64` / `30000` | request limits |
| `EMBEDDER_CACHE_DIR` | `/models` | where fastembed finds the model |
| `EMBEDDER_BEDROCK_MODEL_ID` | `amazon.titan-embed-text-v2:0` | bedrock backend only |
| `AWS_REGION` | unset | bedrock backend only |

Image build args: `INSTALL_EXTRAS` (`bedrock`, `bedrock,test`), `BAKE_MODEL` (`0` skips downloading the model),
`EMBEDDER_MODEL_NAME`.

## Swapping the model or backend

- **Same service, different backend:** change `EMBEDDER_SERVICE_BACKEND` and restart. The contract is identical.
- **Consumers:** read `model` from the response and store it with each vector. After a swap, vectors from the old
  model must be re-embedded; they are not comparable even at the same dimensionality.
- **Skip the service in AWS:** a consumer may call Bedrock directly instead; this service only exists so the rest of
  the app has one stable embedding interface.

## Layout

```
src/embedder_service/
  app.py        HTTP layer: validation, limits, error shape
  config.py     env settings
  backends/     base protocol, fastembed, bedrock, fake
tests/          contract, backends, config, real-model (slow)
```

Dependencies are pinned in `requirements.lock` (resolved on Python 3.12 with the `bedrock` and `test` extras so one
file constrains every image variant).
