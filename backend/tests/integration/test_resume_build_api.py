"""Building resumes from the profile bank, against real PostgreSQL and isolated local identities."""
import os
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from job_hunter.api.main import app
from job_hunter.config import settings
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import Job, Profile, User
from job_hunter.profile_bank.build import LAYOUT_CHOICES

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                                reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")
client = TestClient(app)
ALICE = {"X-Dev-User": "alice"}
CASEY = {"X-Dev-User": "casey"}


@pytest.fixture
def isolated_users(monkeypatch):
    engine = create_engine(settings.migration_database_url)
    user_ids = {key: uuid4() for key in ("alice", "casey")}
    with Session(engine) as db, db.begin():
        for key, user_id in user_ids.items():
            db.add(User(id=user_id, auth_subject=f"build-test-{user_id}", display_name=key))
        db.flush()
        for user_id in user_ids.values():
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            db.add(Profile(user_id=user_id, draft={}, revision=1, bank_revision=1))
            db.flush()
    for key, user_id in user_ids.items():
        monkeypatch.setitem(DEV_USERS, key, (user_id, key))
    yield engine, user_ids
    with Session(engine) as db, db.begin():
        for user_id in user_ids.values():
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            paths = db.execute(text("SELECT file_path FROM document_exports WHERE user_id=:uid UNION ALL SELECT file_path FROM uploads WHERE user_id=:uid"), {"uid": user_id}).scalars().all()
            for table in ("applications", "job_reviews", "profile_imports", "profile_items", "profile_versions", "document_exports", "documents", "uploads", "user_settings", "preferences", "profiles"):
                db.execute(text(f"DELETE FROM {table} WHERE user_id=:uid"), {"uid": user_id})
            db.execute(text("DELETE FROM users WHERE id=:uid"), {"uid": user_id})
            for path in paths:
                Path(path).unlink(missing_ok=True)
    engine.dispose()


def make_item(kind, data, headers=ALICE):
    response = client.post("/v1/profile/items", headers=headers, json={"kind": kind, "data": data})
    assert response.status_code == 201, response.text
    return response.json()


def experience(headers=ALICE):
    return make_item("experience", {
        "title": "Backend Engineer", "organisation": "Example Employer", "location": "Singapore",
        "start": "2023-07", "current": True, "skills": ["Python", "PostgreSQL"],
        "bullets": [
            {"id": "b_api", "text": "Built Python APIs on PostgreSQL.", "tags": ["backend"], "skills": ["PostgreSQL"],
             "alternatives": [{"id": "v_plain", "text": "Made reporting faster with a tested API."}]},
            {"id": "b_docs", "text": "Wrote the team runbooks."}]}, headers)


def skill(name, category="language", headers=ALICE):
    return make_item("skill", {"name": name, "category": category}, headers)


def seeded_job_id(engine, user_id):
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
        job = db.query(Job).filter(Job.title == "Backend Engineer").first()
        assert job is not None, "run python -m job_hunter.seed first"
        return str(job.id)


def set_basics(headers=ALICE):
    revision = client.get("/v1/profile", headers=headers).json()["revision"]
    response = client.put("/v1/profile", headers=headers, json={"expected_revision": revision, "draft": {
        "name": "Fictional Candidate", "email": "candidate@example.invalid", "phone": "+65 5550 0100",
        "location": "Singapore", "summary": "Backend engineer who likes data."}})
    assert response.status_code == 200, response.text


def set_defaults(defaults, headers=ALICE):
    current = client.get("/v1/settings", headers=headers).json()["revision"]
    response = client.put("/v1/settings", headers=headers, json={"expected_revision": current, "resume_defaults": defaults})
    assert response.status_code == 200, response.text


def documents(headers=ALICE):
    return client.get("/v1/documents", headers=headers).json()["items"]


def plan_for(item, skills=()):
    sections = [{"kind": "experience", "items": [{"item_id": item["id"], "picks": [
        {"bullet_id": "b_api", "alternative_id": "v_plain"}, {"bullet_id": "b_docs"}]}]}]
    if skills:
        sections.append({"kind": "skills", "skill_ids": [row["id"] for row in skills]})
    return {"title": "Backend Engineer – Example", "template": "classic", "job_id": None,
            "summary": {"mode": "profile"}, "sections": sections}


