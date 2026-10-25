"""Deterministic PDF renderer for saved structured resume documents."""

from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from job_hunter.domain.models import Document
from job_hunter.profile_bank.dates import (DEFAULT_DATE_FORMAT, DEFAULT_PRESENT_LABEL,
                                           format_date_range)

# Documents saved before the style settings existed have none of these keys and keep
# their original look: a navy bold heading, no rule, centred name, "•" points.
LEGACY_HEADING_COLOR = "#17324D"
ACCENT_COLORS = {"black": "#111111", "navy": "#1F3A5F", "teal": "#0F766E", "maroon": "#7F1D1D"}
# Space above a section heading and after each entry, in points. "normal" is the legacy spacing.
SECTION_SPACE_BEFORE = {"compact": 4, "normal": 8, "airy": 14}
ENTRY_GAP = {"compact": 0, "normal": 0, "airy": 4}
CONTACT_SEPARATORS = {"·": " · ", "|": " | "}
NEWLINE_SEPARATORS = {"newline", "new line"}
SMALL_CAPS_REDUCTION = 0.8


def _safe(value: Any) -> str:
    return escape(str(value or ""))


def _fonts(layout: dict, template: str) -> tuple[str, str]:
    """Register the fonts a layout can ask for and return the regular and bold font names."""
    # ReportLab ships the embedded Vera fonts, so sans-serif exports remain
    # portable and selectable without host-installed fonts.
    font_dir = Path(reportlab.__file__).parent / "fonts"
    if "JobHunterVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("JobHunterVera", str(font_dir / "Vera.ttf")))
    if "JobHunterVeraBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("JobHunterVeraBold", str(font_dir / "VeraBd.ttf")))
    pdfmetrics.registerFontFamily("JobHunterVera", normal="JobHunterVera", bold="JobHunterVeraBold",
                                  italic="JobHunterVera", boldItalic="JobHunterVeraBold")
    pdfmetrics.registerFontFamily("Times-Roman", normal="Times-Roman", bold="Times-Bold",
                                  italic="Times-Italic", boldItalic="Times-BoldItalic")
    family = layout.get("font_family", "auto")
    if family == "auto":
        family = "serif" if template == "classic" else "sans"
    if family == "latex":
        bundled = Path(__file__).parent / "fonts"
        for name, filename in [("JobHunterLatinModern", "lmroman-regular.ttf"), ("JobHunterLatinModernBold", "lmroman-bold.ttf")]:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(bundled / filename)))
        pdfmetrics.registerFontFamily("JobHunterLatinModern", normal="JobHunterLatinModern", bold="JobHunterLatinModernBold")
        return "JobHunterLatinModern", "JobHunterLatinModernBold"
    if family == "serif":
        return "Times-Roman", "Times-Bold"
    if family == "mono":
        return "Courier", "Courier-Bold"
    return "JobHunterVera", "JobHunterVeraBold"


