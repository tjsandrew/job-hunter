"""Listing clean-up against real PostgreSQL: expired jobs leave Discover at once, a pull closes jobs its source stopped
listing, and a job listed again comes back."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from job_hunter.domain.models import Job
from job_hunter.import_jobs import STALE_AFTER, SQLAlchemyJobRepository, import_report
from job_hunter.ingestion.discovery import DiscoveryReport

from tests.integration.test_job_dedup_db import HEADERS, client, discover, pytestmark, record, world  # noqa: F401  (fixture and skip rule)


def pull(engine, *records, checked=()):
    with Session(engine) as db, db.begin():
        return import_report(SQLAlchemyJobRepository(db), DiscoveryReport(jobs=list(records), checked_boards=list(checked)))


def rows(engine, employer):
    with Session(engine) as db:
        return {job.external_id: job for job in db.scalars(select(Job).where(Job.company.like(f"{employer}%")))}


def test_a_job_past_its_closing_date_leaves_discover_before_any_pull(world):
    engine, employer = world
    soon = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    pull(engine, record("greenhouse", f"board-{employer}", "1", employer, expires_at=soon))
    assert len(discover(employer)) == 1
    with Session(engine) as db, db.begin():      # the closing date passes between two pulls
        db.execute(text("UPDATE jobs SET expires_at = now() - interval '1 hour' WHERE company LIKE :name"), {"name": f"{employer}%"})
    assert discover(employer) == []


def test_a_pull_closes_a_job_its_board_stopped_listing_and_reopens_it_when_listed_again(world):
    engine, employer = world
    board = f"board-{employer}"
    now = datetime.now(timezone.utc)
    old = (now - STALE_AFTER - timedelta(days=1)).isoformat()
    pull(engine, record("greenhouse", board, "gone", employer, title="Platform Engineer", fetched_at=old),
         record("greenhouse", board, "kept", employer, fetched_at=old))
    stats = pull(engine, record("greenhouse", board, "kept", employer, fetched_at=now.isoformat()), checked=[f"greenhouse:{board}"])
    assert (stats.unchanged, stats.closed_unseen) == (1, 1)
    assert {key: job.status for key, job in rows(engine, employer).items()} == {"gone": "closed", "kept": "open"}
    assert [item["job"]["id"] for item in discover(employer)] == [str(rows(engine, employer)["kept"].id)]

    before = rows(engine, employer)["gone"].updated_at
    stats = pull(engine, record("greenhouse", board, "gone", employer, title="Platform Engineer", fetched_at=now.isoformat()),
                 record("greenhouse", board, "kept", employer, fetched_at=now.isoformat()), checked=[f"greenhouse:{board}"])
    assert (stats.reopened, stats.closed_unseen) == (1, 0)
    assert rows(engine, employer)["gone"].status == "open" and rows(engine, employer)["gone"].updated_at == before
    assert len(discover(employer)) == 2


def test_an_open_copy_takes_over_when_the_canonical_row_closes(world):
    engine, employer = world
    board = f"board-{employer}"
    old = (datetime.now(timezone.utc) - STALE_AFTER - timedelta(days=1)).isoformat()
    pull(engine, record("greenhouse", board, "1", employer, fetched_at=old), record("adzuna", "sg", "2", employer))
    assert [item["job"]["source"] for item in discover(employer)] == ["greenhouse"]
    pull(engine, checked=[f"greenhouse:{board}"])
    assert [item["job"]["source"] for item in discover(employer)] == ["adzuna"]


def test_the_posted_filter_keeps_recent_and_undated_jobs(world):
    engine, employer = world
    board = f"board-{employer}"
    now = datetime.now(timezone.utc)
    pull(engine, record("greenhouse", board, "new", employer, title="Platform Engineer", posted_at=(now - timedelta(days=2)).isoformat()),
         record("greenhouse", board, "old", employer, posted_at=(now - timedelta(days=20)).isoformat()),
         record("greenhouse", board, "undated", employer, title="Site Reliability Engineer", posted_at=None))

    def titles(**params):
        response = client.get("/v1/recommendations", params={"q": employer, "limit": 100, **params}, headers=HEADERS)
        assert response.status_code == 200, response.text
        return sorted(item["job"]["title"] for item in response.json()["items"])

    assert titles() == ["Data Engineer", "Platform Engineer", "Site Reliability Engineer"]        # default: the past year
    assert titles(posted_within=14) == ["Platform Engineer", "Site Reliability Engineer"]
    with Session(engine) as db, db.begin():
        db.execute(text("UPDATE jobs SET posted_at = now() - interval '400 days' WHERE company LIKE :name AND external_id = 'old'"),
                   {"name": f"{employer}%"})
    assert titles() == ["Platform Engineer", "Site Reliability Engineer"]                          # older than a year: never listed


def test_expired_and_closed_jobs_are_hidden_unless_asked_for(world):
    engine, employer = world
    board = f"board-{employer}"
    now = datetime.now(timezone.utc)
    pull(engine, record("greenhouse", board, "live", employer, title="Platform Engineer", posted_at=now.isoformat()),
         record("greenhouse", board, "expired", employer, posted_at=now.isoformat(),
                expires_at=(now + timedelta(days=1)).isoformat()),
         record("greenhouse", board, "closed", employer, title="Site Reliability Engineer", posted_at=now.isoformat()))
    with Session(engine) as db, db.begin():
        db.execute(text("UPDATE jobs SET expires_at = now() - interval '1 hour' WHERE company LIKE :name AND external_id = 'expired'"),
                   {"name": f"{employer}%"})
        db.execute(text("UPDATE jobs SET status = 'closed' WHERE company LIKE :name AND external_id = 'closed'"), {"name": f"{employer}%"})

    def listed(**params):
        response = client.get("/v1/recommendations", params={"q": employer, "limit": 100, **params}, headers=HEADERS)
        assert response.status_code == 200, response.text
        return {item["job"]["title"]: item["job"] for item in response.json()["items"]}

    assert set(listed()) == {"Platform Engineer"}
    shown = listed(include_expired="true")
    assert set(shown) == {"Platform Engineer", "Data Engineer", "Site Reliability Engineer"}
    assert shown["Site Reliability Engineer"]["status"] == "closed" and shown["Data Engineer"]["expires_at"]