def build(plan, headers=ALICE):
    return client.post("/v1/documents/from-bank", headers=headers, json=plan)


# --- from-bank --------------------------------------------------------------

def test_from_bank_creates_a_resume_that_remembers_where_it_came_from(isolated_users):
    set_basics()
    item = experience()
    python, sql = skill("Python"), skill("SQL")
    response = build(plan_for(item, [python, sql]))
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["title"] == "Backend Engineer – Example" and document["revision"] == 1
    assert document["kind"] == "resume" and document["template"] == "classic" and document["job_id"] is None
    content = document["content"]
    assert (content["name"], content["email"]) == ("Fictional Candidate", "candidate@example.invalid")
    assert content["summary"] == "Backend engineer who likes data."
    experience_section, skills_section = content["sections"]
    assert experience_section["kind"] == "experience"
    entry = experience_section["entries"][0]
    assert entry["source"] == {"item_id": item["id"], "item_revision": item["revision"]}
    assert entry["date_range"] == {"start": "2023-07", "end": None, "current": True}
    assert entry["dates"] == "Jul 2023 – Present"
    assert entry["bullets"] == ["Made reporting faster with a tested API.", "Wrote the team runbooks."]
    assert entry["bullet_sources"] == [
        {"bullet_id": "b_api", "alternative_id": "v_plain", "base_text": "Made reporting faster with a tested API."},
        {"bullet_id": "b_docs", "base_text": "Wrote the team runbooks."}]
    assert skills_section["kind"] == "skills"
    assert [(row["heading"], row["bullets"]) for row in skills_section["entries"]] == [("Languages", ["Python, SQL"])]
    assert client.get(f"/v1/documents/{document['id']}", headers=ALICE).json() == document
    assert len(documents()) == 1
    preview = client.get(f"/v1/documents/{document['id']}/preview.pdf", headers=ALICE)
    assert preview.status_code == 200
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(preview.content)).pages)
    assert "Languages: Python, SQL" in pdf_text and "Jul 2023 – Present" in pdf_text


def test_the_resume_is_a_copy_and_stays_editable_after_the_profile_changes(isolated_users):
    item = experience()
    document = build(plan_for(item)).json()
    changed = client.put(f"/v1/profile/items/{item['id']}/bullets/b_docs", headers=ALICE, json={
        "expected_revision": item["revision"], "text": "Rewrote the runbooks."})
    assert changed.status_code == 200, changed.text
    assert client.get(f"/v1/documents/{document['id']}", headers=ALICE).json()["content"] == document["content"]
    assert client.delete(f"/v1/profile/items/{item['id']}", headers=ALICE).status_code == 200
    edited = deepcopy(document["content"])
    edited["summary"] = "Edited after the item was archived."
    patched = client.patch(f"/v1/documents/{document['id']}", headers=ALICE,
                           json={"expected_revision": 1, "content": edited})
    assert patched.status_code == 200, patched.text
    deleted = client.request("DELETE", "/v1/profile/data", headers=ALICE, json={"confirmation": "DELETE"})
    assert deleted.status_code == 200, deleted.text
    edited["summary"] = "Edited after the profile was deleted."
    again = client.patch(f"/v1/documents/{document['id']}", headers=ALICE,
                         json={"expected_revision": 2, "content": edited})
    assert again.status_code == 200, again.text


def test_resume_defaults_style_the_new_resume(isolated_users):
    item = experience()
    set_defaults({"template": "modern",
                  "layout": {"date_format": "07/2023", "present_label": "Now", "accent_color": "teal"},
                  "sections": [{"kind": "skills", "title": "Technical skills"}, {"kind": "experience", "title": "Work history"}]})
    plan = plan_for(item, [skill("Python")])
    plan["template"] = None
    document = build(plan).json()
    assert document["template"] == "modern"
    assert document["layout"]["accent_color"] == "teal" and document["layout"]["font_size"] == 11
    assert [section["title"] for section in document["content"]["sections"]] == ["Work history", "Technical skills"]
    assert document["content"]["sections"][0]["entries"][0]["dates"] == "07/2023 – Now"


