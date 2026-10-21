"""Service settings, read from environment variables (no extra dependencies)."""
from __future__ import annotations

import os
from dataclasses import dataclass

BACKENDS = ("fastembed", "bedrock", "fake")


@dataclass(frozen=True)
class Settings:
    backend: str = "fastembed"
    model_name: str = "jinaai/jina-embeddings-v2-small-en"  # fastembed model id
    dimensions: int = 512  # the contract promises this size; a backend that disagrees fails at startup
    cache_dir: str = "/models"
    max_texts: int = 64
    max_chars: int = 30_000
    batch_size: int = 1  # texts per ONNX run; fastembed's own default (256) pads a whole request to its longest text and needs GBs on long job texts
    bedrock_model_id: str = "amazon.titan-embed-text-v2:0"
    aws_region: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        e = os.environ if env is None else env
        backend = e.get("EMBEDDER_SERVICE_BACKEND", "fastembed").strip().lower()
        if backend not in BACKENDS:
            raise ValueError(f"EMBEDDER_SERVICE_BACKEND must be one of {BACKENDS}, got {backend!r}")

        def num(name: str, default: int) -> int:
            raw = e.get(name)
            if raw is None or raw == "":
                return default
            value = int(raw)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            return value

        return cls(
            backend=backend,
            model_name=e.get("EMBEDDER_MODEL_NAME", cls.model_name),
            dimensions=num("EMBEDDER_DIMENSIONS", cls.dimensions),
            cache_dir=e.get("EMBEDDER_CACHE_DIR", cls.cache_dir),
            max_texts=num("EMBEDDER_MAX_TEXTS", cls.max_texts),
            max_chars=num("EMBEDDER_MAX_CHARS", cls.max_chars),
            batch_size=num("EMBEDDER_BATCH_SIZE", cls.batch_size),
            bedrock_model_id=e.get("EMBEDDER_BEDROCK_MODEL_ID", cls.bedrock_model_id),
            aws_region=e.get("AWS_REGION") or e.get("AWS_DEFAULT_REGION") or None,
        )
