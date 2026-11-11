"""The Launch Blueprint as a PDF (A4), from blueprint.md: the same text, set in IBM Plex Sans
(bundled in fonts/, SIL Open Font License), with page numbers and clickable source links.

    pdf_bytes = blueprint_pdf(Path("outputs/<run_id>/blueprint.md").read_text())

The Markdown is walked token by token (markdown-it), so headings, paragraphs, lists and tables
get a real layout: tables size their columns from their content and keep only horizontal rules.
"""

import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import TableBordersLayout
from fpdf.fonts import FontFace
from markdown_it import MarkdownIt

FONTS = Path(__file__).parent / "fonts"
INK, MUTED, BRAND, RULE = (23, 21, 26), (95, 91, 99), (200, 23, 93), (220, 218, 224)
MD = MarkdownIt("commonmark", {"html": False}).enable("table")
BODY, LEAD = 9.5, 4.9  # pt, line height in mm
# Characters outside the font (emoji in campaign copy): dropped from the PDF only
NOT_IN_FONT = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


class BlueprintPDF(FPDF):
    def __init__(self, title: str):
        super().__init__(format="A4")
        self.doc_title = title
        for style, name in (("", "Regular"), ("B", "SemiBold"), ("I", "Italic")):
            self.add_font("Plex", style, str(FONTS / f"IBMPlexSans-{name}.ttf"))
        self.set_margins(20, 18, 20)
        self.set_auto_page_break(True, margin=18)
        self.set_title(title)
        self.set_creator("PremortemAI")
        self.set_draw_color(*RULE)

    def header(self):
        if self.page_no() > 1:
            self.set_font("Plex", size=8)
            self.set_text_color(*MUTED)
            self.cell(0, 6, self.doc_title)
            self.ln(10)

    def footer(self):
        self.set_y(-12)
        self.set_font("Plex", size=8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"PremortemAI · page {self.page_no()} of {{nb}}", align="R")


def _inline(token, links: bool = True) -> str:
    """An inline token as fpdf markdown: **bold**, __italic__; code and links as plain text."""
    out = []
    for child in token.children or []:
        if child.type == "text":
            out.append(child.content.replace("**", "").replace("__", "_ _"))
        elif child.type == "code_inline":
            out.append(child.content)
        elif child.type in ("strong_open", "strong_close"):
            out.append("**")
        elif child.type in ("em_open", "em_close"):
            out.append("__")
        elif child.type in ("softbreak", "hardbreak"):
            out.append(" ")
        elif child.type == "link_open":
            pass
    return NOT_IN_FONT.sub("", "".join(out)).strip()


def _plain(token) -> str:
    return re.sub(r"\*\*|__", "", _inline(token))


def _widths(pdf: FPDF, rows: list[list[str]], total: float) -> list[float]:
    """Column widths from the content: never narrower than the longest word, short columns as wide
    as their longest value, the rest of the width shared by the long-text columns in proportion."""
    n = len(rows[0])
    text = [[re.sub(r"\*\*|__", "", r[i]) for r in rows if i < len(r)] for i in range(n)]
    word = [max((pdf.get_string_width(w) for c in col for w in c.split()), default=6) + 4 for col in text]
    full = [max((pdf.get_string_width(c) for c in col), default=6) + 4 for col in text]
    short = [f <= 40 for f in full]
    fixed = sum(f for f, sh in zip(full, short) if sh)
    weights = [sum(len(c) for c in col) for col, sh in zip(text, short) if not sh]
    left, out, k = max(total - fixed, total * 0.3), [], 0
    for i in range(n):
        if short[i]:
            out.append(full[i])
        else:
            out.append(max(word[i], left * weights[k] / (sum(weights) or 1)))
            k += 1
    scale = total / sum(out)
    return [w * scale for w in out]