def test_build_for_a_job_links_the_job(isolated_users):
    engine, ids = isolated_users
    job_id = seeded_job_id(engine, ids["alice"])
    document = build({**plan_for(experience()), "job_id": job_id}).json()
    assert document["job_id"] == job_id
    assert build({**plan_for(experience()), "job_id": str(uuid4())}).status_code == 404


def test_another_users_items_are_rejected_and_nothing_is_created(isolated_users):
    item = experience()
    foreign_skill = skill("Python")
    before = len(documents(CASEY))
    for plan in (plan_for(item), plan_for(item, [foreign_skill])):
        response = build(plan, CASEY)
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "NOT_FOUND"
    skills_only = {**plan_for(item), "sections": [{"kind": "skills", "skill_ids": [foreign_skill["id"]]}]}
    assert build(skills_only, CASEY).status_code == 404
    assert len(documents(CASEY)) == before == 0


def test_archived_items_are_rejected(isolated_users):
    item = experience()
    assert client.delete(f"/v1/profile/items/{item['id']}", headers=ALICE).status_code == 200
    response = build(plan_for(item))
    assert response.status_code == 404, response.text
    assert documents() == []


def test_bad_plans_create_nothing(isolated_users):
    item = experience()
    education = make_item("education", {"qualification": "BSc"})
    mismatched = {"kind": "experience", "items": [{"item_id": education["id"], "picks": []}]}
    unknown_point = {"kind": "experience", "items": [{"item_id": item["id"], "picks": [{"bullet_id": "missing"}]}]}
    unknown_version = {"kind": "experience", "items": [{"item_id": item["id"], "picks": [
        {"bullet_id": "b_api", "alternative_id": "missing"}]}]}
    twice = {"kind": "experience", "items": [{"item_id": item["id"], "picks": [
        {"bullet_id": "b_api"}, {"bullet_id": "b_api", "alternative_id": "v_plain"}]}]}
    expected = [(mismatched, 422), (unknown_point, 404), (unknown_version, 404), (twice, 422),
                ({"kind": "skills", "skill_ids": [item["id"]]}, 422),
                ({"kind": "hobbies", "items": []}, 422)]
    for section, status in expected:
        response = build({**plan_for(item), "sections": [section]})
        assert response.status_code == status, (section, response.text)
    assert build({**plan_for(item), "template": "fancy"}).status_code == 422
    assert build({**plan_for(item), "unexpected": 1}).status_code == 422
    assert build({"template": "classic", "sections": []}).status_code == 422  # a title is required
    assert documents() == []


# --- suggest ----------------------------------------------------------------

def test_suggest_returns_plan_reasons_and_coverage_without_saving(isolated_users):
    engine, ids = isolated_users
    job_id = seeded_job_id(engine, ids["alice"])
    item = experience()
    python, postgres = skill("Python"), skill("PostgreSQL", "tool")
    skill("Excel", "tool")
    response = client.post("/v1/resume-builds/suggest", headers=ALICE, json={"job_id": job_id})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"plan", "reasons", "coverage", "strategy"} and body["strategy"] == "keyword-v1"
    assert body["coverage"] == {"covered": ["Python", "PostgreSQL"], "missing": []}
    plan = body["plan"]
    assert plan["job_id"] == job_id and plan["title"].startswith("Backend Engineer")
    section = next(row for row in plan["sections"] if row["kind"] == "experience")
    assert section["items"][0]["item_id"] == item["id"]
    assert section["items"][0]["picks"][0]["bullet_id"] == "b_api"
    assert any(reason.startswith("matches") for reason in body["reasons"][item["id"]])
    assert any(key.startswith(item["id"] + ":") for key in body["reasons"])
    skills = next(row for row in plan["sections"] if row["kind"] == "skills")
    assert skills["skill_ids"][:2] == [python["id"], postgres["id"]]
    assert documents() == []  # nothing saved
    created = build(plan)
    assert created.status_code == 201, created.text


