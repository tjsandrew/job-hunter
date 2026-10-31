"""Profile import contracts against real PostgreSQL and isolated local identities."""
from copy import deepcopy
import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration.test_profile_bank_api import ALICE, CASEY, bank, client, create_item, isolated_users  # noqa: F401
from tests.test_profile_importing import pdf_fixture

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                                reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")

CONTENT = {
    "name": "Fictional Candidate", "email": "fictional@example.invalid", "phone": "", "location": "Singapore",
    "summary": "Synthetic summary", "sections": [
        {"id": "experience", "title": "Experience", "entries": [
            {"id": "e1", "heading": "Fictional Engineer", "subheading": "Example Employer", "dates": "Jul 2023 – Present",
             "bullets": ["Built synthetic APIs", "Wrote tested pipelines"]}]},
        {"id": "skills", "title": "Skills", "entries": [{"id": "s1", "heading": "Tools", "subheading": "", "dates": "", "bullets": ["Python"]}]},
    ],
}


def new_document(headers=ALICE, content=CONTENT):
    response = client.post("/v1/documents", headers=headers, json={
        "title": "Import source", "template": "classic", "content": deepcopy(content),
        "layout": {"font_size": 11, "margin": 18}})
    assert response.status_code == 201, response.text
    return response.json()


def start(body, headers=ALICE, status=201):
    response = client.post("/v1/profile/imports", headers=headers, json=body)
    assert response.status_code == status, response.text
    return response.json()


def apply(row, decisions, headers=ALICE, epoch=None):
    return client.post(f"/v1/profile/imports/{row['id']}/apply", headers=headers, json={
        "expected_profile_epoch": row["profile_epoch"] if epoch is None else epoch, "decisions": decisions})


def candidate(row, kind):
    return next(item for item in row["candidates"] if item["kind"] == kind)


def error_code(response):
    return response.json()["error"]["code"]


def test_document_import_adds_items_with_provenance_and_one_revision_step(isolated_users):
    document = new_document()
    row = start({"document_id": document["id"]})
    assert row["status"] == "ready" and row["parser"] == "document-v1"
    before = bank()["bank_revision"]
    decisions = [{"candidate_id": item["candidate_id"], "action": "add"} for item in row["candidates"] if item["kind"] != "basics"]
    assert len(decisions) >= 2
    response = apply(row, decisions)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["counts"]["added"] == len(decisions)
    assert result["bank_revision"] == before + 1 == bank()["bank_revision"]
    items = bank()["items"]
    assert len(items) == len(decisions)
    experience = next(item for item in items if item["kind"] == "experience")
    assert experience["origin"] == "import" and experience["import_id"] == row["id"]
    points = experience["data"]["bullets"]
    assert [point["text"] for point in points] == ["Built synthetic APIs", "Wrote tested pipelines"]
    for point in points:
        assert point["provenance"]["origin"] == "import" and point["provenance"]["evidence"]
    # Idempotent: replay returns the same result and creates no duplicates.
    again = apply(row, decisions)
    assert again.status_code == 200 and again.json() == result
    assert len(bank()["items"]) == len(decisions) and bank()["bank_revision"] == before + 1


def test_merge_is_additive_and_reports_conflicts(isolated_users):
    existing = client.post("/v1/profile/items", headers=ALICE, json={"kind": "experience", "tags": ["keep"], "data": {
        "title": "Fictional Engineer", "organisation": "Example Employer", "location": "", "summary": "Existing summary",
        "start": "2023-07", "bullets": [{"id": "b_keep", "text": "Built synthetic APIs", "tags": ["api"], "skills": [],
                                         "alternatives": [{"id": "a_1", "text": "Created synthetic APIs"}]}]}})
    assert existing.status_code == 201, existing.text
    existing = existing.json()
    document = deepcopy(CONTENT)
    document["sections"][0]["entries"][0]["subheading"] = "Example Employer"
    row = start({"document_id": new_document(content=document)["id"]})
    cand = candidate(row, "experience")
    assert cand["match"]["status"] == "update" and cand["match"]["item_id"] == existing["id"]
    cand_data = deepcopy(cand["data"])
    cand_data["summary"] = "Different incoming summary"
    cand_data["location"] = "Singapore"
    before = bank()["bank_revision"]
    response = apply(row, [{"candidate_id": cand["candidate_id"], "action": "merge", "target_item_id": existing["id"],
                            "expected_revision": existing["revision"], "data": cand_data}])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["counts"]["merged"] == 1 and result["bank_revision"] == before + 1
    assert result["conflicts"][0]["candidate_id"] == cand["candidate_id"]
    assert result["conflicts"][0]["fields"]["summary"] == {"existing": "Existing summary", "incoming": "Different incoming summary"}
    merged = client.get(f"/v1/profile/items/{existing['id']}", headers=ALICE).json()
    assert merged["data"]["summary"] == "Existing summary" and merged["data"]["location"] == "Singapore"
    assert "keep" in merged["tags"]
    points = merged["data"]["bullets"]
    assert points[0]["id"] == "b_keep" and points[0]["tags"] == ["api"]
    assert points[0]["alternatives"][0]["text"] == "Created synthetic APIs"
    assert [point["text"] for point in points] == ["Built synthetic APIs", "Wrote tested pipelines"]
    assert points[1]["provenance"]["origin"] == "import"


