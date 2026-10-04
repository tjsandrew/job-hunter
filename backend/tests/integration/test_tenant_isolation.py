"""Run against a migrated PostgreSQL DB seeded with Alice and Bob."""
import os
from io import BytesIO
import pytest
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import text

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
