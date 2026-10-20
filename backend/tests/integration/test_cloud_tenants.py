"""Verify new-user bootstrap under the real non-owner runtime role and RLS."""
from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from starlette.requests import Request

from job_hunter.adapters.auth import CloudIdentity
from job_hunter.adapters.database import get_db
from job_hunter.api.main import app, identity
from job_hunter.adapters import storage
from job_hunter.config import settings

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1", reason="requires PostgreSQL")


def test_new_cloud_users_bootstrap_concurrently_and_remain_isolated():
    alice = CloudIdentity(uuid4(), str(uuid4()), "New user A")
    bob = CloudIdentity(uuid4(), str(uuid4()), "New user B")
    def open_session(_):
        session = get_db(alice)
        db = next(session)
        result = db.info["current_user"].id
        try:
            next(session)
        except StopIteration:
            pass
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(open_session, range(3))) == [alice.user_id] * 3
    client = TestClient(app)
    try:
        app.dependency_overrides[identity] = lambda: alice
        assert client.get("/v1/me").json()["user_id"] == str(alice.user_id)
        assert client.get("/v1/profile").status_code == 200
        created = client.post("/v1/documents", json={"title": "Cloud tenant test", "template": "classic",
                             "content": {"name": "A", "sections": []}, "layout": {"font_size": 11, "margin": 18}})
        assert created.status_code == 201, created.text
        identifier = created.json()["id"]
        app.dependency_overrides[identity] = lambda: bob
        assert client.get("/v1/me", headers={"X-Dev-User": "alice"}).json()["user_id"] == str(bob.user_id)
        assert client.get(f"/v1/documents/{identifier}").status_code == 404
        assert client.patch(f"/v1/documents/{identifier}", json={"title": "stolen", "expected_revision": 1}).status_code == 404
    finally:
        app.dependency_overrides.pop(identity, None)
        for user in (alice, bob):
            session = get_db(user)
            db = next(session)
            # Keep cleanup tenant scoped and use the same runtime role.
            db.execute(text("DELETE FROM documents WHERE user_id=:id"), {"id": user.user_id})
            db.execute(text("DELETE FROM profiles WHERE user_id=:id"), {"id": user.user_id})
            db.execute(text("DELETE FROM users WHERE id=:id"), {"id": user.user_id})
            try:
                next(session)
            except StopIteration:
                pass


def test_cloud_finalize_checks_owner_and_freezes_once(monkeypatch):
    from io import BytesIO
    from reportlab.pdfgen.canvas import Canvas
    from job_hunter.domain.models import Upload
    from uuid import UUID
    buffer = BytesIO()
    canvas = Canvas(buffer)
    canvas.drawString(72, 720, "Fictional cloud upload")
    canvas.save()
    data = buffer.getvalue()
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "document_bucket", "test-documents")
    monkeypatch.setattr(storage, "upload_url", lambda *_: "https://example.test/signed-put")
    captures = []
    def capture(ref, size):
        captures.append((ref, size))
        return ref + "?versionId=immutable-v1", data
    monkeypatch.setattr(storage, "capture", capture)
    client = TestClient(app)
    created = client.post("/v1/uploads", headers={"X-Dev-User": "alice"}, json={
        "filename": "resume.pdf", "content_type": "application/pdf", "size_bytes": len(data)})
    assert created.status_code == 201, created.text
    upload_id = created.json()["upload_id"]
    try:
        url = created.json()["finalize_url"]
        assert client.post(url, headers={"X-Dev-User": "casey"}).status_code == 404
        assert captures == []
        assert client.post(url, headers={"X-Dev-User": "alice"}).status_code == 200
        monkeypatch.setattr(storage, "download_url", lambda *_: "https://documents.example.test/signed")
        download = f"/v1/uploads/{upload_id}/download"
        response = client.get(download, headers={"X-Dev-User": "alice"})
        assert response.status_code == 200
        assert response.json() == {"url": "https://documents.example.test/signed"}
        assert response.headers["cache-control"] == "no-store"
        assert "location" not in response.headers
        assert client.get(download, headers={"X-Dev-User": "casey"}).status_code == 404
        assert client.post(url, headers={"X-Dev-User": "alice"}).status_code == 409
        assert len(captures) == 1
        session = get_db("alice")
        db = next(session)
        assert db.get(Upload, UUID(upload_id)).file_path.endswith("?versionId=immutable-v1")
        try:
            next(session)
        except StopIteration:
            pass
    finally:
        session = get_db("alice")
        db = next(session)
        db.execute(text("DELETE FROM uploads WHERE id=:id"), {"id": upload_id})
        try:
            next(session)
        except StopIteration:
            pass
