"""Cover letters against real PostgreSQL: create (blank, written, improved), edit, review, export and attach to an application."""
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from job_hunter.api import cover_letters
from job_hunter.api.main import app
from job_hunter.config import settings
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import Job, Profile, ProfileVersion, User

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                                reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")
client = TestClient(app)
ALICE = {"X-Dev-User": "alice"}
CASEY = {"X-Dev-User": "casey"}

SNAPSHOT = {"summary": "Backend engineer.", "skills": ["Python", "SQL"],
            "bullets": [{"id": "b1", "text": "Designed incremental SQL pipelines with duplicate detection."}]}
ANSWER = {"paragraphs": ["I am applying for the Fit Job 0 role at Acme.", "I designed incremental SQL pipelines in Python.",
                         "Thank you for your time."],
          "claims": [{"text": "Designed SQL pipelines", "evidence": ["b1"]}, {"text": "Led a team", "evidence": []}]}
DESCRIPTION = "About the role. You need pipeline experience and Python. We also value clear writing and steady ownership of your work."


@pytest.fixture
def world(monkeypatch):
    engine = create_engine(settings.migration_database_url)
    ids = {key: uuid4() for key in ("alice", "casey")}
    with Session(engine) as db, db.begin():
        db.add(User(id=ids["alice"], auth_subject=f"cl-{ids['alice']}", display_name="alice", plan="free"))
        db.add(User(id=ids["casey"], auth_subject=f"cl-{ids['casey']}", display_name="casey", plan="free"))
        db.flush()
        for key, user_id in ids.items():
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            confirmed = 1 if key == "alice" else None            # casey has not confirmed a profile
            db.add(Profile(user_id=user_id, draft={"name": f"{key.title()} Tan", "email": f"{key}@example.com", "location": "Singapore"},
                           revision=1, bank_revision=1, confirmed_revision=confirmed))
            if confirmed:
                db.add(ProfileVersion(user_id=user_id, revision=1, data=SNAPSHOT, content_hash=uuid4().hex))
            db.flush()
        jobs = [Job(title=f"Fit Job {i}", company="Acme", description=DESCRIPTION, skills=[]) for i in range(7)]
        jobs.append(Job(title="Short Job", company="Acme", description="Too short.", skills=[]))
        db.add_all(jobs)
        db.flush()
        job_ids = [str(job.id) for job in jobs]
    for key, user_id in ids.items():
        monkeypatch.setitem(DEV_USERS, key, (user_id, key))
    calls = []

    def fake_ask(payload):
        calls.append(payload)
        return ANSWER

    monkeypatch.setattr(settings, "model_backend", "fake")           # makes the AI "available"; ask_model is replaced below
    monkeypatch.setattr(cover_letters, "ask_model", fake_ask)
    yield calls, job_ids, ids
    with Session(engine) as db, db.begin():
        for user_id in ids.values():
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            for table in ("ai_tailor_uses", "job_reviews", "applications", "document_exports", "documents", "profile_versions", "profiles"):
                db.execute(text(f"DELETE FROM {table} WHERE user_id=:uid"), {"uid": user_id})
            db.execute(text("DELETE FROM users WHERE id=:uid"), {"uid": user_id})
        db.execute(text("DELETE FROM jobs WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": job_ids})
    engine.dispose()


def create(job_id, headers=ALICE, **body):
    return client.post(f"/v1/jobs/{job_id}/cover-letter", json=body, headers=headers)


def used(headers=ALICE):
    return client.get("/v1/me", headers=headers).json()["allowance"]["used"]


def test_a_blank_letter_is_free_and_starts_from_the_profile_and_the_job(world):
    _, jobs, _ = world
    reply = create(jobs[0], mode="blank")
    assert reply.status_code == 201
    document = reply.json()["document"]
    assert document["kind"] == "cover_letter" and document["job_id"] == jobs[0] and document["revision"] == 1
    assert document["title"] == "Cover letter — Fit Job 0"
    content = document["content"]
    assert content["name"] == "Alice Tan" and content["email"] == "alice@example.com" and content["recipient"] == "Hiring Team\nAcme"
    assert content["greeting"] == "Dear Hiring Team," and content["paragraphs"] == [""] and content["signature"] == "Alice Tan"
    assert reply.json()["notes"] == [] and reply.json()["ai"]["status"] == "off"
    assert used() == 0