def test_suggest_uses_the_points_per_item_setting_unless_overridden(isolated_users):
    engine, ids = isolated_users
    job_id = seeded_job_id(engine, ids["alice"])
    experience()
    set_defaults({"build": {"points_per_item": 1}})

    def picks(body):
        response = client.post("/v1/resume-builds/suggest", headers=ALICE, json={"job_id": job_id, **body})
        assert response.status_code == 200, response.text
        return len(response.json()["plan"]["sections"][0]["items"][0]["picks"])

    assert picks({}) == 1
    assert picks({"points_per_item": 2}) == 2


def test_suggest_only_sees_the_callers_bank_and_validates_input(isolated_users):
    engine, ids = isolated_users
    job_id = seeded_job_id(engine, ids["alice"])
    experience()
    skill("Python")
    mine = client.post("/v1/resume-builds/suggest", headers=ALICE, json={"job_id": job_id}).json()
    theirs = client.post("/v1/resume-builds/suggest", headers=CASEY, json={"job_id": job_id}).json()
    assert mine["plan"]["sections"] and theirs["plan"]["sections"] == []
    assert theirs["coverage"]["covered"] == [] and theirs["coverage"]["missing"]
    assert client.post("/v1/resume-builds/suggest", headers=ALICE, json={"job_id": str(uuid4())}).status_code == 404
    for body in ({"job_id": job_id, "points_per_item": 0}, {"job_id": job_id, "extra": 1}, {}):
        assert client.post("/v1/resume-builds/suggest", headers=ALICE, json=body).status_code == 422


# --- validate_document ------------------------------------------------------

def resume(entry=None, section=None, layout=None, headers=ALICE, **fields):
    entry = {"id": "e1", "heading": "Role", "bullets": ["One", "Two"], **(entry or {})}
    content = {"name": "A", "sections": [{"id": "s1", "title": "Experience", "entries": [entry], **(section or {})}]}
    body = {"title": "Check", "template": "classic", "content": content,
            "layout": {"font_size": 11, "margin": 18, **(layout or {})}, **fields}
    return client.post("/v1/documents", headers=headers, json=body)


def test_new_fields_are_accepted_and_older_resumes_still_validate(isolated_users):
    assert resume().status_code == 201
    item = experience()
    good = resume(
        entry={"source": {"item_id": item["id"], "item_revision": 1, "angle_id": None},
               "date_range": {"start": "2023", "end": "2024-02", "current": False},
               "bullet_sources": [None, {"bullet_id": "b_docs", "alternative_id": None, "base_text": "Two"}]},
        section={"kind": "experience", "hidden": True})
    assert good.status_code == 201, good.text


@pytest.mark.parametrize("entry", [
    {"bullet_sources": [None]},                                   # one source for two bullets
    {"bullet_sources": [None, None, None]},
    {"bullet_sources": "x"},
    {"bullet_sources": [None, "x"]},
    {"bullet_sources": [None, {"base_text": "no id"}]},
    {"bullet_sources": [None, {"bullet_id": "b", "base_text": 5}]},
    {"bullet_sources": [None, {"bullet_id": "b", "base_text": "x" * 4001}]},
    {"bullet_sources": [None, {"bullet_id": "b", "alternative_id": 3, "base_text": "x"}]},
    {"date_range": "2023"},
    {"date_range": {"start": "July 2023", "end": None, "current": False}},
    {"date_range": {"start": "2023-13", "end": None, "current": False}},
    {"date_range": {"start": "2023", "end": 2024, "current": False}},
    {"date_range": {"start": "2023", "end": None, "current": "yes"}},
    {"source": "item"},
    {"source": {"item_id": "not-a-uuid", "item_revision": 1}},
    {"source": {"item_id": str(uuid4()), "item_revision": "1"}},
    {"source": {"item_id": str(uuid4()), "item_revision": True}},
])
def test_malformed_bank_fields_are_rejected(isolated_users, entry):
    response = resume(entry=entry)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_CONTENT"


