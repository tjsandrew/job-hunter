"""Deterministic, dependency-free backend for tests and CI.

Feature hashing over lowercase word tokens, so texts that share words get closer vectors.
This is NOT semantic. It only makes downstream tests meaningful without downloading a model.
"""
from __future__ import annotations

import hashlib
import re
from typing import Sequence

from .base import l2_normalize

_TOKEN = re.compile(r"[a-z0-9]+")


class FakeBackend:
    name = "fake"
    normalized = True

    def __init__(self, dimensions: int = 512, model_id: str = "fake-hash-embedder-v1"):
        self.dimensions = dimensions
        self.model_id = model_id

    def _bucket(self, token: str) -> tuple[int, float]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % self.dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        return index, sign

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN.findall(text.lower()) or [text]
        for token in tokens:
            index, sign = self._bucket(token)
            vector[index] += sign
        if not any(vector):  # tokens cancelled out exactly; fall back to a text-level bucket
            index, sign = self._bucket("\x00" + text)
            vector[index] = sign
        return l2_normalize(vector)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]
