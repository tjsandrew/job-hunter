from __future__ import annotations

from ..config import Settings
from .base import EmbeddingBackend


def build_backend(settings: Settings) -> EmbeddingBackend:
    if settings.backend == "fake":
        from .fake import FakeBackend

        return FakeBackend(dimensions=settings.dimensions)
    if settings.backend == "fastembed":
        from .fastembed_backend import FastembedBackend

        return FastembedBackend(settings.model_name, settings.dimensions, settings.cache_dir, settings.batch_size)
    if settings.backend == "bedrock":
        from .bedrock import BedrockBackend

        return BedrockBackend(settings.bedrock_model_id, settings.dimensions, settings.aws_region)
    raise ValueError(f"unknown backend {settings.backend!r}")


__all__ = ["EmbeddingBackend", "build_backend"]
