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
