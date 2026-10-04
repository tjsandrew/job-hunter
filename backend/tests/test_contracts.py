from fastapi.testclient import TestClient
from job_hunter.api.main import app, inspect_pdf, pdf_bytes, validate_document
from job_hunter.domain.models import Document
from job_hunter.api.main import ApplicationWrite
from pydantic import ValidationError
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

def test_application_cover_letter_has_a_bounded_length():
    with pytest.raises(ValidationError):
        ApplicationWrite(status="applied", cover_letter_text="x" * 20001)

def make_resume_document(template="classic", **layout):
    return Document(title="Layout test", template=template,
        layout={"font_size": 11, "margin": 18, "font_family": "auto", "line_spacing": 1.25,
                "page_size": "A4", **layout},
        content={"name": "Avery Example", "sections": [{"title": "Experience", "entries": [
            {"heading": "Engineer", "subheading": "Example Co", "dates": "2022–2026",
             "bullets": ["Designed reliable systems for a regional team."]}
        ]}]})

def pdf_font_names(data):
    page = PdfReader(BytesIO(data)).pages[0]
    fonts = page["/Resources"].get_object()["/Font"].get_object().values()
    return {str(font.get_object().get("/BaseFont")) for font in fonts}

@pytest.mark.parametrize("family,expected", [
    ("serif", "Times-Roman"),
    ("sans", "BitstreamVeraSans-Roman"),
    ("mono", "Courier"),
])
def test_pdf_renderer_embeds_selected_font_family(family, expected):
    data = pdf_bytes(make_resume_document(font_family=family))
    assert any(expected in name for name in pdf_font_names(data))

def test_auto_font_family_follows_template_and_page_size_is_rendered():
    classic = pdf_bytes(make_resume_document("classic", page_size="letter"))
    modern = pdf_bytes(make_resume_document("modern"))
    classic_page = PdfReader(BytesIO(classic)).pages[0]
    modern_page = PdfReader(BytesIO(modern)).pages[0]
    assert any("Times-Roman" in name for name in pdf_font_names(classic))
    assert any("BitstreamVeraSans-Roman" in name for name in pdf_font_names(modern))
    assert round(float(classic_page.mediabox.width)) == 612
    assert round(float(classic_page.mediabox.height)) == 792
    assert round(float(modern_page.mediabox.height)) == 842

def test_line_spacing_changes_pdf_flow_and_multipage_layout():
    sections = [{"title": "Experience", "entries": [{
        "heading": f"Role {index}", "subheading": "Regional Services", "dates": "2020–2026",
        "bullets": ["Built dependable services used by teams across Asia Pacific. " * 6],
    } for index in range(32)]}]
    content = {"name": "Avery Example", "sections": sections}
    tight = pdf_bytes(Document(title="Spacing", template="modern", content=content,
        layout={"font_size": 11, "margin": 18, "line_spacing": 1.0, "font_family": "sans", "page_size": "A4"}))
    loose = pdf_bytes(Document(title="Spacing", template="modern", content=content,
        layout={"font_size": 11, "margin": 18, "line_spacing": 1.8, "font_family": "sans", "page_size": "A4"}))
    tight_pages = len(PdfReader(BytesIO(tight)).pages)
    loose_pages = len(PdfReader(BytesIO(loose)).pages)
    assert tight_pages > 1
    assert loose_pages > tight_pages

@pytest.mark.parametrize("layout", [
    {"font_family": "comic"}, {"font_family": []}, {"font_size": True},
    {"font_size": float("nan")}, {"margin": float("inf")},
    {"line_spacing": False}, {"line_spacing": 0.9}, {"line_spacing": 1.81},
    {"line_spacing": float("nan")}, {"page_size": []},
])
def test_layout_rejects_invalid_families_types_and_numeric_ranges(layout):
    with pytest.raises(HTTPException) as exc:
        validate_document("classic", {"sections": []}, {"font_size": 11, "margin": 18, **layout})
    assert exc.value.status_code == 422