def test_stale_merge_target_revision_rolls_back_everything(isolated_users):
    existing = create_item("Fictional Engineer")
    row = start({"document_id": new_document()["id"]})
    others = [item for item in row["candidates"] if item["kind"] == "skill"]
    cand = candidate(row, "experience")
    before = bank()
    decisions = [{"candidate_id": item["candidate_id"], "action": "add"} for item in others] + [
        {"candidate_id": cand["candidate_id"], "action": "merge", "target_item_id": existing["id"], "expected_revision": existing["revision"] + 5}]
    response = apply(row, decisions)
    assert response.status_code == 409 and error_code(response) == "REVISION_CONFLICT"
    after = bank()
    assert after["bank_revision"] == before["bank_revision"] and len(after["items"]) == len(before["items"])
    assert client.get(f"/v1/profile/imports/{row['id']}", headers=ALICE).json()["status"] == "ready"


def test_epoch_fence_after_delete_profile_data(isolated_users):
    row = start({"document_id": new_document()["id"]})
    deleted = client.request("DELETE", "/v1/profile/data", headers=ALICE, json={"confirmation": "DELETE"})
    assert deleted.status_code == 200, deleted.text
    response = apply(row, [{"candidate_id": "basics", "action": "skip"}])
    assert response.status_code == 409 and error_code(response) == "PROFILE_EPOCH_CHANGED"


def test_import_uses_frozen_input_not_live_document(isolated_users):
    document = new_document()
    row = start({"document_id": document["id"]})
    changed = deepcopy(CONTENT)
    changed["sections"][0]["entries"][0]["heading"] = "Live Edited Title"
    patched = client.patch(f"/v1/documents/{document['id']}", headers=ALICE, json={"expected_revision": document["revision"], "content": changed})
    assert patched.status_code == 200, patched.text
    assert candidate(client.get(f"/v1/profile/imports/{row['id']}", headers=ALICE).json(), "experience")["data"]["title"] == "Fictional Engineer"
    engine, user_ids = isolated_users
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_ids["alice"])})
        db.execute(text("UPDATE profile_imports SET status='failed', error_code='IMPORT_FAILED', candidates='[]' WHERE id=:id"), {"id": row["id"]})
    retried = client.post(f"/v1/profile/imports/{row['id']}/retry", headers=ALICE)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "ready"
    assert candidate(retried.json(), "experience")["data"]["title"] == "Fictional Engineer"
    assert row["input_ref"]["document_revision"] == document["revision"]


@pytest.mark.parametrize("field", ["text", "json_resume"])
def test_oversized_input_is_rejected(isolated_users, field):
    value = "a" * (1024 * 1024 + 1) if field == "text" else {"basics": {"name": "x"}, "pad": "a" * (1024 * 1024)}
    response = client.post("/v1/profile/imports", headers=ALICE, json={field: value})
    assert response.status_code == 422 and error_code(response) == "INPUT_TOO_LARGE"
    assert client.get("/v1/profile/imports", headers=ALICE).json()["items"] == []


def upload_pdf(headers=ALICE):
    data = pdf_fixture()
    initiated = client.post("/v1/uploads", headers=headers, json={"filename": "resume.pdf", "content_type": "application/pdf", "size_bytes": len(data)})
    assert initiated.status_code == 201, initiated.text
    captured = client.put(initiated.json()["upload_url"], headers={**headers, "Content-Type": "application/pdf"}, content=data)
    assert captured.status_code == 200, captured.text
    return initiated.json()["upload_id"]


