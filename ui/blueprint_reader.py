"""Screen C: the Launch Blueprint in a reading layout, with a table of contents, citation chips on
every [n], a Sources list with anchors and the downloads: a paginated PDF (premortem/output/pdf.py)
first, the Markdown second."""

import re

import streamlit as st
from markdown_it import MarkdownIt

from premortem.output.pdf import blueprint_pdf
from ui.citations import Citer
from ui.theme import esc, html_block
from ui.view import RunView

MD = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", text).lower()).strip("-")


def to_html(markdown: str, citer: Citer) -> tuple[str, list[tuple[int, str, str]]]:
    """The blueprint as HTML with ids on its headings and numbered anchors on its sources, and the TOC."""
    body = re.sub(r"^# .*\n", "", markdown, count=1)  # the title is the screen's h1
    html = MD.render(body)
    toc = []

    def heading(m: re.Match) -> str:
        level, text = int(m.group(1)), m.group(2)
        anchor = "sources" if re.search(r"sources|references", text, re.I) and level == 2 else slug(text)
        if level == 2:
            toc.append((level, anchor, re.sub(r"<[^>]+>", "", text)))
        return f'<h{level} id="{anchor}">{text}</h{level}>'

    html = re.sub(r"<h([23])>(.*?)</h\1>", heading, html)
    html = citer.blueprint_html(html)
    head, sep, tail = html.partition('<h2 id="sources"')
    # The Sources list: numbered items with anchors (#src-3), web links open in a new tab
    numbers = iter(range(1, 10_000))
    tail = re.sub(r"<li>", lambda m: f'<li id="src-{next(numbers)}">', tail)
    tail = tail.replace("<a href=", '<a target="_blank" rel="noopener" href=').replace("<ol>", '<ol class="sources">', 1)
    return head + sep + tail, toc


@st.cache_data(show_spinner="Preparing the PDF…", max_entries=16)
def pdf_of(markdown: str) -> bytes:
    return blueprint_pdf(markdown)


def render(view: RunView) -> None:
    md = view.blueprint_md
    if not md:
        html_block('<h1 style="margin:0 0 6px;padding:0">Blueprint</h1>')
        st.caption("The blueprint is written at the end of the run, after the campaign.")
        return
    citer = Citer(view)
    body, toc = to_html(md, citer)
    title = re.match(r"# (.*)", md)
    html_block(f'<h1 style="margin:0 0 6px;padding:0">{esc(title.group(1) if title else "Launch Blueprint")}</h1>'
               f'<p class="pm-sub">Hover a number to see its source; click a web source to open it.</p>')
    a, b, c, _ = st.columns([1.2, 1.1, 1, 2.4])
    a.download_button("Download PDF", pdf_of(md), file_name=f"{view.run_id}_blueprint.pdf", mime="application/pdf",
                      type="primary", icon=":material/picture_as_pdf:", width="stretch", key=f"dl_pdf_{view.run_id}")
    b.download_button("Markdown", md, file_name=f"{view.run_id}_blueprint.md", mime="text/markdown",
                      icon=":material/download:", width="stretch", key=f"dl_md_{view.run_id}")
    if (view.dir / "state.json").exists():
        c.download_button("state.json", (view.dir / "state.json").read_text(), file_name=f"{view.run_id}_state.json",
                          mime="application/json", width="stretch", key=f"dl_state_{view.run_id}", type="tertiary")

    side, main = st.columns([1, 4], gap="large")
    with side:
        links = "".join(f'<a href="#{a}">{esc(t)}</a>' for _, a, t in toc)
        html_block(f'<nav class="pm-toc" aria-label="Contents"><div class="pm-label" style="margin-bottom:8px">Contents</div>{links}</nav>')
    with main:
        st.html(f'<article class="pm-doc">{body}</article>')
