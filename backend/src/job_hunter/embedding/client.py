"""Validate vectors returned by the standalone embedding service."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DIMENSIONS = 512
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class EmbedderUnavailable(Exception):
    """The embedding service could not complete a request."""


class InvalidEmbeddingResponse(Exception):
    """The service response is unsafe to persist or compare."""


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    embeddings: tuple[tuple[float, ...], ...]


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...


@dataclass(frozen=True)
class HttpEmbedder:
    base_url: str
    timeout_seconds: float = 15.0

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not texts or any(not isinstance(value, str) or not value.strip() for value in texts):
            raise ValueError("texts must contain nonblank strings")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        body = json.dumps({"inputs": list(texts)}).encode("utf-8")
        request = Request(
            self.base_url.rstrip("/") + "/v1/embed",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise EmbedderUnavailable("embedding service unavailable") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise InvalidEmbeddingResponse("embedding response exceeds size limit")
        try:
            result = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidEmbeddingResponse("embedding response is not JSON") from exc
        if not isinstance(result, dict):
            raise InvalidEmbeddingResponse("embedding response must be an object")
        model = result.get("model")
        vectors = result.get("embeddings")
        truncated = result.get("truncated")
        if not isinstance(model, str) or not model.strip() or result.get("backend") not in {"fastembed", "bedrock"}:
            raise InvalidEmbeddingResponse("embedding model is missing or not semantic")
        if result.get("dimensions") != DIMENSIONS or result.get("normalized") is not True:
            raise InvalidEmbeddingResponse("embedding dimensions or normalization differ")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise InvalidEmbeddingResponse("embedding count differs from input count")
        if not isinstance(truncated, list) or truncated != [False] * len(texts):
            raise InvalidEmbeddingResponse("embedding text was truncated or flags are missing")
        validated = []
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != DIMENSIONS:
                raise InvalidEmbeddingResponse("embedding has wrong dimensions")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                   for value in vector):
                raise InvalidEmbeddingResponse("embedding contains a non-finite or non-numeric value")
            if not 0.99 <= math.sqrt(sum(float(value) ** 2 for value in vector)) <= 1.01:
                raise InvalidEmbeddingResponse("embedding is not normalized")
            validated.append(tuple(float(value) for value in vector))
        return EmbeddingResult(model=model, embeddings=tuple(validated))
