"""Profile bank contracts against real PostgreSQL and isolated local identities."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from job_hunter.api.main import app
from job_hunter.config import settings
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import Profile, User

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
            db.add(User(id=user_id, auth_subject=f"bank-test-{user_id}", display_name=key))
        db.flush()
        for user_id in user_ids.values():
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            db.add(Profile(user_id=user_id, draft={"name": "Fictional Candidate"}, revision=1, bank_revision=1))
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


def bank(headers=ALICE):
    response = client.get("/v1/profile/bank", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def create_item(title="Fictional Engineer", headers=ALICE):
    response = client.post("/v1/profile/items", headers=headers, json={
        "kind": "experience", "data": {"title": title, "organisation": "Example Employer", "bullets": []},
    })
    assert response.status_code == 201, response.text
    return response.json()


def assert_conflict(response):
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "REVISION_CONFLICT"


def test_bank_item_tenant_isolation_and_settings(isolated_users):
    item = create_item()
    item_id = item["id"]
    assert all(row["id"] != item_id for row in bank(CASEY)["items"])
    operations = [
        client.get(f"/v1/profile/items/{item_id}", headers=CASEY),
        client.patch(f"/v1/profile/items/{item_id}", headers=CASEY, json={"expected_revision": 1, "tags": ["data"]}),
        client.delete(f"/v1/profile/items/{item_id}", headers=CASEY),
        client.post(f"/v1/profile/items/{item_id}/revert", headers=CASEY, json={"expected_revision": 1, "data": item["data"]}),
        client.put("/v1/profile/items/order", headers=CASEY, json={"kind": "experience", "item_ids": [item_id], "expected_bank_revision": bank(CASEY)["bank_revision"]}),
        client.post("/v1/profile/items", headers=CASEY, json={"kind": "project", "parent_id": item_id, "data": {"name": "Foreign parent"}}),
        client.post(f"/v1/profile/items/{item_id}/bullets", headers=CASEY, json={"expected_revision": 1, "text": "Foreign edit"}),
    ]
    assert all(response.status_code == 404 for response in operations), [response.text for response in operations]
    settings_response = client.put("/v1/settings", headers=ALICE, json={"expected_revision": 0, "resume_defaults": {"template": "modern"}})
    assert settings_response.status_code == 200, settings_response.text
    assert client.get("/v1/settings", headers=CASEY).json()["resume_defaults"] == {}
    own_settings = client.put("/v1/settings", headers=CASEY, json={"expected_revision": 0, "resume_defaults": {"template": "classic"}})
    assert own_settings.status_code == 200, own_settings.text
    assert client.get("/v1/settings", headers=ALICE).json()["resume_defaults"] == {"template": "modern"}
    assert_conflict(client.put("/v1/settings", headers=ALICE, json={"expected_revision": 0, "resume_defaults": {}}))


def test_each_mutation_advances_bank_and_confirm_is_revision_checked(isolated_users):
    revision = bank()["bank_revision"]

    def advanced():
        nonlocal revision
        current = bank()["bank_revision"]
        assert current == revision + 1
        revision = current

    item = create_item()
    advanced()
    first_confirm = client.post("/v1/profile/confirm", headers=ALICE, json={"expected_bank_revision": revision})
    assert first_confirm.status_code == 200, first_confirm.text
    assert_conflict(client.patch(f"/v1/profile/items/{item['id']}", headers=ALICE, json={"expected_revision": 0, "tags": []}))
    response = client.patch(f"/v1/profile/items/{item['id']}", headers=ALICE, json={"expected_revision": item["revision"], "tags": ["backend"]})
    assert response.status_code == 200, response.text
    item = response.json()
    advanced()
    assert_conflict(client.post("/v1/profile/confirm", headers=ALICE, json={"expected_bank_revision": revision - 1}))
    second_confirm = client.post("/v1/profile/confirm", headers=ALICE, json={"expected_bank_revision": revision})
    assert second_confirm.status_code == 200, second_confirm.text
    assert first_confirm.json()["profile_version_id"] != second_confirm.json()["profile_version_id"]
    response = client.post(f"/v1/profile/items/{item['id']}/bullets", headers=ALICE, json={"expected_revision": item["revision"], "text": "Built synthetic APIs", "tags": ["backend"]})
    assert response.status_code == 200, response.text
    item = response.json()
    advanced()
    bullet_id = item["data"]["bullets"][0]["id"]
    previous = item["data"]
    response = client.put(f"/v1/profile/items/{item['id']}/bullets/{bullet_id}", headers=ALICE, json={"expected_revision": item["revision"], "text": "Built tested synthetic APIs"})
    assert response.status_code == 200, response.text
    item = response.json()
    advanced()
    assert item["data"]["bullets"][0]["alternatives"][0]["text"] == "Built synthetic APIs"
    response = client.post(f"/v1/profile/items/{item['id']}/bullets/{bullet_id}/alternatives", headers=ALICE, json={"expected_revision": item["revision"], "text": "Created a tested API for example data"})
    assert response.status_code == 200, response.text
    item = response.json()
    advanced()
    assert_conflict(client.post(f"/v1/profile/items/{item['id']}/revert", headers=ALICE, json={"expected_revision": item["revision"] - 1, "data": previous}))
    invalid = client.post(f"/v1/profile/items/{item['id']}/revert", headers=ALICE, json={"expected_revision": item["revision"], "data": previous, "tags": None})
    assert invalid.status_code == 422, invalid.text
    assert bank()["bank_revision"] == revision
    response = client.post(f"/v1/profile/items/{item['id']}/revert", headers=ALICE, json={"expected_revision": item["revision"], "data": previous})
    assert response.status_code == 200, response.text
    item = response.json()
    advanced()
    response = client.put("/v1/profile/items/order", headers=ALICE, json={"kind": "experience", "item_ids": [item["id"]], "expected_bank_revision": revision})
    assert response.status_code == 200, response.text
    advanced()
    basics = client.get("/v1/profile", headers=ALICE).json()
    response = client.put("/v1/profile", headers=ALICE, json={"expected_revision": basics["revision"], "draft": {"name": "Updated Fictional Candidate"}})
    assert response.status_code == 200, response.text
    advanced()
    response = client.delete(f"/v1/profile/items/{item['id']}", headers=ALICE)
    assert response.status_code in (200, 204), response.text
    advanced()
    assert not bank()["items"]


def test_deletion_removes_all_profile_facts_but_retains_resume_and_application(isolated_users, tmp_path):
    from job_hunter.domain.models import Application, Document, DocumentExport, Job, ProfileImport, Upload
    engine, ids = isolated_users
    item = create_item()
    child = client.post("/v1/profile/items", headers=ALICE, json={"kind": "project", "parent_id": item["id"], "data": {"name": "Nested synthetic project"}})
    assert child.status_code == 201, child.text
    archived = client.delete(f"/v1/profile/items/{item['id']}", headers=ALICE)
    assert archived.status_code in (200, 204)
    confirmed = client.post("/v1/profile/confirm", headers=ALICE, json={"expected_bank_revision": bank()["bank_revision"]})
    assert confirmed.status_code == 200, confirmed.text
    assert client.put("/v1/settings", headers=ALICE, json={"expected_revision": 0, "resume_defaults": {"template": "modern"}}).status_code == 200
    upload_path = tmp_path / "profile-upload.pdf"
    export_path = tmp_path / "application-export.pdf"
    upload_path.write_bytes(b"fictional uploaded resume")
    export_path.write_bytes(b"fictional attached resume")
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(ids["alice"])})
        job = db.query(Job).first()
        assert job is not None
        document = Document(user_id=ids["alice"], title="Separate resume", content={"name": "Fictional Candidate", "sections": []}, layout={})
        upload = Upload(user_id=ids["alice"], filename="profile-upload.pdf", content_type="application/pdf", declared_size=20, file_path=str(upload_path))
        db.add_all([document, upload])
        db.flush()
        export = DocumentExport(user_id=ids["alice"], document_id=document.id, revision=1, file_path=str(export_path))
        db.add(export)
        db.flush()
        db.add(Application(user_id=ids["alice"], job_id=job.id, resume_export_id=export.id))
        db.add(ProfileImport(user_id=ids["alice"], source_type="upload", upload_id=upload.id, input_ref={"sha256": "synthetic"}, input_payload={"text": "private facts"}))
        document_id = str(document.id)
    before = bank()
    response = client.request("DELETE", "/v1/profile/data", headers=ALICE, json={"confirmation": "DELETE", "delete_settings": False})
    assert response.status_code in (200, 204), response.text
    after = bank()
    assert after["basics"] == {} and after["items"] == []
    assert after["confirmed_revision"] is None
    assert after["bank_revision"] == before["bank_revision"] + 1
    assert after["profile_epoch"] == before["profile_epoch"] + 1
    assert not upload_path.exists() and export_path.exists()
    assert client.get(f"/v1/documents/{document_id}", headers=ALICE).status_code == 200
    assert client.get("/v1/applications", headers=ALICE).json()["items"]
    assert client.get("/v1/settings", headers=ALICE).json()["resume_defaults"] == {"template": "modern"}
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(ids["alice"])})
        for table in ("profile_items", "profile_imports", "profile_versions", "uploads"):
            assert db.execute(text(f"SELECT count(*) FROM {table} WHERE user_id=:uid"), {"uid": ids["alice"]}).scalar_one() == 0
    response = client.request("DELETE", "/v1/profile/data", headers=ALICE, json={"confirmation": "DELETE", "delete_settings": True})
    assert response.status_code in (200, 204), response.text
    assert client.get("/v1/settings", headers=ALICE).json()["resume_defaults"] == {}


def test_points_enforce_five_wordings_without_losing_previous_text(isolated_users):
    item = create_item()
    response = client.post(f"/v1/profile/items/{item['id']}/bullets", headers=ALICE, json={"text": "Main wording", "expected_revision": item["revision"]})
    assert response.status_code == 200, response.text
    item = response.json()
    bullet_id = item["data"]["bullets"][0]["id"]
    for index in range(4):
        response = client.post(f"/v1/profile/items/{item['id']}/bullets/{bullet_id}/alternatives", headers=ALICE, json={"text": f"Alternative {index}", "expected_revision": item["revision"]})
        assert response.status_code == 200, response.text
        item = response.json()
    revision = bank()["bank_revision"]
    for method, path in (("POST", "alternatives"), ("PUT", "")):
        url = f"/v1/profile/items/{item['id']}/bullets/{bullet_id}" + (f"/{path}" if path else "")
        response = client.request(method, url, headers=ALICE, json={"text": "Overflow wording", "expected_revision": item["revision"]})
        assert response.status_code == 422, response.text
        assert "5" in response.json()["error"]["message"]
    assert bank()["bank_revision"] == revision
    saved = client.get(f"/v1/profile/items/{item['id']}", headers=ALICE).json()
    assert saved["data"]["bullets"][0]["text"] == "Main wording"
    assert len(saved["data"]["bullets"][0]["alternatives"]) == 4


def test_composite_parent_owner_fk_rejects_foreign_item_even_without_api(isolated_users):
    from job_hunter.adapters.database import engine
    from sqlalchemy.exc import IntegrityError
    _, ids = isolated_users
    item = create_item()
    with pytest.raises(IntegrityError):
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(ids["casey"])})
            connection.execute(text("INSERT INTO profile_items (id,user_id,kind,data,parent_id) VALUES (:id,:uid,'project','{\"name\":\"Foreign project\"}',:parent)"), {"id": uuid4(), "uid": ids["casey"], "parent": item["id"]})


def test_recommendations_route_preserves_legacy_order_and_reasons_after_migration(isolated_users):
    from copy import deepcopy
    from job_hunter.api.main import job_out
    from job_hunter.demo import LEGACY_PROFILE
    from datetime import timedelta
    from job_hunter.domain.models import Job, ProfileItem, listed_jobs, now_utc
    from job_hunter.profile_bank.migration import migrate_legacy_profile
    from job_hunter.recommendations import rank_jobs
    engine, ids = isolated_users
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(ids["alice"])})
        # the jobs the route lists: open, unexpired, not a duplicate, posted in the past year (its default)
        jobs = [job_out(job) for job in db.query(Job).filter(listed_jobs(posted_after=now_utc() - timedelta(days=365)))]
        before = rank_jobs(jobs, deepcopy(LEGACY_PROFILE), {})
        basics, items = migrate_legacy_profile(LEGACY_PROFILE, ids["alice"])
        db.get(Profile, ids["alice"]).draft = basics
        for item in items:
            db.add(ProfileItem(**item, user_id=ids["alice"]))
    response = client.get("/v1/recommendations?limit=100", headers=ALICE)
    assert response.status_code == 200, response.text
    after = response.json()["items"]
    assert [(row["job"]["id"], row["reason"], row["evidence"], row["score"]) for row in after] == [
        (row["job"]["id"], row["reason"], row["evidence"], row["score"]) for row in before[:100]
    ]


def test_item_limit_is_per_kind_and_archiving_frees_capacity(isolated_users):
    first = None
    for index in range(50):
        response = client.post("/v1/profile/items", headers=ALICE, json={
            "kind": "custom", "data": {"title": f"Fictional item {index}", "bullets": []},
        })
        assert response.status_code == 201, response.text
        first = first or response.json()
    before = bank()["bank_revision"]
    overflow = client.post("/v1/profile/items", headers=ALICE, json={"kind": "custom", "data": {"title": "Overflow"}})
    assert overflow.status_code == 422, overflow.text
    assert overflow.json()["error"]["code"] == "PROFILE_ITEM_LIMIT"
    assert bank()["bank_revision"] == before
    assert len(bank()["items"]) == 50
    assert create_item()["kind"] == "experience"
    assert client.delete(f"/v1/profile/items/{first['id']}", headers=ALICE).status_code in (200, 204)
    replacement = client.post("/v1/profile/items", headers=ALICE, json={"kind": "custom", "data": {"title": "Replacement"}})
    assert replacement.status_code == 201, replacement.text
    assert sum(item["kind"] == "custom" for item in bank()["items"]) == 50


def test_settings_reject_invalid_style_and_body_identity(isolated_users):
    _, ids = isolated_users
    before = bank()["bank_revision"]
    bad_style = client.put("/v1/settings", headers=ALICE, json={
        "expected_revision": 0, "resume_defaults": {"layout": {"heading_style": "unknown-style"}},
    })
    assert bad_style.status_code == 422, bad_style.text
    foreign_identity = client.put("/v1/settings", headers=CASEY, json={
        "expected_revision": 0, "user_id": str(ids["alice"]), "resume_defaults": {"template": "modern"},
    })
    assert foreign_identity.status_code == 422, foreign_identity.text
    assert client.get("/v1/settings", headers=ALICE).json() == {"resume_defaults": {}, "revision": 0}
    assert client.get("/v1/settings", headers=CASEY).json() == {"resume_defaults": {}, "revision": 0}
    assert bank()["bank_revision"] == before


def test_export_route_is_tenant_scoped_and_preserves_extra_metadata(isolated_users):
    item = create_item('Alice export only')
    point = client.post(f"/v1/profile/items/{item['id']}/bullets", headers=ALICE,
                        json={'expected_revision': 1, 'text': 'Built fictional APIs', 'tags': ['backend']}).json()
    bullet_id = point['data']['bullets'][0]['id']
    version = client.post(f"/v1/profile/items/{item['id']}/bullets/{bullet_id}/alternatives", headers=ALICE,
                          json={'expected_revision': point['revision'], 'text': 'Released services safely', 'tags': ['leadership']})
    assert version.status_code == 200, version.text
    response = client.get('/v1/profile/export.json', headers=ALICE)
    assert response.status_code == 200, response.text
    assert 'profile.json' in response.headers['content-disposition']
    exported = response.json()
    assert exported['work'][0]['position'] == 'Alice export only'
    assert exported['work'][0]['highlights'] == ['Built fictional APIs']
    extra = exported['meta']['jobHunter']['items'][0]
    assert extra['data']['bullets'][0]['alternatives'][0]['text'] == 'Released services safely'
    assert extra['data']['bullets'][0]['tags'] == ['backend']
    casey = client.get('/v1/profile/export.json', headers=CASEY)
    assert casey.status_code == 200
    assert casey.json()['work'] == []
    assert casey.json()['meta']['jobHunter']['items'] == []
    assert 'Alice export only' not in casey.text


def test_archive_undo_restores_active_item_and_checks_revision(isolated_users):
    item = create_item('Undo archive')
    archived = client.delete(f"/v1/profile/items/{item['id']}", headers=ALICE,
                             params={'expected_revision': item['revision']})
    assert archived.status_code == 200, archived.text
    assert bank()['items'] == []
    archived_item = archived.json()
    before_revision = bank()['bank_revision']
    body = {'expected_revision': archived_item['revision'], 'data': item['data'], 'tags': item['tags']}
    foreign = client.post(f"/v1/profile/items/{item['id']}/revert", headers=CASEY, json=body)
    assert foreign.status_code == 404, foreign.text
    restored = client.post(f"/v1/profile/items/{item['id']}/revert", headers=ALICE, json=body)
    assert restored.status_code == 200, restored.text
    assert restored.json()['archived_at'] is None
    assert restored.json()['revision'] == archived_item['revision'] + 1
    assert bank()['bank_revision'] == before_revision + 1
    assert len(bank()['items']) == 1
    assert_conflict(client.post(f"/v1/profile/items/{item['id']}/revert", headers=ALICE, json=body))


def test_archive_undo_rejects_duplicate_skill(isolated_users):
    payload = {'kind': 'skill', 'data': {'name': 'Python', 'category': 'language'}}
    item = client.post('/v1/profile/items', headers=ALICE, json=payload).json()
    archived = client.delete(f"/v1/profile/items/{item['id']}", headers=ALICE,
                             params={'expected_revision': item['revision']}).json()
    assert client.post('/v1/profile/items', headers=ALICE, json=payload).status_code == 201
    response = client.post(f"/v1/profile/items/{item['id']}/revert", headers=ALICE,
                           json={'expected_revision': archived['revision'], 'data': item['data']})
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'DUPLICATE_SKILL'
    assert len(bank()['items']) == 1


def test_make_main_swaps_versions_at_limit_with_provenance(isolated_users):
    source = {'origin': 'import', 'import_id': 'fictional-import',
              'evidence': {'source_sha256': 'a' * 64, 'page': 1, 'text': 'Original source'}}
    response = client.post('/v1/profile/items', headers=ALICE, json={
        'kind': 'experience', 'data': {'title': 'Engineer', 'bullets': [{
            'id': 'b_main', 'text': 'Original main', 'tags': ['backend'], 'provenance': source,
            'alternatives': [{'id': f'v_{i}', 'text': f'Alternative {i}', 'tags': ['data']}
                             for i in range(4)],
        }]},
    })
    assert response.status_code == 201, response.text
    item = response.json()
    revision = bank()['bank_revision']
    promoted = client.put(f"/v1/profile/items/{item['id']}/bullets/b_main", headers=ALICE, json={
        'expected_revision': item['revision'], 'text': 'Alternative 2',
        'alternative_id': 'v_2', 'make_main': True,
    })
    assert promoted.status_code == 200, promoted.text
    updated = promoted.json()
    point = updated['data']['bullets'][0]
    assert point['id'] == 'b_main' and point['text'] == 'Alternative 2'
    assert point['tags'] == ['data']
    old = next(version for version in point['alternatives'] if version['id'] == 'v_2')
    assert old['text'] == 'Original main' and old['provenance'] == source
    assert len(point['alternatives']) == 4
    assert bank()['bank_revision'] == revision + 1
    undone = client.post(f"/v1/profile/items/{item['id']}/revert", headers=ALICE,
                         json={'expected_revision': updated['revision'], 'data': item['data']})
    assert undone.status_code == 200, undone.text
    assert undone.json()['data']['bullets'][0]['provenance'] == source


def test_archive_undo_respects_active_item_limit(isolated_users):
    item = create_item('Archived first')
    archived = client.delete(f"/v1/profile/items/{item['id']}", headers=ALICE,
                             params={'expected_revision': item['revision']}).json()
    for index in range(50):
        create_item(f'Active item {index}')
    before = bank()['bank_revision']
    response = client.post(f"/v1/profile/items/{item['id']}/revert", headers=ALICE,
                           json={'expected_revision': archived['revision'], 'data': item['data']})
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'PROFILE_ITEM_LIMIT'
    assert len(bank()['items']) == 50
    assert bank()['bank_revision'] == before


def test_uploaded_source_library_and_original_download_are_owned(isolated_users):
    from io import BytesIO
    from reportlab.pdfgen.canvas import Canvas
    output = BytesIO()
    pdf = Canvas(output)
    pdf.drawString(72, 720, 'Fictional source resume for ownership checks')
    pdf.showPage()
    pdf.save()
    data = output.getvalue()
    response = client.post('/v1/uploads', headers=ALICE, json={
        'filename': 'fictional-source.pdf', 'content_type': 'application/pdf', 'size_bytes': len(data),
    })
    assert response.status_code == 201, response.text
    upload = response.json()
    assert client.put(upload['upload_url'], headers={**ALICE, 'Content-Type': 'application/pdf'}, content=data).status_code == 200
    own = client.get('/v1/uploads', headers=ALICE)
    assert own.status_code == 200
    assert [row['upload_id'] for row in own.json()['items']] == [upload['upload_id']]
    assert client.get('/v1/uploads', headers=CASEY).json()['items'] == []
    path = f"/v1/uploads/{upload['upload_id']}/download"
    downloaded = client.get(path, headers=ALICE)
    assert downloaded.status_code == 200 and downloaded.content == data
    assert client.get(path, headers=CASEY).status_code == 404

    # Rename is a display label only: owner-scoped, keeps the extension, strips paths, and names the download.
    rename = f"/v1/uploads/{upload['upload_id']}"
    assert client.patch(rename, headers=CASEY, json={'filename': 'stolen'}).status_code == 404
    renamed = client.patch(rename, headers=ALICE, json={'filename': '../Backend roles – Nov'})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()['filename'] == 'Backend roles – Nov.pdf' and renamed.json()['created_at']
    assert client.get('/v1/uploads', headers=ALICE).json()['items'][0]['filename'] == 'Backend roles – Nov.pdf'
    assert client.patch(rename, headers=ALICE, json={'filename': '  .pdf'}).status_code == 422
    assert client.get(path, headers=ALICE).headers['content-disposition'] == 'attachment; filename="Backend roles _ Nov.pdf"'


def full_point():
    item = client.post('/v1/profile/items', headers=ALICE, json={
        'kind': 'experience', 'data': {'title': 'Engineer', 'bullets': [{
            'id': 'b_main', 'text': 'Main wording',
            'alternatives': [{'id': f'v_{i}', 'text': f'Alternative {i}'} for i in range(4)]}]}})
    assert item.status_code == 201, item.text
    return item.json()


def test_replace_alternative_drops_chosen_and_adds_new_in_one_revision(isolated_users):
    item = full_point()
    url = f"/v1/profile/items/{item['id']}/bullets/b_main"
    response = client.post(f"{url}/alternatives", headers=ALICE, json={
        'expected_revision': item['revision'], 'text': 'Fresh wording', 'replace_alternative_id': 'v_1'})
    assert response.status_code == 200, response.text
    saved = response.json()
    texts = [version['text'] for version in saved['data']['bullets'][0]['alternatives']]
    assert saved['revision'] == item['revision'] + 1
    assert 'Alternative 1' not in texts and 'Fresh wording' in texts and len(texts) == 4
    assert saved['data']['bullets'][0]['text'] == 'Main wording'
    assert 'replace_alternative_id' not in saved['data']['bullets'][0]['alternatives'][-1]


def test_update_with_replace_keeps_old_wording_and_drops_chosen(isolated_users):
    item = full_point()
    response = client.put(f"/v1/profile/items/{item['id']}/bullets/b_main", headers=ALICE, json={
        'expected_revision': item['revision'], 'text': 'Better main', 'replace_alternative_id': 'v_0'})
    assert response.status_code == 200, response.text
    point = response.json()['data']['bullets'][0]
    texts = [version['text'] for version in point['alternatives']]
    assert point['text'] == 'Better main' and 'Main wording' in texts and 'Alternative 0' not in texts and len(texts) == 4


def test_update_keep_previous_false_needs_no_room_and_keeps_nothing(isolated_users):
    item = full_point()
    response = client.put(f"/v1/profile/items/{item['id']}/bullets/b_main", headers=ALICE, json={
        'expected_revision': item['revision'], 'text': 'Replacement', 'keep_previous': False})
    assert response.status_code == 200, response.text
    point = response.json()['data']['bullets'][0]
    assert point['text'] == 'Replacement' and len(point['alternatives']) == 4
    assert 'Main wording' not in [version['text'] for version in point['alternatives']]
    alt = client.put(f"/v1/profile/items/{item['id']}/bullets/b_main", headers=ALICE, json={
        'expected_revision': response.json()['revision'], 'text': 'Edited alt', 'alternative_id': 'v_3', 'keep_previous': False})
    assert alt.status_code == 200, alt.text
    versions = {version['id']: version['text'] for version in alt.json()['data']['bullets'][0]['alternatives']}
    assert versions['v_3'] == 'Edited alt' and len(versions) == 4


def test_main_wording_and_unknown_versions_cannot_be_replaced(isolated_users):
    item = full_point()
    url = f"/v1/profile/items/{item['id']}/bullets/b_main"
    revision = bank()['bank_revision']
    for path, method in (('/alternatives', 'POST'), ('', 'PUT')):
        for bad in ('b_main', 'v_missing'):
            response = client.request(method, url + path, headers=ALICE, json={
                'expected_revision': item['revision'], 'text': 'X', 'replace_alternative_id': bad})
            assert response.status_code == 422, response.text
    assert client.put(url, headers=ALICE, json={'expected_revision': item['revision'], 'text': 'X',
                                                  'alternative_id': 'v_2', 'replace_alternative_id': 'v_2'}).status_code == 422
    assert bank()['bank_revision'] == revision


def test_replace_alternative_stale_revision_and_foreign_item(isolated_users):
    item = full_point()
    url = f"/v1/profile/items/{item['id']}/bullets/b_main/alternatives"
    stale = client.post(url, headers=ALICE, json={'expected_revision': item['revision'] + 5, 'text': 'X', 'replace_alternative_id': 'v_1'})
    assert stale.status_code == 409, stale.text
    foreign = client.post(url, headers=CASEY, json={'expected_revision': item['revision'], 'text': 'X', 'replace_alternative_id': 'v_1'})
    assert foreign.status_code == 404, foreign.text
    assert len(client.get(f"/v1/profile/items/{item['id']}", headers=ALICE).json()['data']['bullets'][0]['alternatives']) == 4
