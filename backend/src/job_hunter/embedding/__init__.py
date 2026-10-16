"""Backend client for the generic embedding service."""

from .client import Embedder, EmbeddingResult, EmbedderUnavailable, InvalidEmbeddingResponse, HttpEmbedder

__all__ = ["Embedder", "EmbeddingResult", "EmbedderUnavailable", "InvalidEmbeddingResponse", "HttpEmbedder"]
