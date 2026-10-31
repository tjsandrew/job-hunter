"""The in-memory job pool against real PostgreSQL: Discover lists are identical with and without it, and any change shows
on the very next request."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session
from sqlalchemy import text

from job_hunter import job_pool
from job_hunter.api.main import job_out

from tests.integration.test_job_dedup_db import HEADERS, client, pytestmark, record, world  # noqa: F401
from tests.integration.test_listing_cleanup_db import pull


def listed(**params):
    response = client.get("/v1/recommendations", params={"limit": 100, **params}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return [(item["job"]["id"], item["score"], item["reasons"]) for item in response.json()["items"]], response.json()["total"]


@pytest.mark.parametrize("params", [{}, {"posted_within": 14}, {"include_expired": "true"}, {"filters": "none", "posted_within": 7},
                                    {"filters": "custom", "work_mode": "remote", "posted_within": 365}])
def test_lists_are_identical_with_and_without_the_pool(world, monkeypatch, params):
    engine, employer = world
    now = datetime.now(timezone.utc)
    pull(engine, record("greenhouse", f"b-{employer}", "1", employer, posted_at=now.isoformat()),
         record("greenhouse", f"b-{employer}", "2", employer, title="Platform Engineer", posted_at=(now - timedelta(days=20)).isoformat()))
    job_pool.clear()
    cached = listed(**params)
    monkeypatch.setenv("JOB_POOL_CACHE", "0")
    assert listed(**params) == cached


def test_a_change_shows_on_the_next_request(world):
    engine, employer = world
    now = datetime.now(timezone.utc)
    pull(engine, record("greenhouse", f"b-{employer}", "1", employer, posted_at=now.isoformat()))
    job_pool.clear()
    ids = lambda: {item[0] for item in listed(q=employer)[0]}
    assert len(ids()) == 1
    pull(engine, record("greenhouse", f"b-{employer}", "2", employer, title="Platform Engineer", posted_at=now.isoformat()))
    assert len(ids()) == 2                                                     # a new job
    with Session(engine) as db, db.begin():                                    # a closure that touches no timestamp
        db.execute(text("UPDATE jobs SET status = 'closed' WHERE company LIKE :name AND external_id = '2'"), {"name": f"{employer}%"})
    assert len(ids()) == 1


def test_the_pool_is_built_once_while_nothing_changes(world, monkeypatch):
    builds = []
    original = job_pool._rebuild
    monkeypatch.setattr(job_pool, "_rebuild", lambda *a: builds.append(1) or original(*a))
    job_pool.clear()
    listed(); listed(); listed()
    assert len(builds) == 1


def test_on_lambda_the_pool_rechecks_the_database_at_most_every_interval(world, monkeypatch):
    engine, employer = world
    now = datetime.now(timezone.utc)
    pull(engine, record("greenhouse", f"b-{employer}", "1", employer, posted_at=now.isoformat()))
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "jobhunter-staging-api")      # the Lambda default: 30 s
    assert job_pool.recheck_seconds() == 30
    job_pool.clear()
    ids = lambda: {item[0] for item in listed(q=employer)[0]}
    assert len(ids()) == 1
    pull(engine, record("greenhouse", f"b-{employer}", "2", employer, title="Platform Engineer", posted_at=now.isoformat()))
    assert len(ids()) == 1                                                     # within the interval: the copy, no query
    job_pool._checked_at.clear()                                               # the interval has passed
    assert len(ids()) == 2
    monkeypatch.setenv("JOB_POOL_RECHECK_SECONDS", "0")
    assert job_pool.recheck_seconds() == 0