@pytest.mark.parametrize("section", [{"kind": "hobbies"}, {"kind": 3}, {"hidden": "yes"}, {"hidden": 1}])
def test_bad_section_kind_or_hidden_is_rejected(isolated_users, section):
    assert resume(section=section).status_code == 422


@pytest.mark.parametrize("key, value", [
    (key, value) for key, allowed in LAYOUT_CHOICES.items() for value in (*allowed[:1], "nonsense", 3, ["x"])
    if value not in allowed])
def test_bad_layout_values_are_rejected(isolated_users, key, value):
    response = resume(layout={key: value})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_LAYOUT"


def test_every_listed_layout_value_is_accepted(isolated_users):
    for key, allowed in LAYOUT_CHOICES.items():
        for value in allowed:
            assert resume(layout={key: value}).status_code == 201, (key, value)


def test_editing_a_resume_checks_the_new_fields_too(isolated_users):
    document = resume().json()
    bad_layout = client.patch(f"/v1/documents/{document['id']}", headers=ALICE, json={
        "expected_revision": 1, "layout": {"font_size": 11, "margin": 18, "bullet_char": "*"}})
    assert bad_layout.status_code == 422
    content = deepcopy(document["content"])
    content["sections"][0]["entries"][0]["bullet_sources"] = [None]
    assert client.patch(f"/v1/documents/{document['id']}", headers=ALICE,
                        json={"expected_revision": 1, "content": content}).status_code == 422


def test_a_resume_cannot_point_at_another_users_item(isolated_users):
    item = experience()
    source = {"item_id": item["id"], "item_revision": item["revision"]}
    response = resume(entry={"source": source}, headers=CASEY)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_SOURCE"
    own = resume(headers=CASEY).json()
    content = deepcopy(own["content"])
    content["sections"][0]["entries"][0]["source"] = source
    patched = client.patch(f"/v1/documents/{own['id']}", headers=CASEY, json={"expected_revision": 1, "content": content})
    assert patched.status_code == 422 and patched.json()["error"]["code"] == "INVALID_SOURCE"
    assert resume(entry={"source": {"item_id": str(uuid4()), "item_revision": 1}}).status_code == 422
    assert resume(entry={"source": source}).status_code == 201  # the owner may


# --- blank resumes ----------------------------------------------------------

def test_blank_resume_gets_defaults_and_profile_basics(isolated_users):
    set_basics()
    set_defaults({"template": "modern", "layout": {"date_format": "2023", "accent_color": "maroon"},
                  "sections": [{"kind": "experience", "title": "Work"}, {"kind": "custom", "title": "Fun facts", "hidden": True}],
                  "header_fields": ["email", "location"]})
    response = client.post("/v1/documents", headers=ALICE, json={
        "title": "Blank", "content": {"name": "", "sections": []}})
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["template"] == "modern"
    assert document["layout"] == {"font_size": 11, "margin": 18, "date_format": "2023", "accent_color": "maroon"}
    content = document["content"]
    assert (content["name"], content["email"], content["location"]) == (
        "Fictional Candidate", "candidate@example.invalid", "Singapore")
    assert not content.get("phone")
    assert content["summary"] == "Backend engineer who likes data."
    assert [(row["title"], row["kind"], row.get("hidden", False), row["entries"]) for row in content["sections"]] == [
        ("Work", "experience", False, []), ("Fun facts", "custom", True, [])]
    assert client.patch(f"/v1/documents/{document['id']}", headers=ALICE, json={
        "expected_revision": 1, "content": content}).status_code == 200


