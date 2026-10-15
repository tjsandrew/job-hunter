"""The PDF renderer honours the resume style settings and leaves older resumes unchanged."""
import hashlib
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from reportlab import rl_config

from job_hunter.demo import CONTENT as DEMO_CONTENT
from job_hunter.preparation.rendering import pdf_bytes

LEGACY_CONTENT = {
    "name": "Alex Tan & Co", "email": "alex@example.com", "phone": "+65 5550 0100", "location": "Singapore",
    "summary": "Backend engineer <b>with</b> data focus.",
    "sections": [
        {"id": "s1", "title": "Experience", "entries": [
            {"id": "e1", "heading": "Backend Engineer", "subheading": "Harbour Metrics", "dates": "Jul 2023 – Present",
             "bullets": ["Built FastAPI services", "Cut p95 from 4.2 s to 0.9 s"]},
            {"id": "e2", "heading": "Intern", "subheading": "", "dates": "", "bullets": []}]},
        {"id": "s2", "title": "Skills", "entries": [{"id": "e3", "heading": "", "bullets": ["Languages: Python, SQL"]}]},
    ],
}

# SHA-256 of the PDF bytes (with ReportLab's invariant mode on) produced by the renderer
# before the style settings were added. A change here means older resumes now look different.
LEGACY_GOLDEN = {
    "classic_auto": ("classic", LEGACY_CONTENT, {"font_size": 11, "margin": 18},
                     "5a0739b418b51c3eb678905c175e268bf03b90600ac8d9d50ab0fbf1a0632528"),
    "modern_letter": ("modern", LEGACY_CONTENT, {"font_size": 10, "margin": 20, "page_size": "letter", "line_spacing": 1.4},
                      "3ba36de51aaa2b422b4c10a860a4019b735c43480b247c4186aedf3a819e936c"),
    "classic_latex": ("classic", LEGACY_CONTENT, {"font_family": "latex", "font_size": 11, "margin": 18},
                      "3368a495ba190d75168fcca23383690fa6d6716db0d7b652c4dd2ef0e9231a43"),
    "classic_mono": ("classic", LEGACY_CONTENT, {"font_family": "mono", "font_size": 9, "margin": 12},
                     "faccbf672f7d1d3fda4977ca536c4efa7b3cf86c8ccb503644231c3fb014a623"),
    "demo_classic": ("classic", DEMO_CONTENT, {"font_size": 11, "margin": 18},
                     "8e1c1355d4f12e848b5658c0f39068a2b36347a10b864fe4cc63b046819083e3"),
    "demo_latex": ("modern", DEMO_CONTENT, {"font_family": "latex", "font_size": 11, "margin": 18},
                   "a9bf7ccc29ae6c366e4af73ac1861bd24573f749674b545008cc7d8963269edf"),
}


def render(content, layout=None, template="classic") -> bytes:
    doc = SimpleNamespace(title="Resume", template=template, content=content,
                          layout={"font_size": 11, "margin": 18, **(layout or {})})
    return pdf_bytes(doc)


def text_of(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)


@pytest.fixture
def invariant_pdf():
    previous = rl_config.invariant
    rl_config.invariant = 1
    yield
    rl_config.invariant = previous


@pytest.mark.parametrize("name", LEGACY_GOLDEN)
def test_documents_without_the_new_keys_render_exactly_as_before(invariant_pdf, name):
    template, content, layout, expected = LEGACY_GOLDEN[name]
    doc = SimpleNamespace(title="Resume", template=template, content=deepcopy(content), layout=layout)
    assert hashlib.sha256(pdf_bytes(doc)).hexdigest() == expected


def with_entry(**entry):
    return {**LEGACY_CONTENT, "sections": [{"id": "s", "title": "Experience", "entries": [
        {"id": "e", "heading": "Engineer", "subheading": "Org", "dates": "typed dates", "bullets": ["Did a thing"], **entry}]}]}


def test_hidden_section_is_not_rendered():
    content = deepcopy(LEGACY_CONTENT)
    content["sections"][1]["hidden"] = True
    text = text_of(render(content))
    assert "Experience" in text and "Built FastAPI services" in text
    assert "Skills" not in text and "Languages: Python" not in text
    content["sections"][1]["hidden"] = False
    assert "Skills" in text_of(render(content))


@pytest.mark.parametrize("date_format, expected", [
    ("Jul 2023", "Jul 2023 – Present"), ("July 2023", "July 2023 – Present"),
    ("07/2023", "07/2023 – Present"), ("2023", "2023 – Present")])
def test_date_format_applies_to_entries_with_a_date_range(date_format, expected):
    content = with_entry(date_range={"start": "2023-07", "end": None, "current": True})
    text = text_of(render(content, {"date_format": date_format}))
    assert expected in text
    assert "typed dates" not in text


@pytest.mark.parametrize("label", ["Present", "Current", "Now"])
def test_present_label(label):
    content = with_entry(date_range={"start": "2023-07", "end": None, "current": True})
    assert f"Jul 2023 – {label}" in text_of(render(content, {"present_label": label}))


