from fastapi.testclient import TestClient
from job_hunter.api.main import app, inspect_pdf, pdf_bytes, validate_document
from job_hunter.domain.models import Document
from fastapi import HTTPException
import pytest
from io import BytesIO
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader, PdfWriter

client = TestClient(app)

def test_health_is_public():
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_dev_identity_is_allowlisted():
    response = client.get("/v1/me", headers={"X-Dev-User": "mallory"})
    assert response.status_code == 401

def test_resume_layout_is_bounded():
    validate_document("modern", {"sections": []}, {"font_size": 11, "margin": 18})
    with pytest.raises(HTTPException) as exc:
        validate_document("modern", {"sections": []}, {"font_size": 2, "margin": 18})
    assert exc.value.status_code == 422

def test_resume_content_is_bounded():
    with pytest.raises(HTTPException):
        validate_document("classic", {"sections": [{"entries": [{"bullets": ["x" * 4001]}]}]}, {})

def make_pdf(text=None, pages=1):
    output = BytesIO()
    canvas = Canvas(output)
    for index in range(pages):
        if text and index == 0:
            canvas.drawString(72, 720, text)
        canvas.showPage()
    canvas.save()
    return output.getvalue()

def test_pdf_parser_returns_candidate_text_without_structuring_facts():
    result = inspect_pdf(make_pdf("Avery Example - data engineer"))
    assert result["status"] == "ready_for_review"
    assert result["page_count"] == 1
    assert "Avery Example" in result["text"]

def test_pdf_parser_flags_scanned_like_empty_document():
    result = inspect_pdf(make_pdf())
    assert result["status"] == "ocr_required"
    assert result["error_code"] == "OCR_REQUIRED"

def test_pdf_parser_rejects_over_limit_and_corrupt_documents():
    assert inspect_pdf(make_pdf("ok", pages=21))["error_code"] == "PAGE_LIMIT_EXCEEDED"
    assert inspect_pdf(b"%PDF-not a valid document")["error_code"] == "INVALID_OR_CORRUPT_PDF"

def test_pdf_parser_rejects_encrypted_document():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("password")
    data = BytesIO()
    writer.write(data)
    assert inspect_pdf(data.getvalue())["error_code"] == "ENCRYPTED_PDF"

@pytest.mark.parametrize("template", ["classic", "modern"])
def test_resume_renderer_keeps_bold_text_accented_names_and_long_content(template):
    bullet = "Built and maintained dependable services for a regional product team. " * 12
    document = Document(title="Resume", template=template, layout={"font_size": 11, "margin": 18},
        content={"name": "André Example", "email": "andre@example.test", "sections": [{
            "title": "Experience", "entries": [{"heading": "Backend Engineer", "subheading": "Example Ltd",
                "dates": "2020–2026", "bullets": [bullet for _ in range(36)]}]}]})
    rendered = pdf_bytes(document)
    pages = PdfReader(BytesIO(rendered)).pages
    extracted = "\n".join(page.extract_text() or "" for page in pages)
    assert len(pages) > 1
    assert "André Example" in extracted
    assert "Backend Engineer" in extracted
    assert "regional product team" in extracted