def test_tenant_isolation(isolated_users):
    upload_id = upload_pdf()
    document = new_document()
    assert start({"upload_id": upload_id}, CASEY, 404)["error"]["code"] == "NOT_FOUND"
    assert start({"document_id": document["id"]}, CASEY, 404)["error"]["code"] == "NOT_FOUND"
    row = start({"document_id": document["id"]})
    path = f"/v1/profile/imports/{row['id']}"
    assert client.get(path, headers=CASEY).status_code == 404
    assert client.post(path + "/apply", headers=CASEY, json={"expected_profile_epoch": 0, "decisions": []}).status_code == 404
    assert client.post(path + "/discard", headers=CASEY).status_code == 404
    assert client.post(path + "/retry", headers=CASEY).status_code == 404
    assert client.get("/v1/profile/imports", headers=CASEY).json()["items"] == []
    foreign = create_item("Alice only")
    own = start({"document_id": new_document(headers=CASEY)["id"]}, CASEY)
    cand = candidate(own, "experience")
    response = apply(own, [{"candidate_id": cand["candidate_id"], "action": "merge", "target_item_id": foreign["id"],
                            "expected_revision": foreign["revision"]}], CASEY)
    assert response.status_code == 404
    assert client.get(f"/v1/profile/items/{foreign['id']}", headers=ALICE).json()["revision"] == foreign["revision"]


def test_basics_apply_only_accepted_fields_and_checks_revision(isolated_users):
    row = start({"document_id": new_document()["id"]})
    basics = candidate(row, "basics")
    assert basics["data"]["email"] == "fictional@example.invalid"
    revision = basics["match"]["basics_revision"]
    stale = apply(row, [{"candidate_id": "basics", "action": "add", "accepted_fields": ["email"], "expected_revision": revision + 3}])
    assert stale.status_code == 409 and error_code(stale) == "REVISION_CONFLICT"
    assert client.get("/v1/profile", headers=ALICE).json()["draft"].get("email") is None
    response = apply(row, [{"candidate_id": "basics", "action": "add", "accepted_fields": ["email"], "expected_revision": revision}])
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["basics_updated"] == 1
    profile = client.get("/v1/profile", headers=ALICE).json()
    draft = profile["draft"]
    assert draft["email"] == "fictional@example.invalid" and draft["name"] == "Fictional Candidate"
    assert "summary" not in draft and "location" not in draft


def test_pdf_upload_import_reaches_ready_with_heuristic_parser(isolated_users):
    row = start({"upload_id": upload_pdf()})
    assert row["status"] == "ready" and row["parser"] == "heuristic-v1", row
    assert any(item["kind"] == "experience" for item in row["candidates"])


def test_discard_clears_input_and_blocks_apply(isolated_users):
    row = start({"document_id": new_document()["id"]})
    discarded = client.post(f"/v1/profile/imports/{row['id']}/discard", headers=ALICE)
    assert discarded.status_code == 200 and discarded.json()["status"] == "discarded"
    assert discarded.json()["candidates"] == []
    engine, user_ids = isolated_users
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_ids["alice"])})
        assert db.execute(text("SELECT input_payload FROM profile_imports WHERE id=:id"), {"id": row["id"]}).scalar_one() is None
    response = apply(row, [])
    assert response.status_code == 409, response.text
    assert error_code(response) == "IMPORT_NOT_READY"


def test_hostile_import_bodies_are_rejected_before_parsing(isolated_users):
    huge = client.post("/v1/profile/imports", headers={**ALICE, "Content-Type": "application/json"},
                       content=b'{"text": "' + b"a" * (3 * 1024 * 1024) + b'"}')
    assert huge.status_code == 413 and error_code(huge) == "INPUT_TOO_LARGE"
    nested = client.post("/v1/profile/imports", headers={**ALICE, "Content-Type": "application/json"},
                         content=b'{"json_resume": ' + b'{"a": ' * 5000 + b'1' + b'}' * 5000 + b'}')
    assert nested.status_code == 422 and error_code(nested) == "INVALID_IMPORT_SOURCE"
    malformed = client.post("/v1/profile/imports", headers=ALICE,
                            json={"json_resume": {"meta": {"jobHunter": {"schemaVersion": 1, "basics": {}, "items": ["x"]}}}})
    assert malformed.status_code == 201 and malformed.json()["status"] == "failed"
    assert malformed.json()["error_code"] == "INVALID_BANK_METADATA"


