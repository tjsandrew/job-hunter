from __future__ import annotations

import pytest

from embedder_service.config import Settings


def test_defaults():
    s = Settings.from_env({})
    assert s.backend == "fastembed"
    assert s.model_name == "jinaai/jina-embeddings-v2-small-en"
    assert s.dimensions == 512 and s.max_texts == 64 and s.max_chars == 30_000
    assert s.batch_size == 1


def test_batch_size_override():
    assert Settings.from_env({"EMBEDDER_BATCH_SIZE": "2"}).batch_size == 2


def test_overrides():
    s = Settings.from_env({
        "EMBEDDER_SERVICE_BACKEND": "FAKE",
        "EMBEDDER_MAX_TEXTS": "8",
        "AWS_REGION": "ap-southeast-1",
    })
    assert s.backend == "fake" and s.max_texts == 8 and s.aws_region == "ap-southeast-1"


@pytest.mark.parametrize("env", [
    {"EMBEDDER_SERVICE_BACKEND": "openai"},
    {"EMBEDDER_MAX_TEXTS": "0"},
    {"EMBEDDER_MAX_CHARS": "-5"},
    {"EMBEDDER_BATCH_SIZE": "0"},
    {"EMBEDDER_DIMENSIONS": "abc"},
])
def test_invalid_values_fail_fast(env):
    with pytest.raises(ValueError):
        Settings.from_env(env)
