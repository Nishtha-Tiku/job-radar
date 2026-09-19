"""Render a one-page, ATS-friendly (single column, plain text) resume PDF."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#111111")
ACCENT = colors.HexColor("#0B4F54")
MUTED = colors.HexColor("#444444")
PAGE_W = A4[0]
SIDE = 13 * mm
WIDTH = PAGE_W - 2 * SIDE


def _e(t: str) -> str:
    return escape(t or "")


def _styles(fs: float) -> dict:
    lead = fs * 1.27
    return {
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=fs + 10, leading=fs + 12, textColor=INK),
        "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=fs, leading=lead, textColor=MUTED),
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=fs + 1.2, leading=lead + 1, textColor=ACCENT, spaceBefore=fs * 0.55),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=fs, leading=lead, textColor=INK),
        "right": ParagraphStyle("right", fontName="Helvetica", fontSize=fs, leading=lead, textColor=MUTED, alignment=2),
        "sub": ParagraphStyle("sub", fontName="Helvetica-Oblique", fontSize=fs, leading=lead, textColor=MUTED),
        "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=fs, leading=lead, textColor=INK,
                                 leftIndent=10, bulletIndent=1, spaceAfter=0.6),
    }


def _heading(story, st, title):
    story.append(Paragraph(_e(title.upper()), st["h"]))
    story.append(HRFlowable(width="100%", thickness=0.6, color=ACCENT, spaceBefore=1, spaceAfter=2.5))


def _row(left_html, right_text, st):
    t = Table([[Paragraph(left_html, st["body"]), Paragraph(_e(right_text), st["right"])]],
              colWidths=[WIDTH - 36 * mm, 36 * mm])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _story(content: dict, master: dict, fs: float, drop: int):
    st = _styles(fs)
    h = master["header"]
    story = [Paragraph(_e(h["name"].upper()), st["name"])]
    link = 'color="#0B4F54"'
    story.append(Paragraph(
        f'{_e(h["phone"])} | <a href="mailto:{_e(h["email"])}" {link}>{_e(h["email"])}</a> | '
        f'<a href="{_e(h["linkedin"])}" {link}>LinkedIn</a> | <a href="{_e(h["github"])}" {link}>GitHub</a> | '
        f'{_e(h["location"])}', st["contact"]))

    _heading(story, st, "Professional Summary")
    story.append(Paragraph(_e(content["summary"]), st["body"]))

    _heading(story, st, "Technical Skills")
    for group, items in content["skills"].items():
        if items:
            story.append(Paragraph(f"<b>{_e(group)}:</b> {_e(', '.join(items))}", st["body"]))

    _heading(story, st, "Work Experience")
    exp = content["experience"]
    siemens = master["experience"][0]
    extra = max(0, drop - 2)          # later drops remove experience bullets, keeping at least 4
    keep = exp[: max(4, len(exp) - extra)]
    story.append(_row(f"<b>{_e(siemens['role'])}</b>", siemens["dates"], st))
    story.append(Paragraph(f"{_e(siemens['org'])}, {_e(siemens['place'])}", st["sub"]))
    for b in keep:
        story.append(Paragraph(_e(b), st["bullet"], bulletText="\u2022"))
    if drop < 1:
        intern = master["experience"][1]
        story.append(Spacer(1, 2))
        story.append(_row(f"<b>{_e(intern['role'])}</b>", intern["dates"], st))
        story.append(Paragraph(f"{_e(intern['org'])}, {_e(intern['place'])}", st["sub"]))
        for b in intern["bullets"]:
            story.append(Paragraph(_e(b["text"]), st["bullet"], bulletText="\u2022"))

    projects = content["projects"][: (len(content["projects"]) - 1 if drop >= 2 and len(content["projects"]) > 1 else None)]
    if projects:
        _heading(story, st, "Projects")
        for p in projects:
            story.append(_row(f"<b>{_e(p['name'])}</b>", p["dates"], st))
            story.append(Paragraph(_e(p["stack"]), st["sub"]))
            for b in p["bullets"]:
                story.append(Paragraph(_e(b), st["bullet"], bulletText="\u2022"))

    _heading(story, st, "Education")
    ed = master["education"]
    story.append(_row(f"<b>{_e(ed['degree'])}</b>, {_e(ed['school'])}", ed["dates"], st))
    story.append(Paragraph(_e(ed["score"]), st["sub"]))

    _heading(story, st, "Certifications & Achievements")
    for c in master["certifications"]:
        story.append(Paragraph(_e(c), st["bullet"], bulletText="\u2022"))
    return story


def _build(content, master, fs, drop):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=SIDE, rightMargin=SIDE, topMargin=11 * mm, bottomMargin=10 * mm,
                            title=f"{master['header']['name']} Resume", author=master["header"]["name"])
    doc.build(_story(content, master, fs, drop))
    return buf.getvalue(), doc.page


def render_one_page(content: dict, master: dict) -> bytes:
    """Shrink the font, then drop the least important content, until everything fits on one page."""
    sizes = (10.4, 10.1, 9.8, 9.5, 9.2, 8.9, 8.6, 8.3)
    last = b""
    for drop in range(0, 6):
        for fs in sizes:
            pdf, pages = _build(content, master, fs, drop)
            last = pdf
            if pages == 1:
                return pdf
    return last