def test_unexpected_parser_errors_fail_the_import_instead_of_500(isolated_users, monkeypatch):
    from job_hunter.profile_bank.importing import services as import_services
    monkeypatch.setattr(import_services, "from_text", lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("boom")))
    response = client.post("/v1/profile/imports", headers=ALICE, json={"text": "Jordan Example\nEXPERIENCE"})
    assert response.status_code == 201 and response.json()["status"] == "failed"
    assert response.json()["error_code"] == "IMPORT_FAILED"


DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upload_file(filename, content_type, data, headers=ALICE, put_type=None):
    initiated = client.post("/v1/uploads", headers=headers, json={"filename": filename, "content_type": content_type, "size_bytes": len(data)})
    if initiated.status_code != 201:
        return initiated, None
    captured = client.put(initiated.json()["upload_url"], headers={**headers, "Content-Type": put_type or content_type}, content=data)
    return initiated, captured


def test_docx_upload_import_reaches_ready_with_candidates(isolated_users):
    from tests.test_profile_importing_docx import make_docx
    data = make_docx("table")
    initiated, captured = upload_file("resume.docx", DOCX_TYPE, data)
    assert captured.status_code == 200, captured.text
    assert captured.json()["status"] == "ready_for_review" and captured.json()["error_code"] is None
    shown = client.get(f"/v1/uploads/{initiated.json()['upload_id']}", headers=ALICE).json()
    assert "Backend Engineer" in shown["extracted_text"] and shown["page_count"] is None
    assert client.get("/v1/uploads", headers=ALICE).json()["items"][0]["filename"] == "resume.docx"
    download = client.get(f"/v1/uploads/{initiated.json()['upload_id']}/download", headers=ALICE)
    assert download.headers["content-type"] == DOCX_TYPE and download.content == data
    row = start({"upload_id": initiated.json()["upload_id"]})
    assert row["status"] == "ready" and row["parser"] == "heuristic-v1", row
    assert any(item["kind"] == "experience" and item["data"]["title"] == "Backend Engineer" for item in row["candidates"])
    assert any(item["kind"] == "skill" for item in row["candidates"])
    assert candidate(row, "basics")["data"]["email"] == "jordan@example.invalid"
    engine, user_ids = isolated_users
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_ids["alice"])})
        assert db.execute(text("SELECT content_type FROM uploads WHERE id=:id"), {"id": initiated.json()["upload_id"]}).scalar_one() == DOCX_TYPE


def test_renamed_docx_is_detected_by_content_and_stored_accurately(isolated_users):
    from tests.test_profile_importing_docx import make_docx
    initiated, captured = upload_file("resume.pdf", "application/pdf", make_docx())
    assert captured.status_code == 200, captured.text
    engine, user_ids = isolated_users
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_ids["alice"])})
        stored = db.execute(text("SELECT content_type, file_path FROM uploads WHERE id=:id"), {"id": initiated.json()["upload_id"]}).one()
    assert stored.content_type == DOCX_TYPE and stored.file_path.endswith(".docx")
    assert start({"upload_id": initiated.json()["upload_id"]})["status"] == "ready"


