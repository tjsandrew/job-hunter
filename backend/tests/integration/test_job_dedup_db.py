"""Cross-source de-duplication against real PostgreSQL: import two sources, check the links, the Discover lists and the review rules."""
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from job_hunter.api.main import app
from job_hunter.config import settings
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import Job, User
from job_hunter.embedding.job_text import JOB_TEXT_VERSION
from job_hunter.embedding.pending import pending_job_ids
from job_hunter.import_jobs import SQLAlchemyJobRepository, import_report, upsert_records
from job_hunter.ingestion.discovery import DiscoveryReport

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                                reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")
client = TestClient(app)
HEADERS = {"X-Dev-User": "dedup-user"}
DESCRIPTION = ("You will build and run data pipelines for the platform team. Requirements include strong SQL, Python, "
               "experience with orchestration tools, careful testing and clear communication with analysts and engineers.")


def record(source, board, external_id, employer, **overrides):
    return {"source": source, "source_board": board, "external_id": external_id, "dedup_key": f"{source}:{board}:{external_id}",
            "source_url": f"https://{source}.example/{external_id}", "title": "Data Engineer", "employer": employer,
            "location": "Singapore", "description": DESCRIPTION, "posted_at": "2026-10-01T00:00:00Z",
            "fetched_at": "2026-10-20T00:00:00Z", **overrides}


@pytest.fixture
def world(monkeypatch):
    engine = create_engine(settings.migration_database_url)
    token = uuid4().hex[:10]
    employer = f"Dedupco{token}"
    user_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(User(id=user_id, auth_subject=f"dedup-{user_id}", display_name="dedup", plan="free"))
    monkeypatch.setitem(DEV_USERS, "dedup-user", (user_id, "dedup"))
    yield engine, employer
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
        for table in ("job_reviews", "applications"):
            db.execute(text(f"DELETE FROM {table} WHERE user_id=:uid"), {"uid": user_id})
        db.execute(text("DELETE FROM users WHERE id=:uid"), {"uid": user_id})
        db.execute(text("DELETE FROM jobs WHERE company LIKE :name"), {"name": f"{employer}%"})
    engine.dispose()


def load(engine, *records):
    with Session(engine) as db, db.begin():
        return import_report(SQLAlchemyJobRepository(db), DiscoveryReport(jobs=list(records)))


def discover(employer):
    response = client.get("/v1/recommendations", params={"q": employer, "limit": 100}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_two_sources_become_one_job_with_the_other_source_listed(world):
    engine, employer = world
    stats = load(engine, record("greenhouse", "dedupboard", "1", employer),
                 record("mycareersfuture", "sg", "2", f"{employer} Singapore Pte Ltd", location="Tanjong Pagar, Singapore"))
    assert (stats.new, stats.linked) == (2, 2)
    with Session(engine) as db:
        rows = {job.source: job for job in db.scalars(select(Job).where(Job.company.like(f"{employer}%")))}
        assert rows["greenhouse"].canonical_job_id is None and rows["mycareersfuture"].canonical_job_id == rows["greenhouse"].id
        assert pending_job_ids(db, text_version=JOB_TEXT_VERSION, model=None, limit=10000, everything=True).count(rows["mycareersfuture"].id) == 0
    items = discover(employer)
    assert len(items) == 1 and items[0]["job"]["source"] == "greenhouse"
    assert [seen["source"] for seen in items[0]["job"]["also_seen_on"]] == ["mycareersfuture"]


def test_a_reimport_changes_no_links_and_no_rows(world):
    engine, employer = world
    records = [record("greenhouse", "dedupboard", "1", employer), record("mycareersfuture", "sg", "2", employer)]
    load(engine, *records)
    again = load(engine, *records)
    assert (again.new, again.updated, again.unchanged, again.linked) == (0, 0, 2, 0)
    with Session(engine) as db:
        assert db.scalar(select(text("count(*)")).select_from(Job).where(Job.company.like(f"{employer}%"))) == 2


def test_saving_the_duplicate_hides_the_canonical_row_and_both_stay_openable(world):
    engine, employer = world
    load(engine, record("greenhouse", "dedupboard", "1", employer), record("adzuna", "sg", "3", employer))
    with Session(engine) as db:
        rows = {job.source: job for job in db.scalars(select(Job).where(Job.company.like(f"{employer}%")))}
        canonical, duplicate = str(rows["greenhouse"].id), str(rows["adzuna"].id)
    assert [item["job"]["id"] for item in discover(employer)] == [canonical]
    assert client.put(f"/v1/jobs/{duplicate}/review", json={"decision": "saved"}, headers=HEADERS).status_code == 200
    assert discover(employer) == []                              # the user already saved this posting under another source
    assert client.get(f"/v1/jobs/{duplicate}", headers=HEADERS).status_code == 200
    saved = client.get("/v1/jobs/reviewed", params={"decision": "saved"}, headers=HEADERS).json()["items"]
    assert [item["job"]["id"] for item in saved] == [duplicate]


def test_a_better_source_arriving_later_takes_over_without_losing_the_old_row(world):
    engine, employer = world
    load(engine, record("adzuna", "sg", "3", employer))
    with Session(engine) as db:
        adzuna_id = db.scalar(select(Job.id).where(Job.company.like(f"{employer}%")))
    load(engine, record("greenhouse", "dedupboard", "1", employer))
    with Session(engine) as db:
        rows = {job.source: job for job in db.scalars(select(Job).where(Job.company.like(f"{employer}%")))}
        assert rows["adzuna"].id == adzuna_id and rows["adzuna"].canonical_job_id == rows["greenhouse"].id
    assert [item["job"]["source"] for item in discover(employer)] == ["greenhouse"]


def test_an_old_row_gets_its_key_without_a_new_embedding_request(world):
    engine, employer = world
    load(engine, record("greenhouse", "dedupboard", "1", employer))
    with Session(engine) as db, db.begin():
        db.execute(text("UPDATE jobs SET match_key = NULL, also_seen_on = NULL WHERE company LIKE :name"), {"name": f"{employer}%"})
        before = db.scalar(select(Job.updated_at).where(Job.company.like(f"{employer}%")))
    stats = load(engine, record("greenhouse", "dedupboard", "1", employer))
    assert stats.unchanged == 1
    with Session(engine) as db:
        job = db.scalar(select(Job).where(Job.company.like(f"{employer}%")))
        assert job.match_key and job.updated_at == before
