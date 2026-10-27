"""The fit analysis endpoints against real PostgreSQL, with a scripted model instead of a network call."""
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from job_hunter.api import fit_analysis
from job_hunter.api.main import app
from job_hunter.config import settings
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import Job, Profile, ProfileVersion, User
from job_hunter.llm import FakeLlm
from job_hunter.preparation import allowance

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                                reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")
client = TestClient(app)
ALICE = {"X-Dev-User": "alice"}
CASEY = {"X-Dev-User": "casey"}

SNAPSHOT = {"summary": "Backend engineer.", "skills": ["Python", "SQL"],
            "bullets": [{"id": "b1", "text": "Designed incremental SQL pipelines with duplicate detection."}]}


def respond(system, user):
    if "list the real requirements" in system:
        return {"requirements": [{"text": "Pipeline experience", "importance": "must"}, {"text": "Kubernetes", "importance": "must"}]}
    if "compare job requirements" in system:
        return {"verdicts": [{"id": 0, "verdict": "met", "evidence": ["b1"], "note": "Built pipelines."},
                             {"id": 1, "verdict": "not_evidenced", "evidence": [], "note": ""}]}
    return {"suggestions": [{"kind": "add", "requirement": 1, "bullet_id": None, "text": "Mention Kubernetes if you have used it."}]}


@pytest.fixture
def world(monkeypatch):
    engine = create_engine(settings.migration_database_url)
    ids = {key: uuid4() for key in ("alice", "casey")}
    with Session(engine) as db, db.begin():
        db.add(User(id=ids["alice"], auth_subject=f"fit-{ids['alice']}", display_name="alice", plan="free"))
        db.add(User(id=ids["casey"], auth_subject=f"fit-{ids['casey']}", display_name="casey", plan="premium"))
        db.flush()
        for key, user_id in ids.items():
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            db.add(Profile(user_id=user_id, draft={}, revision=1, bank_revision=1, confirmed_revision=1))
            db.add(ProfileVersion(user_id=user_id, revision=1, data=SNAPSHOT, content_hash=uuid4().hex))
            db.flush()
        jobs = [Job(title=f"Fit Job {i}", description="About the role. You need pipeline experience and Kubernetes. We also value clear writing, steady ownership of your work and curiosity about data.", skills=[]) for i in range(7)]
        db.add_all(jobs)
        db.flush()
        job_ids = [str(job.id) for job in jobs]
    for key, user_id in ids.items():
        monkeypatch.setitem(DEV_USERS, key, (user_id, key))
    fake = FakeLlm(respond)
    monkeypatch.setattr(fit_analysis, "build_client", lambda _settings: fake)
    monkeypatch.setattr(settings, "llm_worker", "inline")
    yield fake, job_ids, ids
    with Session(engine) as db, db.begin():
        for user_id in ids.values():
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            for table in ("fit_analyses", "ai_tailor_uses", "job_reviews", "applications", "profile_versions", "profiles"):
                db.execute(text(f"DELETE FROM {table} WHERE user_id=:uid"), {"uid": user_id})
            db.execute(text("DELETE FROM users WHERE id=:uid"), {"uid": user_id})
        db.execute(text("DELETE FROM jobs WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": job_ids})
    engine.dispose()


def analyse(job_id, headers=ALICE):
    return client.post(f"/v1/jobs/{job_id}/fit-analysis", headers=headers)


def test_an_analysis_is_started_then_read_back_checked_and_scored(world):
    fake, jobs, _ = world
    started = analyse(jobs[0])
    assert started.status_code == 202, started.text
    # The TestClient runs the background task before returning, so the result is ready on the next read.
    body = client.get(f"/v1/fit-analyses/{started.json()['id']}", headers=ALICE).json()
    assert body["status"] == "ready" and body["stale"] is False
    assert body["result"]["coverage"]["percent"] == 50 and body["result"]["verdicts"][0]["evidence"] == ["b1"]
    assert client.get(f"/v1/jobs/{jobs[0]}/fit-analysis", headers=ALICE).json()["id"] == body["id"]
    assert client.get("/v1/me", headers=ALICE).json()["allowance"]["used"] == 1


def test_requirements_are_extracted_once_per_job_and_reused_by_everyone(world):
    fake, jobs, _ = world
    analyse(jobs[0])
    extractions = sum("list the real requirements" in system for system, _ in fake.calls)
    analyse(jobs[0], CASEY)
    assert extractions == 1
    assert sum("list the real requirements" in system for system, _ in fake.calls) == 1


def test_another_users_analysis_is_not_visible(world):
    _, jobs, _ = world
    started = analyse(jobs[0]).json()
    assert client.get(f"/v1/fit-analyses/{started['id']}", headers=CASEY).status_code == 404
    assert client.get(f"/v1/jobs/{jobs[0]}/fit-analysis", headers=CASEY).status_code == 404