def test_date_range_without_layout_keys_uses_the_defaults():
    content = with_entry(date_range={"start": "2022-01", "end": "2023-06", "current": False})
    assert "Jan 2022 – Jun 2023" in text_of(render(content))


def test_typed_dates_are_kept_when_there_is_no_date_range():
    text = text_of(render(with_entry(), {"date_format": "07/2023"}))
    assert "typed dates" in text


def test_bullet_characters():
    # The built-in serif font extracts its bullet as a control character, so check with a TrueType font.
    content = with_entry()
    sans = {"font_family": "sans"}
    assert "• Did a thing" in text_of(render(content, sans))
    assert "– Did a thing" in text_of(render(content, {**sans, "bullet_char": "–"}))
    square = render(content, {**sans, "bullet_char": "▪"})
    assert "Did a thing" in text_of(square)
    assert square != render(content, sans)


def test_contact_separators():
    assert "alex@example.com · +65 5550 0100 · Singapore" in text_of(render(LEGACY_CONTENT))
    assert "alex@example.com | +65 5550 0100 | Singapore" in text_of(render(LEGACY_CONTENT, {"contact_separator": "|"}))
    for spelling in ("newline", "new line"):
        lines = text_of(render(LEGACY_CONTENT, {"contact_separator": spelling})).splitlines()
        assert "alex@example.com" in lines and "+65 5550 0100" in lines and "Singapore" in lines


def test_small_caps_headings_are_upper_case():
    text = text_of(render(LEGACY_CONTENT, {"heading_style": "small-caps"}))
    assert "EXPERIENCE" in text.replace(" ", "")


@pytest.mark.parametrize("setting, value", [
    ("heading_style", "rule"), ("heading_style", "bold"), ("heading_style", "small-caps"),
    ("accent_color", "navy"), ("accent_color", "teal"), ("accent_color", "maroon"),
    ("header_align", "left"), ("header_align", "center"),
    ("section_spacing", "compact"), ("section_spacing", "airy")])
def test_style_settings_change_the_output_but_keep_the_text(setting, value):
    baseline = render(LEGACY_CONTENT)
    styled = render(LEGACY_CONTENT, {setting: value})
    assert styled != baseline
    assert "Built FastAPI services" in text_of(styled)


def test_normal_spacing_matches_the_legacy_spacing(invariant_pdf):
    assert render(LEGACY_CONTENT, {"section_spacing": "normal"}) == render(LEGACY_CONTENT)


def skills_content():
    return {"name": "A", "sections": [{"id": "s", "title": "Skills", "kind": "skills", "entries": [
        {"id": "1", "heading": "Languages", "bullets": ["Python, SQL"]},
        {"id": "2", "heading": "Tools", "bullets": ["PostgreSQL, Docker"]},
        {"id": "3", "heading": "Soft skills", "bullets": ["Mentoring"]}]}]}


def test_skills_layouts():
    grouped = text_of(render(skills_content(), {"skills_layout": "grouped"}))
    assert "Languages: Python, SQL" in grouped and "Tools: PostgreSQL, Docker" in grouped
    assert "•" not in grouped
    assert text_of(render(skills_content())) == grouped  # grouped is the default for skills sections
    inline = text_of(render(skills_content(), {"skills_layout": "inline"}))
    assert "Python, SQL, PostgreSQL, Docker, Mentoring" in inline.replace("\n", " ")
    assert "Languages:" not in inline
    columns = text_of(render(skills_content(), {"skills_layout": "columns"}))
    for label in ("Languages:", "Tools:", "Soft skills:"):
        assert label in columns


def test_empty_skills_section_still_renders():
    content = {"name": "A", "sections": [{"id": "s", "title": "Skills", "kind": "skills", "entries": []}]}
    for skills_layout in ("inline", "grouped", "columns"):
        assert "Skills" in text_of(render(content, {"skills_layout": skills_layout}))


def test_special_characters_in_new_fields_are_escaped():
    content = skills_content()
    content["sections"][0]["entries"][0]["bullets"] = ["C++ <b>& R</b>"]
    for skills_layout in ("inline", "grouped", "columns"):
        assert "C++" in text_of(render(content, {"skills_layout": skills_layout}))


def test_certifications_awards_and_volunteering_render_like_other_sections():
    entry = lambda heading, sub, dates, bullets: {"id": heading, "heading": heading, "subheading": sub, "dates": dates, "bullets": bullets}
    content = {"name": "A", "sections": [
        {"id": "c", "title": "Certifications", "kind": "certifications", "entries": [entry("Docker Certified Associate", "Example Academy", "Mar 2022", [])]},
        {"id": "a", "title": "Awards", "kind": "awards", "entries": [entry("Hackathon winner", "City Council", "2021", [])]},
        {"id": "v", "title": "Volunteering", "kind": "volunteering", "entries": [entry("Mentor", "Code Club", "2020", ["Taught Python."])]}]}
    text = text_of(render(content))
    for expected in ("CERTIFICATIONS", "Docker Certified Associate — Example Academy", "Mar 2022", "Hackathon winner — City Council",
                     "Mentor — Code Club", "Taught Python."):
        assert expected.lower() in text.lower(), expected