def letter_pdf_bytes(doc: Document) -> bytes:
    """A cover letter as a PDF: sender block, date, recipient, greeting, paragraphs, closing and signature."""
    content, layout = doc.content, doc.layout
    page = letter if layout.get("page_size") == "letter" else A4
    margin = float(layout.get("margin", 22)) * mm
    fs = float(layout.get("font_size", 11))
    leading = fs * float(layout.get("line_spacing", 1.3))
    body_font, bold_font = _fonts(layout, doc.template)
    out = BytesIO()
    pdf = SimpleDocTemplate(out, pagesize=page, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin, title=doc.title)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="LetterName", parent=styles["Title"], fontName=bold_font, fontSize=fs + 6,
                              leading=(fs + 6) * 1.2, alignment=TA_LEFT, spaceAfter=2))
    styles.add(ParagraphStyle(name="LetterBody", parent=styles["BodyText"], fontName=body_font, fontSize=fs,
                              leading=leading, spaceAfter=fs * 0.8))
    contact = " · ".join(_safe(content.get(key)) for key in ("email", "phone", "location") if content.get(key))
    flow = [Paragraph(_safe(content.get("name") or "Your Name"), styles["LetterName"])]
    if contact:
        flow.append(Paragraph(contact, styles["LetterBody"]))
    flow.append(HRFlowable(width="100%", thickness=0.7, color=ACCENT_COLORS["black"], spaceBefore=2, spaceAfter=fs))
    if content.get("date"):
        flow.append(Paragraph(_safe(content["date"]), styles["LetterBody"]))
    if content.get("recipient"):
        flow.append(Paragraph("<br/>".join(_safe(line) for line in str(content["recipient"]).splitlines() if line.strip()), styles["LetterBody"]))
    if content.get("greeting"):
        flow.append(Paragraph(_safe(content["greeting"]), styles["LetterBody"]))
    for paragraph in content.get("paragraphs", []):
        if str(paragraph or "").strip():
            flow.append(Paragraph("<br/>".join(_safe(line) for line in str(paragraph).splitlines()), styles["LetterBody"]))
    if content.get("closing"):
        flow.append(Paragraph(_safe(content["closing"]), styles["LetterBody"]))
    flow.append(Paragraph(_safe(content.get("signature") or content.get("name")), styles["LetterBody"]))
    pdf.build(flow)
    return out.getvalue()


def pdf_bytes(doc: Document) -> bytes:
    if getattr(doc, "kind", "resume") in ("cover_letter", "archived_letter"):
        return letter_pdf_bytes(doc)
    content, layout = doc.content, doc.layout
    page = letter if layout.get("page_size") == "letter" else A4
    margin = float(layout.get("margin", 18)) * mm
    fs = float(layout.get("font_size", 11))
    line_spacing = float(layout.get("line_spacing", 1.25))
    body_font, bold_font = _fonts(layout, doc.template)

    out = BytesIO()
    pdf = SimpleDocTemplate(out, pagesize=page, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin, title=doc.title)
    styles = getSampleStyleSheet()
    leading = fs * line_spacing
    accent = ACCENT_COLORS.get(layout.get("accent_color"), LEGACY_HEADING_COLOR)
    header_align = layout.get("header_align")
    spacing = layout.get("section_spacing")
    styles.add(ParagraphStyle(name="ResumeName", parent=styles["Title"], fontName=bold_font,
        fontSize=fs + 8, leading=(fs + 8) * line_spacing,
        alignment=TA_LEFT if header_align == "left" else TA_CENTER, spaceAfter=3))
    heading_style = layout.get("heading_style")
    styles.add(ParagraphStyle(name="ResumeSection", parent=styles["Heading2"], fontName=bold_font,
        fontSize=fs + 1, leading=(fs + 1) * line_spacing,
        spaceBefore=SECTION_SPACE_BEFORE.get(spacing, 8), spaceAfter=1 if heading_style == "rule" else 3,
        textColor=accent))
    styles.add(ParagraphStyle(name="ResumeBody", parent=styles["BodyText"], fontName=body_font,
        fontSize=fs, leading=leading, spaceAfter=2))
    contact_style = styles["ResumeBody"]
    if header_align in ("center", "left"):
        contact_style = ParagraphStyle(name="ResumeContact", parent=styles["ResumeBody"],
                                       alignment=TA_LEFT if header_align == "left" else TA_CENTER)
    entry_gap = ENTRY_GAP.get(spacing, 0)
    prefix = _bullet_prefix(layout.get("bullet_char"), fs)

    flow = [Paragraph(_safe(content.get("name") or "Your Name"), styles["ResumeName"])]
    contact_parts = [_safe(content.get(key)) for key in ("email", "phone", "location") if content.get(key)]
    separator = layout.get("contact_separator")
    contact = ("<br/>" if separator in NEWLINE_SEPARATORS else CONTACT_SEPARATORS.get(separator, " · ")).join(contact_parts)
    if contact:
        flow.append(Paragraph(contact, contact_style))
    if content.get("summary"):
        flow.extend([Spacer(1, 5), Paragraph(_safe(content["summary"]), styles["ResumeBody"])])
    for section in content.get("sections", []):
        if section.get("hidden") is True:
            continue
        title = section.get("title", "Section")
        if heading_style == "small-caps":
            flow.append(Paragraph(_small_caps(title, fs + 1), styles["ResumeSection"]))
        else:
            flow.append(Paragraph(_safe(title), styles["ResumeSection"]))
        if heading_style == "rule":
            flow.append(HRFlowable(width="100%", thickness=0.7, color=accent, spaceBefore=0, spaceAfter=3))
        if section.get("kind") == "skills":
            flow.extend(_skills_flowables(section.get("entries", []), layout.get("skills_layout"),
                                          styles["ResumeBody"], pdf.width - 12))
            continue
        for entry in section.get("entries", []):
            heading = " — ".join(_safe(entry.get(key)) for key in ("heading", "subheading")
                                 if entry.get(key))
            dates = _safe(_entry_dates(entry, layout))
            if heading or dates:
                flow.append(Paragraph(f"<b>{heading}</b>{(' · ' + dates) if dates else ''}",
                                      styles["ResumeBody"]))
            for bullet in entry.get("bullets", []):
                flow.append(Paragraph(prefix + _safe(bullet), styles["ResumeBody"]))
            if entry_gap:
                flow.append(Spacer(1, entry_gap))
    pdf.build(flow)
    return out.getvalue()


