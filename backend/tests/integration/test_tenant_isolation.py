"""Run against a migrated PostgreSQL DB seeded with Alice and Bob."""
import os
from io import BytesIO
import pytest
from reportlab.pdfgen.canvas import Canvas
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                                reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")

from fastapi.testclient import TestClient
from job_hunter.api.main import app

client = TestClient(app)

def test_document_is_invisible_to_other_local_identity():
    headers_alice = {"X-Dev-User": "alice"}
    headers_bob = {"X-Dev-User": "bob"}
    created = client.post("/v1/documents", headers=headers_alice, json={
        "title": "Tenant isolation test", "template": "classic",
        "content": {"name": "Alice", "sections": []},
        "layout": {"font_size": 11, "margin": 18},
    })
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert client.get(f"/v1/documents/{document_id}", headers=headers_alice).status_code == 200
    assert client.get(f"/v1/documents/{document_id}", headers=headers_bob).status_code == 404
    assert all(row["id"] != document_id for row in client.get("/v1/documents", headers=headers_bob).json()["items"])

def test_recommendations_support_server_side_search_and_offset_pages():
    headers = {"X-Dev-User": "alice"}
    first = client.get("/v1/recommendations?limit=1&offset=0", headers=headers)
    assert first.status_code == 200
    page = first.json()
    assert page["ranking_version"] == "local_tfidf_hybrid_v1"
    assert page["items"][0]["score_label"] == "relevance score (not probability)"
    assert page["total"] >= 2
    assert len(page["items"]) == 1
    assert page["next_offset"] == 1
    second = client.get("/v1/recommendations?limit=1&offset=1", headers=headers).json()
    assert second["items"][0]["job"]["id"] != page["items"][0]["job"]["id"]
    searched = client.get("/v1/recommendations?q=backend%20engineer", headers=headers).json()
    assert searched["items"]
    assert any("backend engineer" in " ".join(str(row["job"].get(k) or "") for k in ("title", "company", "description", "location", "category")).lower()
               for row in searched["items"])

def test_runtime_role_rls_fails_closed_and_switches_tenant_context():
    from job_hunter.adapters.database import engine
    created = client.post("/v1/documents", headers={"X-Dev-User": "alice"}, json={
        "title": "RLS context test", "template": "classic",
        "content": {"name": "Alice", "sections": []},
        "layout": {"font_size": 11, "margin": 18},
    })
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    alice_id = "00000000-0000-4000-8000-000000000001"
    bob_id = "00000000-0000-4000-8000-000000000002"
    with engine.connect() as connection:
        with connection.begin():
            assert connection.execute(text("SELECT count(*) FROM documents WHERE id=:id"), {"id": document_id}).scalar_one() == 0
            connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": alice_id})
            assert connection.execute(text("SELECT count(*) FROM documents WHERE id=:id"), {"id": document_id}).scalar_one() == 1
            connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": bob_id})
            assert connection.execute(text("SELECT count(*) FROM documents WHERE id=:id"), {"id": document_id}).scalar_one() == 0

def test_pdf_upload_extracts_review_text_and_freezes_the_captured_bytes():
    buffer = BytesIO()
    pdf = Canvas(buffer)
    pdf.drawString(72, 720, "Jordan Tan - Product Designer")
    pdf.showPage()
    pdf.save()
    data = buffer.getvalue()
    alice = {"X-Dev-User": "alice"}
    initiated = client.post("/v1/uploads", headers=alice, json={
        "filename": "resume.pdf", "content_type": "application/pdf", "size_bytes": len(data),
    })
    assert initiated.status_code == 201, initiated.text
    upload_id = initiated.json()["upload_id"]
    captured = client.put(initiated.json()["upload_url"], headers={**alice, "Content-Type": "application/pdf"}, content=data)
    assert captured.status_code == 200, captured.text
    assert captured.json()["status"] == "ready_for_review"
    reviewed_candidate = client.get(f"/v1/uploads/{upload_id}", headers=alice)
    assert reviewed_candidate.status_code == 200
    assert "Jordan Tan" in reviewed_candidate.json()["extracted_text"]
    replay = client.put(initiated.json()["upload_url"], headers={**alice, "Content-Type": "application/pdf"}, content=data)
    assert replay.status_code == 409
    assert client.get(f"/v1/uploads/{upload_id}", headers={"X-Dev-User": "bob"}).status_code == 404