def test_a_letter_the_person_already_has_is_put_in_the_editor_as_it_is_for_free(world):
    calls, jobs, _ = world
    reply = create(jobs[0], mode="blank", source_text="Dear Ms Lim,\n\nMy own first paragraph.\n\nMy own second paragraph.\n\nYours sincerely,\nAlice Tan")
    assert reply.status_code == 201
    content = reply.json()["document"]["content"]
    assert content["greeting"] == "Dear Ms Lim," and content["paragraphs"] == ["My own first paragraph.", "My own second paragraph."]
    assert content["closing"] == "Yours sincerely," and content["signature"] == "Alice Tan"
    assert content["name"] == "Alice Tan" and content["recipient"] == "Hiring Team\nAcme"            # contact and recipient still come from the profile and the job
    assert calls == [] and used() == 0 and reply.json()["ai"]["status"] == "off"
    assert create(jobs[1], mode="blank", source_text="   ").json()["document"]["content"]["paragraphs"] == [""]


def test_a_written_letter_comes_from_the_profile_with_notes_and_costs_one_use(world):
    calls, jobs, _ = world
    reply = create(jobs[0], mode="write", tone="friendly", points="Mention teamwork.")
    assert reply.status_code == 201
    body = reply.json()
    assert body["document"]["content"]["paragraphs"] == ANSWER["paragraphs"] and body["ai"]["status"] == "applied"
    kinds = [note["kind"] for note in body["notes"]]
    assert kinds[0] == "ok" and "warn" in kinds and kinds[-1] == "info"
    assert calls[0]["mode"] == "write" and calls[0]["tone"] == "friendly" and calls[0]["points"] == "Mention teamwork."
    assert calls[0]["evidence"]["b1"].startswith("Designed incremental") and "email" not in str(calls[0]["job"])
    assert used() == 1
    assert create(jobs[0], mode="write").status_code == 201 and used() == 1      # the same job in the same month is free again


def test_a_letter_can_be_improved_from_pasted_text_or_from_a_saved_letter(world):
    calls, jobs, _ = world
    pasted = create(jobs[0], mode="improve", source_text="Dear sir, I would like a job in data engineering please consider me.")
    assert pasted.status_code == 201 and calls[0]["mode"] == "improve" and "consider me" in calls[0]["letter"]
    saved = pasted.json()["document"]
    again = create(jobs[1], mode="improve", source_document_id=saved["id"])
    assert again.status_code == 201 and calls[1]["letter"].startswith("I am applying")
    assert create(jobs[1], mode="improve").status_code == 422                                      # nothing to improve
    assert create(jobs[1], mode="improve", source_text="short").json()["error"]["code"] == "LETTER_TOO_SHORT"
    assert create(jobs[1], mode="improve", source_document_id=saved["id"], headers=CASEY).status_code == 404


def test_writing_needs_a_confirmed_profile_and_a_job_with_some_detail(world):
    _, jobs, _ = world
    assert create(jobs[0], headers=CASEY, mode="write").json()["error"]["code"] == "PROFILE_NOT_CONFIRMED"
    assert create(jobs[7], mode="write").json()["error"]["code"] == "JOB_TOO_SHORT"
    assert create(str(uuid4()), mode="blank").status_code == 404
    assert create(jobs[0], headers=CASEY, mode="blank").status_code == 201                       # a blank letter never needs the profile


def test_the_sixth_job_of_the_month_is_refused_for_a_free_user_but_a_blank_letter_still_works(world):
    _, jobs, _ = world
    for job_id in jobs[:5]:
        assert create(job_id, mode="write").status_code == 201
    assert used() == 5
    refused = create(jobs[5], mode="write")
    assert refused.status_code == 402 and refused.json()["error"]["code"] == "AI_LIMIT_REACHED"
    assert create(jobs[5], mode="blank").status_code == 201


@pytest.mark.parametrize("failure", ["raise", "no_paragraphs", "error"])
def test_a_model_that_fails_creates_nothing_and_costs_nothing(world, monkeypatch, failure):
    _, jobs, _ = world

    def broken(payload):
        if failure == "raise":
            raise cover_letters.AiLetterFailed("AI_TIMEOUT")
        return {"paragraphs": []} if failure == "no_paragraphs" else {"error": "MODEL_UNAVAILABLE"}

    monkeypatch.setattr(cover_letters, "ask_model", broken)
    reply = create(jobs[0], mode="write")
    assert reply.status_code == 503 and "Nothing was used" in reply.json()["error"]["message"]
    assert used() == 0 and client.get("/v1/documents?kind=cover_letter", headers=ALICE).json()["items"] == []