def test_free_users_stop_at_five_jobs_and_premium_users_do_not(world):
    _, jobs, _ = world
    for job_id in jobs[:5]:
        assert analyse(job_id).status_code == 202
    over = analyse(jobs[5])
    assert over.status_code == 402 and over.json()["error"]["code"] == "AI_LIMIT_REACHED"
    assert analyse(jobs[0]).status_code == 202            # a job that already has its slot costs nothing more
    for job_id in jobs[:6]:
        assert analyse(job_id, CASEY).status_code == 202   # premium: 50 a month


def test_an_unconfirmed_profile_or_unknown_job_is_refused(world):
    _, jobs, ids = world
    assert analyse(str(uuid4())).status_code == 404
    engine = create_engine(settings.migration_database_url)
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(ids["alice"])})
        db.execute(text("UPDATE profiles SET confirmed_revision = NULL WHERE user_id=:uid"), {"uid": ids["alice"]})
    engine.dispose()
    response = analyse(jobs[0])
    assert response.status_code == 409 and response.json()["error"]["code"] == "PROFILE_NOT_CONFIRMED"


def test_a_listing_with_no_real_description_is_refused_without_using_the_model(world):
    fake, jobs, _ = world
    engine = create_engine(settings.migration_database_url)
    with Session(engine) as db, db.begin():
        db.execute(text("UPDATE jobs SET description = 'Turn data into experiments.' WHERE id = CAST(:id AS uuid)"), {"id": jobs[0]})
    engine.dispose()
    response = analyse(jobs[0])
    assert response.status_code == 422 and response.json()["error"]["code"] == "JOB_TOO_SHORT"
    assert fake.calls == [] and client.get("/v1/me", headers=ALICE).json()["allowance"]["used"] == 0


def test_without_a_model_the_answer_is_503(world, monkeypatch):
    _, jobs, _ = world
    monkeypatch.setattr(fit_analysis, "build_client", lambda _settings: None)
    assert analyse(jobs[0]).status_code == 503
    assert client.get("/v1/me", headers=ALICE).json()["fit_available"] is False


def test_a_model_failure_is_reported_and_costs_no_slot(world):
    from job_hunter.llm import LlmError

    def down(system, user):
        raise LlmError("model unavailable")
    fake, jobs, _ = world
    fake._answers = down
    started = analyse(jobs[0]).json()
    body = client.get(f"/v1/fit-analyses/{started['id']}", headers=ALICE).json()
    assert body["status"] == "failed" and body["error_code"] == "MODEL_UNAVAILABLE"
    assert client.get("/v1/me", headers=ALICE).json()["allowance"]["used"] == 0
    fake._answers = respond
    assert analyse(jobs[0]).status_code == 202            # trying again replaces the failed row
    assert client.get(f"/v1/jobs/{jobs[0]}/fit-analysis", headers=ALICE).json()["status"] == "ready"


def test_the_s3_path_writes_a_request_and_reads_the_workers_answer(world, monkeypatch):
    import io
    from job_hunter import llm_transport, llm_worker

    class NoSuchKey(Exception):
        pass

    class FakeS3:
        objects: dict = {}
        exceptions = type("Exceptions", (), {"NoSuchKey": NoSuchKey})

        def __init__(self):
            self.objects = {}

        def put_object(self, Bucket, Key, Body, **_):
            self.objects[(Bucket, Key)] = Body

        def get_object(self, Bucket, Key):
            if (Bucket, Key) not in self.objects:
                raise NoSuchKey(Key)
            return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    fake, jobs, _ = world
    s3 = FakeS3()
    monkeypatch.setattr(settings, "llm_worker", "s3")
    monkeypatch.setattr(settings, "document_bucket", "docs")
    monkeypatch.setattr(fit_analysis.storage, "s3", lambda: s3)
    started = analyse(jobs[0])
    assert started.status_code == 202 and started.json()["status"] == "pending"
    analysis_id = started.json()["id"]
    assert client.get(f"/v1/fit-analyses/{analysis_id}", headers=ALICE).json()["status"] == "pending"   # worker has not answered yet
    assert client.get("/v1/fit-analyses", headers=ALICE).json() == {"items": [], "running": [jobs[0]]}   # the list shows it as running
    assert client.get("/v1/fit-analyses", headers=CASEY).json()["running"] == []
    assert llm_worker.process(s3, "docs", llm_transport.request_key(analysis_id), client=fake) == "ok"
    listed = client.get("/v1/fit-analyses", headers=ALICE).json()           # the list alone picks up the worker's answer
    assert listed["running"] == [] and [item["job_id"] for item in listed["items"]] == [jobs[0]]
    body = client.get(f"/v1/fit-analyses/{analysis_id}", headers=ALICE).json()
    assert body["status"] == "ready" and body["result"]["coverage"]["percent"] == 50
    assert analyse(jobs[0]).status_code == 202            # the same job again is allowed and costs nothing more
    assert allowance.month_label() == client.get("/v1/me", headers=ALICE).json()["allowance"]["period"]


