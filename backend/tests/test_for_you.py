"""The flagged for-you route stays off by default and the switch parses sensibly (no database needed)."""
import pytest
from fastapi.testclient import TestClient

from job_hunter.api.main import app, db_for
from job_hunter.embedding import settings as embedding_settings


@pytest.fixture
def client():
    app.dependency_overrides[db_for] = lambda: iter([None])      # the disabled path never touches the database
    yield TestClient(app)
    app.dependency_overrides.pop(db_for, None)


@pytest.mark.parametrize("value,enabled", [(None, False), ("", False), ("0", False), ("no", False),
                                           ("1", True), ("true", True), (" TRUE ", True), ("on", True)])
def test_for_you_switch(monkeypatch, value, enabled):
    if value is None:
        monkeypatch.delenv("FOR_YOU_ENABLED", raising=False)
    else:
        monkeypatch.setenv("FOR_YOU_ENABLED", value)
    assert embedding_settings.for_you_enabled() is enabled


def test_for_you_route_is_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("FOR_YOU_ENABLED", raising=False)
    response = client.get("/v1/recommendations/for-you")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FOR_YOU_DISABLED"


@pytest.mark.parametrize("value,enabled", [(None, False), ("0", False), ("1", True), ("true", True)])
def test_embed_on_save_switch(monkeypatch, value, enabled):
    if value is None:
        monkeypatch.delenv("EMBED_ON_SAVE", raising=False)
    else:
        monkeypatch.setenv("EMBED_ON_SAVE", value)
    assert embedding_settings.embed_on_save_enabled() is enabled


@pytest.mark.parametrize("value,enabled", [(None, True), ("", True), ("1", True), ("0", False), ("false", False), (" OFF ", False), ("no", False)])
def test_fusion_switch_is_on_by_default(monkeypatch, value, enabled):
    if value is None:
        monkeypatch.delenv("FOR_YOU_FUSION", raising=False)
    else:
        monkeypatch.setenv("FOR_YOU_FUSION", value)
    assert embedding_settings.for_you_fusion_enabled() is enabled


class _FakeDb:
    """Just enough database for the route: no reviews, no jobs, no preferences."""

    def get(self, *_):
        return None

    def scalars(self, *_):
        return type("Rows", (), {"all": staticmethod(lambda: []), "__iter__": lambda self: iter(())})()

    info = {"current_user": type("U", (), {"id": "u1"})()}


def _wire_for_you(monkeypatch, fusion):
    from job_hunter.api import main
    from job_hunter.embedding.retrieval import RankedJob, RetrievalResult

    rows = tuple(RankedJob(job_id=j, rank=i, similarity=1.0, role="same", seniority="match", reasons=()) for i, j in enumerate("abc", 1))
    monkeypatch.setenv("FOR_YOU_ENABLED", "1")
    if fusion is None:
        monkeypatch.delenv("FOR_YOU_FUSION", raising=False)
    else:
        monkeypatch.setenv("FOR_YOU_FUSION", fusion)
    monkeypatch.setattr(main.bank_services, "get_confirmed_snapshot", lambda db: ("pv", 1, {}))
    monkeypatch.setattr(main.bank_services, "build_profile_snapshot", lambda db: {})
    monkeypatch.setattr(main.semantic, "semantic_for_you", lambda *a, **k: (RetrievalResult(ranked=rows, blocked=(), considered=3), None))
    monkeypatch.setattr(main.semantic, "matching", lambda db, ranked, q, job_out: list(ranked))
    monkeypatch.setattr(main.semantic, "page_items", lambda db, ranked, offset, limit, job_out, **k: [r.job_id for r in ranked[offset:offset + limit]])
    monkeypatch.setattr(main, "rank_jobs", lambda jobs, profile, prefs: [{"job": {"id": j}} for j in "cba"])
    def fake_db():
        yield _FakeDb()

    app.dependency_overrides[db_for] = fake_db
    return TestClient(app)


def test_for_you_route_fuses_the_keyword_ranking_by_default(monkeypatch):
    try:
        body = _wire_for_you(monkeypatch, None).get("/v1/recommendations/for-you").json()
    finally:
        app.dependency_overrides.pop(db_for, None)
    assert body["ranking_mode"] == "semantic" and body["ranking_fusion"] == "rrf-v1"
    assert body["ranking_version"].endswith("+rrf-v1")
    assert body["items"] == ["a", "c", "b"]                  # a: best similarity; c: best keyword; b: middle of both
    assert "Keyword and semantic" in body["ranking_status"]


def test_for_you_route_serves_the_semantic_order_when_fusion_is_off(monkeypatch):
    try:
        body = _wire_for_you(monkeypatch, "0").get("/v1/recommendations/for-you").json()
    finally:
        app.dependency_overrides.pop(db_for, None)
    assert body["ranking_fusion"] is None and body["items"] == ["a", "b", "c"]
    assert not body["ranking_version"].endswith("+rrf-v1")