def test_blank_resume_without_saved_defaults_only_gains_contact_details(isolated_users):
    set_basics()
    blank_sections = [{"id": "s1", "title": "Experience", "entries": []}]
    response = client.post("/v1/documents", headers=ALICE, json={
        "title": "Blank", "template": "classic", "layout": {"font_size": 12, "margin": 20},
        "content": {"name": "Typed", "email": "", "sections": blank_sections}})
    document = response.json()
    assert document["template"] == "classic" and document["layout"] == {"font_size": 12, "margin": 20}
    assert document["content"]["name"] == "Typed"
    assert document["content"]["email"] == "candidate@example.invalid"
    assert document["content"]["sections"] == blank_sections
    default = client.post("/v1/documents", headers=ALICE, json={"title": "Default layout", "content": {"sections": []}})
    assert default.json()["layout"] == {"font_size": 11, "margin": 18}


def test_a_copy_with_entries_gets_no_defaults(isolated_users):
    set_basics()
    set_defaults({"template": "modern", "layout": {"accent_color": "teal"}})
    entry = {"id": "e", "heading": "Role", "bullets": ["Typed"]}
    content = {"name": "Typed", "sections": [{"id": "s", "title": "Mine", "entries": [entry]}]}
    document = client.post("/v1/documents", headers=ALICE, json={"title": "Copy", "content": content}).json()
    assert document["template"] == "classic" and document["layout"] == {"font_size": 11, "margin": 18}
    assert document["content"] == content


def test_recommendations_still_rank_for_the_same_user(isolated_users):
    experience()
    skill("Python")
    response = client.get("/v1/recommendations?limit=100", headers=ALICE)
    assert response.status_code == 200, response.text
    assert response.json()["items"] and response.json()["ranking_version"] == "local_tfidf_hybrid_v1"


# --- archive and restore ----------------------------------------------------

def make_resume(title="Resume to archive", headers=ALICE):
    response = client.post("/v1/documents", headers=headers, json={
        "title": title, "content": {"name": "Archive Test", "sections": []}})
    assert response.status_code == 201, response.text
    return response.json()


def test_archive_hides_a_resume_from_the_library_and_restore_brings_it_back(isolated_users):
    first, second = make_resume("First"), make_resume("Second")
    response = client.delete(f"/v1/documents/{first['id']}", headers=ALICE)
    assert response.status_code == 204 and response.content == b""
    assert [row["id"] for row in documents()] == [second["id"]]
    assert [row["id"] for row in client.get("/v1/documents?kind=resume", headers=ALICE).json()["items"]] == [second["id"]]
    assert [row["id"] for row in client.get("/v1/documents?kind=archived", headers=ALICE).json()["items"]] == [first["id"]]
    archived = client.get(f"/v1/documents/{first['id']}", headers=ALICE).json()
    assert archived["kind"] == "archived" and archived["content"] == first["content"] and archived["revision"] == first["revision"]
    assert client.delete(f"/v1/documents/{first['id']}", headers=ALICE).status_code == 204  # repeating is harmless
    restored = client.post(f"/v1/documents/{first['id']}/restore", headers=ALICE)
    assert restored.status_code == 200 and restored.json()["kind"] == "resume"
    assert {row["id"] for row in documents()} == {first["id"], second["id"]}
    assert client.post(f"/v1/documents/{first['id']}/restore", headers=ALICE).json()["kind"] == "resume"


def test_archived_resumes_cannot_be_edited_copied_or_exported_until_restored(isolated_users):
    document = make_resume()
    client.delete(f"/v1/documents/{document['id']}", headers=ALICE)
    assert client.patch(f"/v1/documents/{document['id']}", headers=ALICE, json={"expected_revision": 1, "title": "x"}).status_code == 404
    assert client.post(f"/v1/documents/{document['id']}/duplicate", headers=ALICE, json={}).status_code == 404
    assert client.post(f"/v1/documents/{document['id']}/exports", headers=ALICE).status_code == 404
    client.post(f"/v1/documents/{document['id']}/restore", headers=ALICE)
    assert client.patch(f"/v1/documents/{document['id']}", headers=ALICE, json={"expected_revision": 1, "title": "x"}).status_code == 200


