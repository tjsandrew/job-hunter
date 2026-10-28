"""Discover filters against PostgreSQL: they change one job list and never the saved preferences."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                                reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")

from fastapi.testclient import TestClient
from job_hunter.api.main import app

client = TestClient(app)
ALICE = {"X-Dev-User": "alice"}


def jobs(**params):
    response = client.get("/v1/recommendations", params={"limit": 100, **params}, headers=ALICE)
    assert response.status_code == 200, response.text
    return response.json()


def test_custom_work_mode_filters_this_list_only():
    before = client.get("/v1/preferences", headers=ALICE).json()
    remote = jobs(filters="custom", work_mode="remote")
    assert all((row["job"].get("work_mode") or "").casefold() == "remote" for row in remote["items"])
    assert remote["total"] <= jobs(filters="none")["total"]
    assert client.get("/v1/preferences", headers=ALICE).json() == before   # nothing was saved


def test_custom_location_with_no_matches_returns_an_empty_list():
    assert jobs(filters="custom", location="Nowhere-ville-xyz")["total"] == 0


def test_no_filters_shows_at_least_as_many_jobs_as_the_saved_defaults():
    assert jobs(filters="none")["total"] >= jobs()["total"]


def test_invalid_filters_are_rejected_with_a_clear_code():
    response = client.get("/v1/recommendations", params={"filters": "custom", "seniority": "novice"}, headers=ALICE)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILTERS"
