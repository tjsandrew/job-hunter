"""Deterministic PDF renderer for saved structured resume documents."""

from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from job_hunter.domain.models import Document


def _safe(value: Any) -> str:
    return escape(str(value or ""))


def pdf_bytes(doc: Document) -> bytes:
    content, layout = doc.content, doc.layout
    page = letter if layout.get("page_size") == "letter" else A4
    margin = float(layout.get("margin", 18)) * mm
    fs = float(layout.get("font_size", 11))
    line_spacing = float(layout.get("line_spacing", 1.25))

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

    out = BytesIO()
    pdf = SimpleDocTemplate(out, pagesize=page, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin, title=doc.title)
    styles = getSampleStyleSheet()
    family = layout.get("font_family", "auto")
    if family == "auto":
        family = "serif" if doc.template == "classic" else "sans"
    if family == "latex":
        bundled = Path(__file__).parent / "fonts"
        for name, filename in [("JobHunterLatinModern", "lmroman-regular.ttf"), ("JobHunterLatinModernBold", "lmroman-bold.ttf")]:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(bundled / filename)))
        pdfmetrics.registerFontFamily("JobHunterLatinModern", normal="JobHunterLatinModern", bold="JobHunterLatinModernBold")
        body_font, bold_font = "JobHunterLatinModern", "JobHunterLatinModernBold"
    elif family == "serif":
        body_font, bold_font = "Times-Roman", "Times-Bold"
    elif family == "mono":
        body_font, bold_font = "Courier", "Courier-Bold"
    else:
        body_font, bold_font = "JobHunterVera", "JobHunterVeraBold"
    leading = fs * line_spacing
    styles.add(ParagraphStyle(name="ResumeName", parent=styles["Title"], fontName=bold_font,
        fontSize=fs + 8, leading=(fs + 8) * line_spacing, alignment=TA_CENTER, spaceAfter=3))
    styles.add(ParagraphStyle(name="ResumeSection", parent=styles["Heading2"], fontName=bold_font,
        fontSize=fs + 1, leading=(fs + 1) * line_spacing, spaceBefore=8, spaceAfter=3,
        textColor="#17324D"))
    styles.add(ParagraphStyle(name="ResumeBody", parent=styles["BodyText"], fontName=body_font,
        fontSize=fs, leading=leading, spaceAfter=2))

    flow = [Paragraph(_safe(content.get("name") or "Your Name"), styles["ResumeName"])]
    contact = " · ".join(_safe(content.get(key)) for key in ("email", "phone", "location")
                         if content.get(key))
    if contact:
        flow.append(Paragraph(contact, styles["ResumeBody"]))
    if content.get("summary"):
        flow.extend([Spacer(1, 5), Paragraph(_safe(content["summary"]), styles["ResumeBody"])])
    for section in content.get("sections", []):
        flow.append(Paragraph(_safe(section.get("title", "Section")), styles["ResumeSection"]))
        for entry in section.get("entries", []):
            heading = " — ".join(_safe(entry.get(key)) for key in ("heading", "subheading")
                                 if entry.get(key))
            dates = _safe(entry.get("dates"))
            if heading or dates:
                flow.append(Paragraph(f"<b>{heading}</b>{(' · ' + dates) if dates else ''}",
                                      styles["ResumeBody"]))
            for bullet in entry.get("bullets", []):
                flow.append(Paragraph("• " + _safe(bullet), styles["ResumeBody"]))
    pdf.build(flow)
    return out.getvalue()
