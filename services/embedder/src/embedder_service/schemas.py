from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[str]


class Usage(BaseModel):
    texts: int


class EmbedResponse(BaseModel):
    model: str
    backend: str
    dimensions: int
    normalized: bool
    embeddings: list[list[float]]
    truncated: list[bool]
    usage: Usage


class ModelInfo(BaseModel):
    model: str
    backend: str
    dimensions: int
    normalized: bool
    max_texts: int
    max_chars: int
    ready: bool