def test_finished_analyses_are_listed_so_job_lists_can_mark_them(world):
    _, jobs, _ = world
    assert client.get("/v1/fit-analyses", headers=ALICE).json() == {"items": [], "running": []}
    analyse(jobs[0])
    assert client.get("/v1/fit-analyses", headers=ALICE).json()["items"] == [{"job_id": jobs[0], "percent": 50, "stale": False}]
    assert client.get("/v1/fit-analyses", headers=CASEY).json()["items"] == []     # one user's analyses never show for another


def test_saved_and_passed_jobs_are_listed_for_the_user_who_chose_them(world):
    _, jobs, _ = world
    assert client.put(f"/v1/jobs/{jobs[0]}/review", json={"decision": "saved"}, headers=ALICE).status_code == 200
    assert client.put(f"/v1/jobs/{jobs[1]}/review", json={"decision": "dismissed"}, headers=ALICE).status_code == 200
    saved = client.get("/v1/jobs/reviewed?decision=saved", headers=ALICE).json()
    assert [row["job"]["id"] for row in saved["items"]] == [jobs[0]] and saved["items"][0]["review"] == "saved" and saved["total"] == 1
    passed = client.get("/v1/jobs/reviewed?decision=dismissed", headers=ALICE).json()
    assert [row["job"]["id"] for row in passed["items"]] == [jobs[1]]
    assert client.get("/v1/jobs/reviewed?decision=dismissed&q=nothing-matches-this", headers=ALICE).json()["items"] == []
    assert client.get("/v1/jobs/reviewed?decision=saved", headers=CASEY).json()["items"] == []
    assert client.get("/v1/jobs/reviewed?decision=bogus", headers=ALICE).status_code == 422
    client.put(f"/v1/jobs/{jobs[1]}/review", json={"decision": "none"}, headers=ALICE)   # restoring a passed job removes it from the list
    assert client.get("/v1/jobs/reviewed?decision=dismissed", headers=ALICE).json()["items"] == []


def review(job_id, decision, headers=ALICE):
    assert client.put(f"/v1/jobs/{job_id}/review", json={"decision": decision}, headers=headers).status_code == 200


def tracker(headers=ALICE):
    return [row["job_id"] for row in client.get("/v1/applications", headers=headers).json()["items"]]


def statements_during(call):
    """The SQL statements the database ran while ``call`` ran."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    seen = []

    def hook(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", hook)
    try:
        call()
    finally:
        event.remove(Engine, "before_cursor_execute", hook)
    return seen


def test_unsaving_or_passing_a_job_removes_the_tracker_row_the_save_created(world):
    _, jobs, _ = world
    review(jobs[0], "saved")
    review(jobs[1], "saved")
    assert sorted(tracker()) == sorted(jobs[:2])
    review(jobs[0], "none")
    review(jobs[1], "dismissed")
    assert tracker() == []
    review(jobs[0], "saved")    # saving again brings it back
    assert tracker() == [jobs[0]]


@pytest.mark.parametrize("change", [{"notes": "Spoke to a recruiter"}, {"status": "preparing"}, {"status": "applied"},
                                    {"cover_letter_text": "Dear hiring team"}])
def test_a_tracker_row_the_user_worked_on_survives_unsave_and_pass(world, change):
    _, jobs, _ = world
    review(jobs[0], "saved")
    revision = client.get("/v1/applications", headers=ALICE).json()["items"][0]["revision"]
    assert client.put(f"/v1/applications/{jobs[0]}", json={"expected_revision": revision, **change}, headers=ALICE).status_code == 200
    review(jobs[0], "none")
    assert tracker() == [jobs[0]]
    review(jobs[0], "dismissed")
    assert tracker() == [jobs[0]]


def test_unsaving_never_touches_another_users_tracker(world):
    _, jobs, _ = world
    review(jobs[0], "saved")
    review(jobs[0], "saved", CASEY)
    review(jobs[0], "none")
    assert tracker() == [] and tracker(CASEY) == [jobs[0]]


def test_listing_applications_does_not_query_once_per_application(world):
    _, jobs, _ = world
    review(jobs[0], "saved")
    one = len(statements_during(lambda: client.get("/v1/applications", headers=ALICE)))
    for job_id in jobs[1:6]:
        review(job_id, "saved")
    assert len(tracker()) == 6
    assert len(statements_during(lambda: client.get("/v1/applications", headers=ALICE))) == one


def test_reading_a_document_does_not_lock_its_row(world):
    statements = statements_during(lambda: client.get(f"/v1/documents/{uuid4()}", headers=ALICE))
    assert statements and not any("FOR UPDATE" in statement.upper() for statement in statements)