def test_legacy_doc_upload_is_refused_with_friendly_message(isolated_users):
    refused, _ = upload_file("resume.doc", "application/msword", b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
    assert refused.status_code == 422 and error_code(refused) == "LEGACY_DOC"
    assert "Save it as PDF or .docx" in refused.json()["error"]["message"]
    # A legacy file disguised with a .docx name is still caught from its bytes, and nothing is stored.
    initiated, captured = upload_file("resume.docx", DOCX_TYPE, b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
    assert captured.status_code == 422 and error_code(captured) == "LEGACY_DOC"
    assert "Save it as PDF or .docx" in captured.json()["error"]["message"]
    assert client.get(f"/v1/uploads/{initiated.json()['upload_id']}", headers=ALICE).json()["sha256"] is None


def test_hostile_and_unsupported_uploads_are_refused(isolated_users):
    from tests.test_profile_importing_docx import make_docx, rebuild
    refused, _ = upload_file("resume.rtf", "application/rtf", b"{\\rtf1 x}")
    assert refused.status_code == 422 and error_code(refused) == "UNSUPPORTED_FILE"
    macro = rebuild(make_docx(), add={"word/vbaProject.bin": b"x"})
    _, captured = upload_file("resume.docx", DOCX_TYPE, macro)
    assert captured.status_code == 422 and error_code(captured) == "MACRO_ENABLED"
    bomb = rebuild(make_docx(), add={"word/media/blob.bin": b"\x00" * (20 * 1024 * 1024)})
    _, captured = upload_file("resume.docx", DOCX_TYPE, bomb)
    assert captured.status_code == 422 and error_code(captured) == "DOCX_ZIP_BOMB"
    _, captured = upload_file("resume.docx", DOCX_TYPE, b"plain text, not a document")
    assert captured.status_code == 422 and error_code(captured) == "UNSUPPORTED_FILE"


def test_delete_uploaded_original_preserves_imported_facts_and_documents(isolated_users):
    from pathlib import Path
    upload_id = upload_pdf()
    row = start({"upload_id": upload_id})
    decisions = [{"candidate_id": item["candidate_id"], "action": "add"}
                 for item in row["candidates"] if item["kind"] != "basics"]
    assert apply(row, decisions).status_code == 200
    before = bank()
    document = new_document()
    engine, user_ids = isolated_users
    with Session(engine) as db:
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_ids['alice'])})
        path = db.execute(text("SELECT file_path FROM uploads WHERE id=:id"), {"id": upload_id}).scalar_one()
    assert Path(path).exists()
    assert client.delete(f"/v1/uploads/{upload_id}", headers=CASEY).status_code == 404
    assert Path(path).exists()
    response = client.delete(f"/v1/uploads/{upload_id}", headers=ALICE)
    assert response.status_code == 204, response.text
    assert not Path(path).exists()
    assert bank() == before
    assert client.get(f"/v1/documents/{document['id']}", headers=ALICE).status_code == 200
    assert all(item['upload_id'] != upload_id for item in client.get('/v1/uploads', headers=ALICE).json()['items'])
    for suffix in ('', '/download'):
        assert client.get(f"/v1/uploads/{upload_id}{suffix}", headers=ALICE).status_code == 404
    assert client.delete(f"/v1/uploads/{upload_id}", headers=ALICE).status_code == 404
    with Session(engine) as db:
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_ids['alice'])})
        assert db.execute(text("SELECT upload_id FROM profile_imports WHERE id=:id"), {"id": row['id']}).scalar_one() is None


STACKED = """Alex Tan
EXPERIENCE
Research Assistant
Acme Labs
Jan 2024 – Present
- Built forecasting pipelines
"""


def test_merging_an_ended_role_into_a_current_one_keeps_the_dates_and_reports_them(isolated_users):
    first = start({"text": STACKED})
    assert apply(first, [{"candidate_id": candidate(first, "experience")["candidate_id"], "action": "add"}]).status_code == 200
    second = start({"text": STACKED.replace("Jan 2024 – Present", "Jan 2024 – Jun 2025").replace("pipelines", "pipelines in Python")})
    role = candidate(second, "experience")
    assert role["match"]["status"] == "update"
    response = apply(second, [{"candidate_id": role["candidate_id"], "action": "merge", "target_item_id": role["match"]["item_id"],
                               "expected_revision": role["match"]["item_revision"]}])
    assert response.status_code == 200, response.text
    assert set(response.json()["conflicts"][0]["fields"]) == {"end", "current"}
    item = next(item for item in bank()["items"] if item["kind"] == "experience")
    assert (item["data"]["start"], item["data"].get("end"), item["data"]["current"]) == ("2024-01", None, True)


def test_an_impossible_edit_in_the_review_gets_a_plain_message_and_applies_nothing(isolated_users):
    row = start({"text": STACKED})
    role = candidate(row, "experience")
    before = bank()["bank_revision"]
    response = apply(row, [{"candidate_id": role["candidate_id"], "action": "add", "data": {**role["data"], "end": "2025-06"}}])
    assert response.status_code == 422 and error_code(response) == "INVALID_IMPORTED_ITEM"
    message = response.json()["error"]["message"]
    assert "Research Assistant" in message and "a current item cannot have an end date" in message and "pydantic" not in message
    assert bank()["bank_revision"] == before
