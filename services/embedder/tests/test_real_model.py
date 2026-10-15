"""Slow: loads the real jina model. Run with `pytest -m real_model` (needs the model cache or network)."""
from __future__ import annotations

import math
import os

import pytest

from embedder_service.config import Settings

pytestmark = pytest.mark.real_model


@pytest.fixture(scope="module")
def backend():
    from embedder_service.backends.fastembed_backend import FastembedBackend

    s = Settings.from_env({"EMBEDDER_CACHE_DIR": os.environ.get("EMBEDDER_CACHE_DIR", "/models")})
    return FastembedBackend(s.model_name, s.dimensions, s.cache_dir)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_dimensions_and_norm(backend):
    v = backend.embed(["Senior Python backend engineer, FastAPI and PostgreSQL"])[0]
    assert len(v) == 512
    assert math.isclose(dot(v, v), 1.0, rel_tol=1e-5)


def test_deterministic(backend):
    a = backend.embed(["data analyst role"])[0]
    b = backend.embed(["data analyst role"])[0]
    assert dot(a, b) == pytest.approx(1.0, abs=1e-5)


def test_related_closer_than_unrelated(backend):
    q, rel, unrel = backend.embed([
        "Python backend developer building REST APIs",
        "Software engineer working on server-side web services in Python",
        "Pastry chef preparing desserts for a restaurant kitchen",
    ])
    assert dot(q, rel) > dot(q, unrel) + 0.1