def test_archiving_someone_elses_resume_is_not_found_and_changes_nothing(isolated_users):
    document = make_resume("Alice only")
    assert client.delete(f"/v1/documents/{document['id']}", headers=CASEY).status_code == 404
    assert client.post(f"/v1/documents/{document['id']}/restore", headers=CASEY).status_code == 404
    assert [row["id"] for row in documents()] == [document["id"]]
    client.delete(f"/v1/documents/{document['id']}", headers=ALICE)
    assert client.post(f"/v1/documents/{document['id']}/restore", headers=CASEY).status_code == 404
    assert client.get(f"/v1/documents/{document['id']}", headers=ALICE).json()["kind"] == "archived"
    assert client.delete(f"/v1/documents/{uuid4()}", headers=ALICE).status_code == 404


def test_other_kinds_of_documents_are_left_alone(isolated_users):
    engine, ids = isolated_users
    document = make_resume()
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(ids["alice"])})
        db.execute(text("UPDATE documents SET kind='archived_test' WHERE id=:id"), {"id": document["id"]})
    assert client.delete(f"/v1/documents/{document['id']}", headers=ALICE).status_code == 404
    assert client.post(f"/v1/documents/{document['id']}/restore", headers=ALICE).status_code == 404


def test_an_application_keeps_its_pdf_snapshot_after_the_resume_is_archived(isolated_users):
    engine, ids = isolated_users
    job_id = seeded_job_id(engine, ids["alice"])
    document = make_resume("Snapshot resume")
    assert client.post(f"/v1/documents/{document['id']}/review", headers=ALICE, json={"expected_revision": 1}).status_code == 200
    attached = client.put(f"/v1/applications/{job_id}", headers=ALICE, json={
        "expected_revision": 0, "resume_document_id": document["id"], "expected_resume_revision": 1})
    assert attached.status_code == 200, attached.text
    packet = attached.json()["resume_packet"]
    assert client.delete(f"/v1/documents/{document['id']}", headers=ALICE).status_code == 204
    again = next(row for row in client.get("/v1/applications", headers=ALICE).json()["items"] if row["job_id"] == job_id)
    assert again["resume_packet"] == packet
    download = client.get(packet["download_url"], headers=ALICE)
    assert download.status_code == 200 and download.content.startswith(b"%PDF")
    assert "Archive Test" in "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(download.content)).pages)
    # A new attachment of the archived resume is refused; the old snapshot stays.
    refused = client.put(f"/v1/applications/{job_id}", headers=ALICE, json={
        "expected_revision": again["revision"], "resume_document_id": document["id"], "expected_resume_revision": 1})
    assert refused.status_code == 422 or refused.status_code == 404
    assert next(row for row in client.get("/v1/applications", headers=ALICE).json()["items"] if row["job_id"] == job_id)["resume_packet"] == packet


def test_from_bank_builds_certifications_awards_and_volunteering(isolated_users):
    cert = make_item("certification", {"name": "Docker Certified Associate", "issuer": "Example Academy", "start": "2022-03"})
    award = make_item("award", {"title": "Hackathon winner", "awarder": "City Council", "start": "2021"})
    volunteering = make_item("volunteering", {"title": "Mentor", "organisation": "Code Club", "bullets": [
        {"id": "b_vol", "text": "Taught Python to teenagers."}]})
    plan = {"title": "Extras", "template": "classic", "job_id": None, "summary": {"mode": "custom", "text": ""}, "sections": [
        {"kind": "certifications", "items": [{"item_id": cert["id"], "picks": []}]},
        {"kind": "awards", "items": [{"item_id": award["id"], "picks": []}]},
        {"kind": "volunteering", "items": [{"item_id": volunteering["id"], "picks": [{"bullet_id": "b_vol"}]}]}]}
    response = build(plan)
    assert response.status_code == 201, response.text
    sections = response.json()["content"]["sections"]
    assert [s["kind"] for s in sections] == ["certifications", "awards", "volunteering"]
    assert sections[0]["entries"][0]["subheading"] == "Example Academy"
    preview = client.get(f"/v1/documents/{response.json()['id']}/preview.pdf", headers=ALICE)
    text_out = "\n".join(page.extract_text() for page in PdfReader(BytesIO(preview.content)).pages)
    assert "Docker Certified Associate" in text_out and "Taught Python to teenagers." in text_out
    wrong = {**plan, "sections": [{"kind": "awards", "items": [{"item_id": cert["id"], "picks": []}]}]}
    assert build(wrong).status_code == 422