def test_a_letter_is_edited_reviewed_exported_and_attached_to_the_application(world):
    _, jobs, _ = world
    document = create(jobs[0], mode="write").json()["document"]
    paragraphs = ["My own first paragraph.", "My own second paragraph."]
    edited = client.patch(f"/v1/documents/{document['id']}", headers=ALICE,
                          json={"expected_revision": 1, "content": {**document["content"], "paragraphs": paragraphs}})
    assert edited.status_code == 200 and edited.json()["revision"] == 2 and edited.json()["content"]["paragraphs"] == paragraphs
    assert client.patch(f"/v1/documents/{document['id']}", headers=ALICE,
                        json={"expected_revision": 1, "title": "stale"}).status_code == 409
    attach = {"cover_letter_document_id": document["id"], "expected_cover_letter_revision": 2, "expected_revision": 0}
    assert client.put(f"/v1/applications/{jobs[0]}", headers=ALICE, json=attach).json()["error"]["code"] == "REVIEW_REQUIRED"
    assert client.post(f"/v1/documents/{document['id']}/exports", headers=ALICE).status_code == 409
    assert client.post(f"/v1/documents/{document['id']}/review", headers=ALICE, json={"expected_revision": 2}).status_code == 200
    assert client.put(f"/v1/applications/{jobs[0]}", headers=ALICE,
                      json={**attach, "expected_cover_letter_revision": 1}).json()["error"]["code"] == "LETTER_REVISION_CONFLICT"
    attached = client.put(f"/v1/applications/{jobs[0]}", headers=ALICE, json=attach)
    assert attached.status_code == 200
    packet = attached.json()["cover_letter_packet"]
    assert packet["document_id"] == document["id"] and packet["revision"] == 2 and packet["title"] == document["title"]
    assert attached.json()["resume_packet"] is None
    download = client.get(packet["download_url"], headers=ALICE)
    assert download.status_code == 200 and download.content.startswith(b"%PDF") and "cover-letter-r2.pdf" in download.headers["content-disposition"]
    listed = client.get("/v1/applications", headers=ALICE).json()["items"][0]
    assert listed["cover_letter_packet"]["export_id"] == packet["export_id"]
    # editing the letter afterwards does not change the attached snapshot
    client.patch(f"/v1/documents/{document['id']}", headers=ALICE, json={"expected_revision": 2, "title": "Renamed"})
    assert client.get("/v1/applications", headers=ALICE).json()["items"][0]["cover_letter_packet"]["revision"] == 2
    cleared = client.put(f"/v1/applications/{jobs[0]}", headers=ALICE,
                         json={"cover_letter_document_id": None, "expected_revision": attached.json()["revision"]})
    assert cleared.json()["cover_letter_packet"] is None


def test_a_resume_cannot_be_attached_as_a_letter_and_a_letter_cannot_be_the_resume(world):
    _, jobs, _ = world
    letter = create(jobs[0], mode="blank").json()["document"]
    resume = client.post("/v1/documents", headers=ALICE, json={"title": "Resume", "content": {"name": "Alice"}}).json()
    client.post(f"/v1/documents/{resume['id']}/review", headers=ALICE, json={"expected_revision": 1})
    wrong = client.put(f"/v1/applications/{jobs[0]}", headers=ALICE,
                       json={"cover_letter_document_id": resume["id"], "expected_cover_letter_revision": 1, "expected_revision": 0})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "NOT_A_COVER_LETTER"
    wrong = client.put(f"/v1/applications/{jobs[0]}", headers=ALICE,
                       json={"resume_document_id": letter["id"], "expected_resume_revision": 1, "expected_revision": 0})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "NOT_A_RESUME"
    assert client.put(f"/v1/applications/{jobs[0]}", headers=ALICE,
                      json={"cover_letter_document_id": letter["id"], "expected_revision": 0}).status_code == 422   # revision is required


