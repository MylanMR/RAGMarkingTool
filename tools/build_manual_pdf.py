"""Render USER_MANUAL.md to a paginated PDF with a title page and TOC.

Usage: python tools/build_manual_pdf.py USER_MANUAL.md USER_MANUAL.pdf (needs reportlab)
"""
import re, sys
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph,
                                Preformatted, Spacer, Table, TableStyle, KeepTogether)
from reportlab.platypus.tableofcontents import TableOfContents

SRC, OUT = sys.argv[1], sys.argv[2]
NAVY = colors.HexColor("#0033a0"); INK = colors.HexColor("#1c1e21"); GREY = colors.HexColor("#5b616b")
RULE = colors.HexColor("#d0d3d8"); SHADE = colors.HexColor("#f4f5f7")

base = dict(fontName="Helvetica", fontSize=10, leading=14, textColor=INK)
S = {
    "body": ParagraphStyle("body", **base, spaceAfter=6),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY, spaceBefore=4, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=INK, spaceBefore=12, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11, leading=15, textColor=INK, spaceBefore=8, spaceAfter=4),
    "cell": ParagraphStyle("cell", **dict(base, fontSize=8.8, leading=11.5)),
    "cellh": ParagraphStyle("cellh", **dict(base, fontName="Helvetica-Bold", fontSize=8.8, leading=11.5, textColor=colors.white)),
    "bullet": ParagraphStyle("bullet", **base, leftIndent=16, bulletIndent=4, spaceAfter=3),
    "bullet2": ParagraphStyle("bullet2", **base, leftIndent=32, bulletIndent=20, spaceAfter=3),
    "code": ParagraphStyle("code", fontName="Courier", fontSize=8.3, leading=10.5, textColor=INK,
                           backColor=SHADE, borderPadding=6, leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=10),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=30, leading=36, textColor=NAVY),
    "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=13, leading=18, textColor=GREY),
    "toc1": ParagraphStyle("toc1", fontName="Helvetica", fontSize=10.5, leading=16, leftIndent=0),
    "toc2": ParagraphStyle("toc2", fontName="Helvetica", fontSize=9.5, leading=13, leftIndent=16, textColor=GREY),
}

def inline(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"`([^`]+)`", r'<font face="Courier" size="9">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?!\w)", r"<i>\1</i>", t)
    t = re.sub(r"\[([^\]]+)\]\((#[^)]+)\)", r"\1", t)          # internal links -> text
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#0033a0">\1</link>', t)
    return t

class Doc(BaseDocTemplate):
    def beforeDocument(self):
        self._hseq = 0  # same bookmark keys on every multiBuild pass

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name in ("h1", "h2"):
            lvl = 0 if f.style.name == "h1" else 1
            key = "h{}".format(self._hseq)
            self._hseq += 1
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(f.getPlainText(), key, level=lvl, closed=lvl > 0)
            self.notify("TOCEntry", (lvl, f.getPlainText(), self.page, key))

def page_deco(canv, doc):
    if doc.page == 1:
        return
    canv.saveState()
    canv.setFont("Helvetica", 8); canv.setFillColor(GREY)
    canv.drawString(inch, 0.6 * inch, "RAG Marking Tool user manual, version 0.2.1")
    canv.drawRightString(letter[0] - inch, 0.6 * inch, "Page {}".format(doc.page))
    canv.setStrokeColor(RULE); canv.line(inch, 0.78 * inch, letter[0] - inch, 0.78 * inch)
    canv.restoreState()

lines = open(SRC, encoding="utf-8").read().splitlines()
story = []
# Title page
title = lines[0].lstrip("# ").strip()
version = lines[2].strip()
story += [Spacer(1, 2.2 * inch), Paragraph("RAG Marking Tool", S["title"]),
          Spacer(1, 6), Paragraph("User manual", ParagraphStyle("t2", parent=S["title"], fontSize=22, textColor=INK)),
          Spacer(1, 18), Paragraph(version, S["subtitle"]),
          Spacer(1, 4), Paragraph("Classification-aware retrieval, AI-assisted drafting, and release review", S["subtitle"]),
          Spacer(1, 2.4 * inch),
          Paragraph("This system requires an authorization decision before it processes real classified information.", ParagraphStyle("n", parent=S["body"], textColor=GREY)),
          PageBreak()]
toc = TableOfContents(); toc.levelStyles = [S["toc1"], S["toc2"]]
story += [Paragraph("Contents", ParagraphStyle("ch", parent=S["h1"])), toc, PageBreak()]

i = 3
first_h2 = True
def flush_para(buf):
    if buf:
        story.append(Paragraph(inline(" ".join(buf)), S["body"]))
    return []

buf = []
while i < len(lines):
    ln = lines[i]
    st = ln.strip()
    if st.startswith("```"):
        buf = flush_para(buf); code = []; i += 1
        while i < len(lines) and not lines[i].strip().startswith("```"):
            code.append(lines[i]); i += 1
        story.append(Preformatted("\n".join(code), S["code"])); i += 1; continue
    if st.startswith("|"):
        buf = flush_para(buf); rows = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            r = lines[i].strip()
            if not re.match(r"^\|[\s:|-]+\|$", r):
                cells = [c.strip() for c in re.split(r"(?<!\\)\|", r.strip("|"))]
                rows.append([c.replace("\\|", "|") for c in cells])
            i += 1
        ncol = len(rows[0])
        data = [[Paragraph(inline(c), S["cellh"] if ri == 0 else S["cell"]) for c in row + [""] * (ncol - len(row))]
                for ri, row in enumerate(rows)]
        avail = letter[0] - 2 * inch
        lens = [max(len(r[c]) if c < len(r) else 0 for r in rows) for c in range(ncol)]
        w = [max(0.9 * inch, avail * l / sum(lens)) for l in lens]
        scale = avail / sum(w); w = [x * scale for x in w]
        t = Table(data, colWidths=w, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SHADE]),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
        story += [t, Spacer(1, 10)]; continue
    if st.startswith("## "):
        buf = flush_para(buf)
        if not first_h2:
            story.append(PageBreak())
        first_h2 = False
        story.append(Paragraph(inline(st[3:]), S["h1"])); i += 1; continue
    if st.startswith("### "):
        buf = flush_para(buf); story.append(Paragraph(inline(st[4:]), S["h2"])); i += 1; continue
    if st.startswith("#### "):
        buf = flush_para(buf); story.append(Paragraph(inline(st[5:]), S["h3"])); i += 1; continue
    if st == "---":
        buf = flush_para(buf); i += 1; continue
    m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", ln)
    if m:
        buf = flush_para(buf)
        indent = len(m.group(1)); marker = m.group(2); text = m.group(3)
        i += 1
        while i < len(lines) and lines[i].startswith(" " * (indent + 2)) and lines[i].strip() \
                and not re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
            text += " " + lines[i].strip(); i += 1
        style = S["bullet2"] if indent >= 2 else S["bullet"]
        bullet = "\u2022" if marker in "-*" else marker
        story.append(Paragraph(inline(text), style, bulletText=bullet)); continue
    if not st:
        buf = flush_para(buf); i += 1; continue
    buf.append(st); i += 1
flush_para(buf)

doc = Doc(OUT, pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
          title="RAG Marking Tool user manual", author="RAG Marking Tool", subject="User manual v0.2.1")
doc._hseq = 0
frame = Frame(inch, inch, letter[0] - 2 * inch, letter[1] - 2 * inch, id="f")
doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=page_deco)])
doc.multiBuild(story)
print("pages written")