def _entry_dates(entry: dict, layout: dict) -> Any:
    """Dates for an entry: formatted from `date_range` when it has one, else the typed text."""
    if isinstance(entry.get("date_range"), dict):
        formatted = format_date_range(entry["date_range"], layout.get("date_format", DEFAULT_DATE_FORMAT),
                                      layout.get("present_label", DEFAULT_PRESENT_LABEL))
        if formatted:
            return formatted
    return entry.get("dates")


def _bullet_prefix(bullet_char: Any, font_size: float) -> str:
    # "▪" is not in the standard PDF fonts, so draw it with the built-in Dingbats square.
    if bullet_char == "▪":
        return f'<font name="ZapfDingbats" size="{font_size * 0.6:.1f}">n</font> '
    return ("– " if bullet_char == "–" else "• ")


def _small_caps(text: Any, size: float) -> str:
    """Emulate small capitals: each word's first letter full size, the rest smaller."""
    small = round(size * SMALL_CAPS_REDUCTION, 1)
    words = []
    for word in str(text or "").split():
        head, tail = _safe(word[0].upper()), _safe(word[1:].upper())
        words.append(f'{head}<font size="{small}">{tail}</font>' if tail else head)
    return " ".join(words)


def _skills_flowables(entries: list, skills_layout: Any, style: ParagraphStyle, width: float) -> list:
    """Skills as one line per entry ("Languages: Python, SQL"), one run-on line or two columns."""
    lines = []
    for entry in entries:
        values = ", ".join(_safe(text).strip() for text in entry.get("bullets", []) if str(text or "").strip())
        label = _safe(entry.get("heading")).strip()
        if values:
            lines.append((label, values))
    if not lines:
        return []
    if skills_layout == "inline":
        return [Paragraph(", ".join(values for _, values in lines), style)]
    paragraphs = [Paragraph(f"<b>{label}:</b> {values}" if label else values, style) for label, values in lines]
    if skills_layout == "columns" and len(paragraphs) > 1:
        half = (len(paragraphs) + 1) // 2
        left, right = paragraphs[:half], paragraphs[half:]
        rows = [[left[i], right[i] if i < len(right) else ""] for i in range(len(left))]
        table = Table(rows, colWidths=[width / 2, width / 2])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return [table]
    return paragraphs