def test_application_packet_snapshots_reviewed_resume_and_cover_letter():
    alice = {"X-Dev-User": "alice"}
    bob = {"X-Dev-User": "bob"}
    from sqlalchemy import create_engine
    from job_hunter.config import settings
    from job_hunter.domain.models import Job
    owner_engine = create_engine(settings.migration_database_url)
    test_job_id, resume_id, export_id = uuid4(), None, None
    with Session(owner_engine) as db:
        with db.begin():
            db.add(Job(id=test_job_id, title="Packet regression role", company="Test Employer",
                       location="Singapore", work_mode="onsite", description="Synthetic isolated test job",
                       url="https://example.test/packet-regression", source="packet-test", status="open"))
    try:
        alice_job_id = str(test_job_id)
        job = client.get(f"/v1/jobs/{alice_job_id}", headers=alice).json()
        resume = client.post("/v1/documents", headers=alice, json={
            "title": "Resume April", "template": "classic",
            "content": {"name": "Jordan Original", "sections": []},
            "layout": {"font_size": 11, "margin": 18},
        })
        assert resume.status_code == 201, resume.text
        resume_id = resume.json()["id"]
        reviewed = client.post(f"/v1/documents/{resume_id}/review", headers=alice,
                               json={"expected_revision": 1})
        assert reviewed.status_code == 200

        attached = client.put(f"/v1/applications/{job['id']}", headers=alice, json={
            "expected_revision": 0, "resume_document_id": resume_id,
            "expected_resume_revision": 1,
            "cover_letter_text": "Dear hiring team, I would like to apply.",
        })
        assert attached.status_code == 200, attached.text
        packet = attached.json()["resume_packet"]
        assert packet["title"] == "Resume April" and packet["revision"] == 1
        assert attached.json()["cover_letter_text"].startswith("Dear hiring team")
        assert attached.json()["packet_updated_at"]
        export_id = packet["export_id"]

        downloaded = client.get(packet["download_url"], headers=alice)
        assert downloaded.status_code == 200
        from pypdf import PdfReader
        from io import BytesIO
        original_pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(downloaded.content)).pages)
        assert "Jordan Original" in original_pdf_text

        changed = client.patch(f"/v1/documents/{resume_id}", headers=alice, json={
            "expected_revision": 1, "title": "Resume May",
            "content": {"name": "Jordan Revised", "sections": []},
        })
        assert changed.status_code == 200
        saved_application = client.get("/v1/applications", headers=alice).json()["items"]
        saved_packet = next(row for row in saved_application if row["job_id"] == alice_job_id)["resume_packet"]
        assert saved_packet["title"] == "Resume April"
        assert saved_packet["revision"] == 1
        still_original = client.get(saved_packet["download_url"], headers=alice)
        revised_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(still_original.content)).pages)
        assert "Jordan Original" in revised_text and "Jordan Revised" not in revised_text

        letter_update = client.put(f"/v1/applications/{job['id']}", headers=alice, json={
            "expected_revision": attached.json()["revision"],
            "cover_letter_text": "Updated manually for this application.",
        })
        assert letter_update.status_code == 200
        assert letter_update.json()["resume_packet"]["export_id"] == export_id
        assert letter_update.json()["cover_letter_text"] == "Updated manually for this application."
        reused_export = client.put(f"/v1/applications/{job['id']}", headers=alice, json={
            "expected_revision": letter_update.json()["revision"], "resume_export_id": export_id,
        })
        assert reused_export.status_code == 200
        assert reused_export.json()["resume_packet"]["export_id"] == export_id
        assert client.put(f"/v1/applications/{job['id']}", headers=alice, json={
            "expected_revision": attached.json()["revision"], "cover_letter_text": "stale"
        }).status_code == 409

        cleared = client.put(f"/v1/applications/{job['id']}", headers=alice, json={
            "expected_revision": reused_export.json()["revision"],
            "resume_export_id": None, "cover_letter_text": None,
        })
        assert cleared.status_code == 200
        assert cleared.json()["resume_packet"] is None
        assert cleared.json()["cover_letter_text"] is None

        foreign_attach = client.put(f"/v1/applications/{job['id']}", headers=bob, json={
            "expected_revision": 0, "resume_export_id": export_id,
        })
        assert foreign_attach.status_code == 404
        assert client.get(f"/v1/exports/{export_id}", headers=bob).status_code == 404
    finally:
        from pathlib import Path
        with Session(owner_engine) as db:
            with db.begin():
                db.execute(text("SELECT set_config('app.user_id', :user_id, true)"),
                           {"user_id": "00000000-0000-4000-8000-000000000001"})
                paths = db.execute(text("SELECT file_path FROM document_exports WHERE user_id=:uid AND document_id=:did"),
                                   {"uid": "00000000-0000-4000-8000-000000000001", "did": resume_id}).scalars().all() if resume_id else []
                db.execute(text("DELETE FROM applications WHERE user_id=:uid AND job_id=:jid"),
                           {"uid": "00000000-0000-4000-8000-000000000001", "jid": test_job_id})
                if resume_id:
                    db.execute(text("DELETE FROM document_exports WHERE user_id=:uid AND document_id=:did"),
                               {"uid": "00000000-0000-4000-8000-000000000001", "did": resume_id})
                    db.execute(text("DELETE FROM documents WHERE user_id=:uid AND id=:did"),
                               {"uid": "00000000-0000-4000-8000-000000000001", "did": resume_id})
                db.execute(text("DELETE FROM jobs WHERE id=:jid"), {"jid": test_job_id})
        for path in paths:
            Path(path).unlink(missing_ok=True)
        owner_engine.dispose()


def test_new_resume_can_keep_its_preparation_job_context():
    from job_hunter.adapters.database import engine
    with engine.connect() as connection:
        job_id = str(connection.execute(text("SELECT id FROM jobs LIMIT 1")).scalar_one())
    created = client.post('/v1/documents', headers={'X-Dev-User': 'alice'}, json={
        'title': 'Synthetic preparation context test', 'template': 'classic',
        'job_id': job_id, 'content': {'name': 'Example', 'sections': []},
        'layout': {'font_size': 11, 'margin': 18},
    })
    assert created.status_code == 201, created.text
    assert created.json()['job_id'] == job_id
    loaded = client.get('/v1/documents/' + created.json()['id'], headers={'X-Dev-User': 'alice'})
    assert loaded.json()['job_id'] == job_id
