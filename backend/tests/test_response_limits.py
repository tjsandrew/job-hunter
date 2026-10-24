from __future__ import annotations

import io

import pytest

from job_hunter.ingestion import discovery
from job_hunter.ingestion.discovery import ProviderRequestError


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def serve(monkeypatch, size):
    body = b'{"jobs": [], "pad": "' + b"x" * size + b'"}'
    monkeypatch.setattr(discovery, "urlopen", lambda request, timeout: Response(body))


def test_a_big_greenhouse_board_is_read(monkeypatch):
    serve(monkeypatch, 12_000_000)       # Cloudflare's board is bigger than the default limit
    assert discovery._fetch_json("https://example.test/board", 5, "greenhouse")["jobs"] == []


def test_other_feeds_keep_the_smaller_limit(monkeypatch):
    serve(monkeypatch, 12_000_000)
    with pytest.raises(ProviderRequestError) as caught:
        discovery._fetch_json("https://example.test/search", 5, "mycareersfuture")
    assert caught.value.kind == "response_too_large" and "8 MB" in str(caught.value)


def test_greenhouse_is_still_bounded(monkeypatch):
    serve(monkeypatch, 33_000_000)
    with pytest.raises(ProviderRequestError) as caught:
        discovery._fetch_json("https://example.test/board", 5, "greenhouse")
    assert caught.value.kind == "response_too_large" and "32 MB" in str(caught.value)
