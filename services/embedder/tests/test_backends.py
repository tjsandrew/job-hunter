from __future__ import annotations

import io
import json
import math

import pytest

from embedder_service.backends import build_backend
from embedder_service.backends.bedrock import BedrockBackend
from embedder_service.backends.fake import FakeBackend
from embedder_service.config import Settings


def test_fake_is_deterministic_and_unit_length():
    b = FakeBackend(512)
    v1, v2 = b.embed(["Python engineer"]), b.embed(["python ENGINEER"])
    assert v1 == v2  # tokenisation is case-insensitive
    assert math.isclose(sum(x * x for x in v1[0]), 1.0, rel_tol=1e-9)


def test_fake_handles_punctuation_only_text():
    v = FakeBackend(512).embed(["!!!"])[0]
    assert len(v) == 512 and math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-9)


def test_build_backend_fake():
    b = build_backend(Settings(backend="fake", dimensions=64))
    assert b.name == "fake" and b.dimensions == 64


class _FakeBedrockClient:
    def __init__(self, dims):
        self.dims = dims
        self.calls = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        body = json.loads(kwargs["body"])
        vec = [3.0, 4.0] + [0.0] * (self.dims - 2)  # deliberately not unit length
        assert body["normalize"] is True and body["dimensions"] == self.dims
        return {"body": io.BytesIO(json.dumps({"embedding": vec, "inputTextTokenCount": 3}).encode())}


def test_bedrock_request_shape_and_normalisation():
    client = _FakeBedrockClient(512)
    b = BedrockBackend("amazon.titan-embed-text-v2:0", 512, client=client)
    out = b.embed(["a", "b"])
    assert len(client.calls) == 2  # one call per text
    assert client.calls[0]["modelId"] == "amazon.titan-embed-text-v2:0"
    assert json.loads(client.calls[0]["body"])["inputText"] == "a"
    assert len(out) == 2 and out[0][:2] == pytest.approx([0.6, 0.8])


def test_bedrock_rejects_wrong_dimensions():
    class Wrong:
        def invoke_model(self, **kwargs):
            return {"body": io.BytesIO(json.dumps({"embedding": [1.0] * 256}).encode())}

    b = BedrockBackend("m", 512, client=Wrong())
    with pytest.raises(RuntimeError, match="expected 512"):
        b.embed(["x"])
