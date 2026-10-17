"""The only thing the HTTP layer knows about a model."""
from __future__ import annotations

import math
from typing import Protocol, Sequence


class EmbeddingBackend(Protocol):
    name: str          # "fastembed" | "bedrock" | "fake"
    model_id: str      # reported to consumers; they store it next to each vector
    dimensions: int
    normalized: bool

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, in order. Raise on any failure; never return partial results."""
        ...


def l2_normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        raise ValueError("cannot normalise a zero vector")
    return [float(x) / norm for x in vector]
