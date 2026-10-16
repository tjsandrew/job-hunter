"""Contract checks for the app-to-embedder boundary; no model or network needed."""

from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest

from job_hunter.embedding import HttpEmbedder, EmbedderUnavailable, InvalidEmbeddingResponse


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def valid_payload(count=1):
    return {
        "model": "jinaai/jina-embeddings-v2-small-en",
        "backend": "fastembed",
        "dimensions": 512,
        "normalized": True,
        "embeddings": [[0.0] * 511 + [1.0] for _ in range(count)],
        "truncated": [False] * count,
    }


def stub_response(monkeypatch, payload):
    def respond(request, timeout):
        assert request.full_url == "http://embedder:8100/v1/embed"
        assert timeout == 3
        assert json.loads(request.data) == {"inputs": ["Backend Engineer"]}
        return Response(json.dumps(payload).encode())
    monkeypatch.setattr("job_hunter.embedding.client.urlopen", respond)


def test_valid_response_preserves_model_and_vector(monkeypatch):
    stub_response(monkeypatch, valid_payload())
    result = HttpEmbedder("http://embedder:8100/", timeout_seconds=3).embed(["Backend Engineer"])
    assert result.model == "jinaai/jina-embeddings-v2-small-en"
    assert len(result.embeddings) == 1
    assert len(result.embeddings[0]) == 512
    assert result.embeddings[0][-1] == 1.0


@pytest.mark.parametrize("change", [
    {"dimensions": 384},
    {"normalized": False},
    {"model": ""},
    {"backend": "fake"},
    {"backend": None},
    {"embeddings": []},
    {"embeddings": [[0.0] * 384]},
    {"embeddings": [[0.0] * 512]},
    {"embeddings": [[0.0] * 511 + [float("nan")]]},
    {"truncated": [True]},
])
def test_rejects_unsafe_response(monkeypatch, change):
    stub_response(monkeypatch, valid_payload() | change)
    with pytest.raises(InvalidEmbeddingResponse):
        HttpEmbedder("http://embedder:8100", timeout_seconds=3).embed(["Backend Engineer"])


@pytest.mark.parametrize("error", [URLError("offline"), HTTPError("url", 503, "unready", {}, None), TimeoutError()])
def test_unavailable_service_has_one_caller_error(monkeypatch, error):
    def fail(*_args, **_kwargs):
        raise error
    monkeypatch.setattr("job_hunter.embedding.client.urlopen", fail)
    with pytest.raises(EmbedderUnavailable):
        HttpEmbedder("http://embedder:8100").embed(["Backend Engineer"])


def test_rejects_invalid_input_before_http(monkeypatch):
    monkeypatch.setattr("job_hunter.embedding.client.urlopen", lambda *_args, **_kwargs: pytest.fail("HTTP called"))
    with pytest.raises(ValueError):
        HttpEmbedder("http://embedder:8100").embed([" "])


@pytest.mark.parametrize("body_factory", [
    pytest.param(lambda: b"not json", id="malformed"),
    pytest.param(lambda: b"x" * (4 * 1024 * 1024 + 1), id="oversized"),
])
def test_rejects_malformed_or_oversized_body(monkeypatch, body_factory):
    monkeypatch.setattr("job_hunter.embedding.client.urlopen", lambda *_args, **_kwargs: Response(body_factory()))
    with pytest.raises(InvalidEmbeddingResponse):
        HttpEmbedder("http://embedder:8100").embed(["Backend Engineer"])
