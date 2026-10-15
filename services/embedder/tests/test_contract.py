"""HTTP contract tests. Run against the fake backend, so they need no model download."""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from embedder_service.app import create_app
from embedder_service.backends.fake import FakeBackend
from embedder_service.config import Settings


@pytest.fixture()
def client():
    settings = Settings(backend="fake", max_texts=4, max_chars=50)
    with TestClient(create_app(settings, FakeBackend(512))) as c:
        yield c


def post(client, payload):
    return client.post("/v1/embed", json=payload)


def test_embed_shape_and_metadata(client):
    r = post(client, {"inputs": ["python backend engineer", "nurse"]})
    assert r.status_code == 200
    body = r.json()
    assert body["dimensions"] == 512
    assert body["backend"] == "fake"
    assert body["normalized"] is True
    assert body["usage"] == {"texts": 2}
    assert body["truncated"] == [False, False]
    assert len(body["embeddings"]) == 2
    for v in body["embeddings"]:
        assert len(v) == 512
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)


def test_deterministic_and_ordered(client):
    a = post(client, {"inputs": ["alpha", "beta"]}).json()["embeddings"]
    b = post(client, {"inputs": ["beta", "alpha"]}).json()["embeddings"]
    assert a[0] == b[1] and a[1] == b[0]


def test_shared_words_are_closer(client):
    v = post(client, {"inputs": ["python backend engineer", "backend python developer", "registered nurse"]})
    e = v.json()["embeddings"]
    dot = lambda x, y: sum(p * q for p, q in zip(x, y))  # noqa: E731
    assert dot(e[0], e[1]) > dot(e[0], e[2])


def test_truncation_is_flagged(client):
    r = post(client, {"inputs": ["short", "x" * 51]})
    assert r.status_code == 200
    assert r.json()["truncated"] == [False, True]


@pytest.mark.parametrize(
    "payload,status,code",
    [
        ({"inputs": []}, 422, "no_inputs"),
        ({"inputs": ["a"] * 5}, 422, "too_many_inputs"),
        ({"inputs": ["ok", "   "]}, 422, "blank_input"),
        ({"inputs": ["ok", ""]}, 422, "blank_input"),
        ({}, 422, "invalid_request"),
        ({"inputs": "not a list"}, 422, "invalid_request"),
        ({"inputs": [1, 2]}, 422, "invalid_request"),
        ({"inputs": ["a"], "extra": 1}, 422, "invalid_request"),
    ],
)
def test_error_shape(client, payload, status, code):
    r = post(client, payload)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"]


def test_blank_input_names_index(client):
    r = post(client, {"inputs": ["ok", "fine", " "]})
    assert "inputs[2]" in r.json()["error"]["message"]


def test_model_endpoint_and_health(client):
    assert client.get("/health").json()["status"] == "ok"
    info = client.get("/v1/model").json()
    assert info["dimensions"] == 512 and info["ready"] is True
    assert info["max_texts"] == 4 and info["max_chars"] == 50


def test_not_ready_returns_503():
    app = create_app(Settings(backend="fake"), backend=None)
    app.state.embedder.load_error = "boom"
    c = TestClient(app)  # no context manager: lifespan loader thread is not started
    r = c.get("/health")
    assert r.status_code == 503 and r.json()["error"]["code"] == "not_ready"
    r = c.post("/v1/embed", json={"inputs": ["x"]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "not_ready"
    assert c.get("/v1/model").json()["ready"] is False


def test_backend_failure_is_502_without_leaking_input():
    class Broken:
        name, model_id, dimensions, normalized = "fake", "m", 512, True

        def embed(self, texts):
            raise RuntimeError("secret user text: " + texts[0])

    c = TestClient(create_app(Settings(backend="fake"), Broken()))
    r = c.post("/v1/embed", json={"inputs": ["my private cv"]})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "backend_error"
    assert "private" not in r.text


def test_malformed_backend_output_is_502():
    class Wrong:
        name, model_id, dimensions, normalized = "fake", "m", 512, True

        def embed(self, texts):
            return [[0.0] * 3 for _ in texts]

    c = TestClient(create_app(Settings(backend="fake"), Wrong()))
    r = c.post("/v1/embed", json={"inputs": ["x"]})
    assert r.status_code == 502 and r.json()["error"]["code"] == "backend_error"
