"""Local ONNX model through fastembed (default: jina-embeddings-v2-small-en, 512-d)."""
from __future__ import annotations

import threading
from typing import Sequence

from .base import l2_normalize


class FastembedBackend:
    name = "fastembed"
    normalized = True

    def __init__(self, model_name: str, dimensions: int, cache_dir: str | None = None):
        from fastembed import TextEmbedding  # lazy: tests and other backends need not install it

        self.model_id = model_name
        self._lock = threading.Lock()  # one ONNX session; keep concurrent requests simple and safe
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        probe = self._run(["dimension probe"])[0]
        if len(probe) != dimensions:
            raise RuntimeError(
                f"model {model_name!r} produces {len(probe)}-dimension vectors, "
                f"but the service is configured for {dimensions}"
            )
        self.dimensions = dimensions

    def _run(self, texts: Sequence[str]) -> list[list[float]]:
        with self._lock:
            vectors = list(self._model.embed(list(texts)))
        return [l2_normalize([float(x) for x in v]) for v in vectors]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._run(texts)