def test_letter_content_is_checked_and_belongs_to_its_owner(world):
    _, jobs, _ = world
    document = create(jobs[0], mode="blank").json()["document"]
    url = f"/v1/documents/{document['id']}"
    for bad in ({"paragraphs": "one string"}, {"paragraphs": ["x" * 4001]}, {"paragraphs": ["a"] * 13}, {"greeting": 5}, {"recipient": "r" * 1001}):
        reply = client.patch(url, headers=ALICE, json={"expected_revision": 1, "content": {**document["content"], **bad}})
        assert reply.status_code == 422, bad
    assert client.patch(url, headers=CASEY, json={"expected_revision": 1, "title": "mine now"}).status_code == 404
    assert client.get(url, headers=CASEY).status_code == 404
    assert client.post(f"{url}/review", headers=CASEY, json={"expected_revision": 1}).status_code == 404
    assert client.get("/v1/documents?kind=cover_letter", headers=CASEY).json()["items"] == []


def test_letters_are_listed_separately_archived_restored_and_duplicated_as_letters(world):
    _, jobs, _ = world
    document = create(jobs[0], mode="blank").json()["document"]
    resume = client.post("/v1/documents", headers=ALICE, json={"title": "Resume", "content": {"name": "Alice"}}).json()
    letters = client.get("/v1/documents?kind=cover_letter", headers=ALICE).json()["items"]
    assert [item["id"] for item in letters] == [document["id"]]
    assert resume["id"] not in [item["id"] for item in letters]
    copy = client.post(f"/v1/documents/{document['id']}/duplicate", headers=ALICE, json={"job_id": jobs[1]})
    assert copy.status_code == 201 and copy.json()["kind"] == "cover_letter" and copy.json()["job_id"] == jobs[1]
    assert client.delete(f"/v1/documents/{document['id']}", headers=ALICE).status_code == 204
    assert [item["id"] for item in client.get("/v1/documents?kind=cover_letter", headers=ALICE).json()["items"]] == [copy.json()["id"]]
    assert document["id"] not in [item["id"] for item in client.get("/v1/documents", headers=ALICE).json()["items"]]
    restored = client.post(f"/v1/documents/{document['id']}/restore", headers=ALICE)
    assert restored.status_code == 200 and restored.json()["kind"] == "cover_letter"
    assert len(client.get("/v1/documents?kind=cover_letter", headers=ALICE).json()["items"]) == 2


def test_a_saved_job_with_an_attached_letter_keeps_its_tracker_row_when_unsaved(world):
    _, jobs, _ = world
    client.put(f"/v1/jobs/{jobs[0]}/review", json={"decision": "saved"}, headers=ALICE)
    document = create(jobs[0], mode="blank").json()["document"]
    client.post(f"/v1/documents/{document['id']}/review", headers=ALICE, json={"expected_revision": 1})
    revision = client.get("/v1/applications", headers=ALICE).json()["items"][0]["revision"]
    attached = client.put(f"/v1/applications/{jobs[0]}", headers=ALICE, json={
        "cover_letter_document_id": document["id"], "expected_cover_letter_revision": 1, "expected_revision": revision})
    assert attached.status_code == 200
    client.put(f"/v1/jobs/{jobs[0]}/review", json={"decision": "none"}, headers=ALICE)
    assert [row["job_id"] for row in client.get("/v1/applications", headers=ALICE).json()["items"]] == [jobs[0]]


def test_renaming_keeps_a_reviewed_document_reviewed_but_a_content_change_does_not(world):
    _, jobs, _ = world
    document = create(jobs[0], mode="write").json()["document"]
    url = f"/v1/documents/{document['id']}"
    assert client.post(f"{url}/review", headers=ALICE, json={"expected_revision": 1}).status_code == 200
    # Title only (the title is not printed): still reviewed, so it can be downloaded and attached without a new review.
    renamed = client.patch(url, headers=ALICE, json={"expected_revision": 1, "title": "Stripe letter"}).json()
    assert renamed["title"] == "Stripe letter" and renamed["revision"] == 2 and renamed["reviewed_revision"] == 2
    # The editor's autosave sends everything; unchanged content with a new title still counts as a rename.
    same = client.patch(url, headers=ALICE, json={"expected_revision": 2, "title": "Stripe letter v2", "content": renamed["content"],
                                                  "layout": renamed["layout"], "template": renamed["template"]}).json()
    assert same["reviewed_revision"] == 3
    edited = client.patch(url, headers=ALICE, json={"expected_revision": 3, "content": {**same["content"], "paragraphs": ["New."]}}).json()
    assert edited["revision"] == 4 and edited["reviewed_revision"] is None
