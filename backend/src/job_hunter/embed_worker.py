"""Lambda entry point of the AWS embed worker (``job_hunter.embed_worker.handler``).

The event is ignored: S3 flags reach this function as SQS messages, but what to embed is recomputed from
the database every time (see docs/design/11-EMBEDDING-WORKER.md). The only event content that matters is
``{"force": true}`` sent by an operator through a direct invoke; it is honoured only when the event is not an
SQS delivery, so a flag can never request a forced re-embed.

Locally (``python -m job_hunter.embed_worker``) the same code runs against the Compose database, using the
HTTP embedder service instead of an in-process model.
"""

from __future__ import annotations

import logging
import os
import time

from job_hunter.embedding import flag
from job_hunter.embedding.client import EmbeddingResult, HttpEmbedder
from job_hunter.embedding.settings import embedder_model_name, embedder_url
from job_hunter.embedding.worker import run_pass

DB_ROLE = "jobhunter_embedder"
SAFETY_SECONDS = 90          # leave this much of the Lambda timeout for shutdown
DEFAULT_BUDGET_SECONDS = 840  # when there is no Lambda context (local runs)
log = logging.getLogger(__name__)


class LazyBackendEmbedder:
    """In-process embedder over ``embedder_service.backends``; loads the model on the first real call.

    A run with nothing to embed therefore never pays the model load. The texts are used as they are, like
    the HTTP client, which rejects results for truncated input."""

    def __init__(self, backend_factory=None, max_chars: int = 30_000):
        self._backend_factory = backend_factory or self._default_backend
        self._backend = None
        self._max_chars = max_chars

    @staticmethod
    def _default_backend():
        from embedder_service.backends import build_backend
        from embedder_service.config import Settings
        return build_backend(Settings.from_env())

    def embed(self, texts) -> EmbeddingResult:
        if not texts or any(not isinstance(value, str) or not value.strip() for value in texts):
            raise ValueError("texts must contain nonblank strings")
        if any(len(value) > self._max_chars for value in texts):
            raise ValueError("text exceeds the embedder's character limit")
        if self._backend is None:
            started = time.perf_counter()
            self._backend = self._backend_factory()
            log.info("embedding model loaded in %.1fs", time.perf_counter() - started)
        vectors = self._backend.embed(list(texts))
        return EmbeddingResult(model=self._backend.model_id,
                               embeddings=tuple(tuple(float(x) for x in vector) for vector in vectors))


def build_engine():
    """Engine for the embed worker's own database role (never the application role)."""
    if os.getenv("APP_ENV") == "aws":
        from job_hunter.adapters.aws_config import password_engine
        return password_engine(os.environ["DATABASE_HOST"], os.getenv("DATABASE_NAME", "jobhunter"),
                               os.getenv("DATABASE_USERNAME") or DB_ROLE)
    from sqlalchemy import create_engine
    return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def build_embedder():
    if (os.getenv("EMBEDDER_MODE") or "inprocess").strip().lower() == "http":
        return HttpEmbedder(embedder_url(), timeout_seconds=120)
    return LazyBackendEmbedder()


def _budget_seconds(context) -> float:
    if context is not None and hasattr(context, "get_remaining_time_in_millis"):
        return max(30.0, context.get_remaining_time_in_millis() / 1000 - SAFETY_SECONDS)
    return float(os.getenv("EMBED_MAX_SECONDS") or DEFAULT_BUDGET_SECONDS)


def wants_force(event) -> bool:
    """True only for an operator's direct ``{"force": true}`` invoke, never for an SQS delivery."""
    return isinstance(event, dict) and "Records" not in event and event.get("force") is True


_engine = None
_embedder = None


def handler(event, context):
    global _engine, _embedder
    logging.getLogger().setLevel(logging.INFO)
    if _engine is None:
        _engine = build_engine()
    if _embedder is None:
        _embedder = build_embedder()
    result = run_pass(_engine, _embedder, model=embedder_model_name(),
                      deadline=time.monotonic() + _budget_seconds(context),
                      batch_size=int(os.getenv("EMBED_BATCH_JOBS") or 8), force=wants_force(event))
    # Time ran out with work left: wake the next run, but only if this one made progress. Every chained run
    # must embed at least one previously pending item, so the chain ends once the pending set is empty.
    chained = False
    if result.remaining and result.progress > 0 and not result.busy:
        chained = flag.write_flag()
    return {**result.summary(), "chained": chained}


def main() -> int:  # pragma: no cover - local convenience
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    print(handler({}, None))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
