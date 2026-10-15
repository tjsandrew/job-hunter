"""Amazon Bedrock backend (Titan Text Embeddings v2, 512 dims).

NOT verified against live AWS locally: the request/response shape follows the published
Titan v2 format and is covered by a mocked-client unit test only.
Titan v2 embeds one text per call, so a batch is a sequence of calls.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from .base import l2_normalize


class BedrockBackend:
    name = "bedrock"
    normalized = True

    def __init__(self, model_id: str, dimensions: int, region: str | None = None, client: Any = None):
        if client is None:
            import boto3  # optional dependency (extra "bedrock")

            client = boto3.client("bedrock-runtime", region_name=region)
        self._client = client
        self.model_id = model_id
        self.dimensions = dimensions

    def _one(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text, "dimensions": self.dimensions, "normalize": True})
        response = self._client.invoke_model(
            modelId=self.model_id, body=body, accept="application/json", contentType="application/json"
        )
        payload = json.loads(response["body"].read())
        vector = payload["embedding"]
        if len(vector) != self.dimensions:
            raise RuntimeError(f"Bedrock returned {len(vector)} dimensions, expected {self.dimensions}")
        return l2_normalize(vector)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]