def _table(pdf: BlueprintPDF, rows: list[list[str]], header: bool) -> None:
    pdf.set_font("Plex", size=8.5)
    pdf.set_text_color(*INK)
    widths = _widths(pdf, rows, pdf.epw)
    with pdf.table(col_widths=widths, width=pdf.epw, line_height=4.3, text_align="LEFT",
                   borders_layout=TableBordersLayout.HORIZONTAL_LINES, first_row_as_headings=header,
                   headings_style=FontFace(family="Plex", emphasis=None, size_pt=8, color=MUTED),
                   padding=(1.6, 2, 1.6, 0), markdown=True) as table:
        for row in rows:
            r = table.row()
            for cell in row:
                r.cell(cell or "")
    pdf.ln(3)


def _paragraph(pdf: BlueprintPDF, text: str, indent: float = 0, bullet: str | None = None) -> None:
    pdf.set_font("Plex", size=BODY)
    pdf.set_text_color(*INK)
    x = pdf.l_margin + indent
    if bullet:
        pdf.set_x(x)
        pdf.set_text_color(*MUTED)
        width = 7 if bullet[0].isdigit() else 5
        pdf.cell(width, LEAD, bullet)
        pdf.set_text_color(*INK)
        x += width
    pdf.set_x(x)
    sources = re.fullmatch(r"(.*?)(https?://\S+)", text)
    if sources:  # a Sources line: the URL is a link
        pdf.multi_cell(pdf.epw - (x - pdf.l_margin), LEAD, sources.group(2), link=sources.group(2),
                       align="L", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.multi_cell(pdf.epw - (x - pdf.l_margin), LEAD, text, markdown=True, align="L",
                       new_x="LMARGIN", new_y="NEXT")


def blueprint_pdf(markdown: str) -> bytes:
    match = re.match(r"# (.*)", markdown)
    title = match.group(1).strip() if match else "Launch Blueprint"
    pdf = BlueprintPDF(title)
    pdf.add_page()
    pdf.set_font("Plex", "B", 8.5)
    pdf.set_text_color(*BRAND)
    pdf.cell(0, 5, "PremortemAI · Launch Blueprint", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Plex", "B", 20)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 9, title.replace("Launch Blueprint: ", ""), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    tokens = MD.parse(re.sub(r"^# .*\n", "", markdown, count=1))
    lists: list[list] = []  # stack of [ordered, counter]
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open":
            level = int(t.tag[1])
            text = _plain(tokens[i + 1])
            if pdf.will_page_break(24):
                pdf.add_page()
            pdf.ln(5 if level == 2 else 2)
            pdf.set_font("Plex", "B", 13.5 if level == 2 else 10.5)
            pdf.set_text_color(*INK)
            pdf.multi_cell(0, 6.5 if level == 2 else 5.5, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
            i += 3
            continue
        if t.type in ("bullet_list_open", "ordered_list_open"):
            lists.append([t.type == "ordered_list_open", int(t.attrs.get("start", 1) or 1) - 1])
        elif t.type in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
            if not lists:
                pdf.ln(1.5)
        elif t.type == "list_item_open":
            lists[-1][1] += 1
        elif t.type == "paragraph_open":
            text = _inline(tokens[i + 1])
            if lists:
                ordered, n = lists[-1]
                _paragraph(pdf, text, indent=4 * (len(lists) - 1), bullet=f"{n}." if ordered else "•")
                pdf.ln(0.8)
            else:
                _paragraph(pdf, text)
                pdf.ln(2.2)
            i += 3
            continue
        elif t.type == "table_open":
            rows, header, j = [], False, i + 1
            while tokens[j].type != "table_close":
                if tokens[j].type == "thead_open":
                    header = True
                if tokens[j].type == "tr_open":
                    rows.append([])
                if tokens[j].type == "inline":
                    rows[-1].append(_inline(tokens[j]))
                j += 1
            if header and rows and not any(rows[0]):  # "| | |" header of a key/value table
                rows, header = rows[1:], False
            _table(pdf, rows, header)
            i = j + 1
            continue
        elif t.type == "hr":
            pdf.ln(2)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pdf.epw, pdf.get_y())
            pdf.ln(3)
        i += 1
    return bytes(pdf.output())