CONTENT_FOR_TAILOR = {"name": "Tailor Test", "sections": [{"id": "s", "title": "Experience", "entries": [
    {"id": "e", "heading": "Engineer", "subheading": "Acme", "dates": "", "bullets": ["Ran lunches", "Wrote Python pipelines"]}]}]}


@pytest.fixture
def tailor_jobs(isolated_users):
    engine, user_ids = isolated_users
    with Session(engine) as db, db.begin():
        jobs = [Job(title=f"Tailor Job {index}", description="Build Python pipelines", skills=["Python"]) for index in range(6)]
        db.add_all(jobs); db.flush()
        ids = [str(job.id) for job in jobs]
    yield ids
    with Session(engine) as db, db.begin():
        for user_id in user_ids.values():
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            db.execute(text("DELETE FROM ai_tailor_uses WHERE user_id=:uid"), {"uid": user_id})
            db.execute(text("DELETE FROM documents WHERE job_id = ANY(CAST(:ids AS uuid[])) AND user_id=:uid"), {"ids": ids, "uid": user_id})
        db.execute(text("DELETE FROM jobs WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids})


def tailor(document, job_id, headers=ALICE, **extra):
    return client.post(f"/v1/documents/{document['id']}/tailor", headers=headers, json={"job_id": job_id, **extra})


def test_rules_tailoring_copies_reorders_and_leaves_the_original(tailor_jobs):
    source = client.post("/v1/documents", headers=ALICE, json={"title": "Base", "content": CONTENT_FOR_TAILOR}).json()
    response = tailor(source, tailor_jobs[0])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["job_id"] == tailor_jobs[0] and body["ai"]["status"] == "off"
    assert body["document"]["content"]["sections"][0]["entries"][0]["bullets"] == ["Wrote Python pipelines", "Ran lunches"]
    assert client.get(f"/v1/documents/{source['id']}", headers=ALICE).json()["content"] == source["content"]


def test_tailoring_someone_elses_resume_is_not_found(tailor_jobs):
    source = client.post("/v1/documents", headers=ALICE, json={"title": "Base", "content": CONTENT_FOR_TAILOR}).json()
    assert tailor(source, tailor_jobs[0], CASEY).status_code == 404


def test_ai_tailoring_needs_a_configured_model(tailor_jobs, monkeypatch):
    monkeypatch.setattr(settings, "model_backend", "heuristic")
    source = client.post("/v1/documents", headers=ALICE, json={"title": "Base", "content": CONTENT_FOR_TAILOR}).json()
    response = tailor(source, tailor_jobs[0], mode="ai")
    assert response.status_code == 503 and response.json()["error"]["code"] == "AI_NOT_CONFIGURED"


def test_ai_tailoring_allows_five_jobs_in_total(tailor_jobs, monkeypatch):
    class Reword:
        def rewrite(self, entries, job):
            return [[bullet.replace("Ran", "Organised") for bullet in bullets] for bullets in entries]
    monkeypatch.setattr("job_hunter.preparation.ai_tailoring.build_model", lambda: Reword())
    source = client.post("/v1/documents", headers=ALICE, json={"title": "Base", "content": CONTENT_FOR_TAILOR}).json()
    for job_id in tailor_jobs[:5]:
        response = tailor(source, job_id, mode="ai")
        assert response.status_code == 201 and response.json()["ai"]["status"] == "applied", response.text
    assert client.get("/v1/me", headers=ALICE).json()["allowance"]["remaining"] == 0
    assert tailor(source, tailor_jobs[0], mode="ai").status_code == 201
    over = tailor(source, tailor_jobs[5], mode="ai")
    assert over.status_code == 402 and over.json()["error"]["code"] == "AI_LIMIT_REACHED"
    assert tailor(source, tailor_jobs[5]).status_code == 201
