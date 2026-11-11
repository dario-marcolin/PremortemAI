"""Analysis: the market, the segments (size × intent, so a trap segment shows up small), the
competitors and the searches the Analyst made, with the ones it cited."""

import re

import altair as alt
import streamlit as st

from ui.citations import Citer
from premortem.schemas import Analysis
from ui.steps.common import round_picker, title_head, title_row, title_sentence, validator_block, version, what_changed
from ui.theme import esc, html_block
from ui.view import RunView, domain

SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(million|M|k|thousand)?\b", re.I)
INTENT = [re.compile(r"(\d+(?:\.\d+)?)\s?%[^.%]{0,40}?(?:purchase intent|would buy|intent)", re.I),
          re.compile(r"intent[^.%\d]{0,40}?(\d+(?:\.\d+)?)\s?%", re.I)]
UNITS = {"million": 1e6, "m": 1e6, "k": 1e3, "thousand": 1e3}


def parse_size(text: str | None) -> float | None:
    m = SIZE.search(text or "")
    if not m or not m.group(2):
        return None
    return float(m.group(1).replace(",", ".")) * UNITS[m.group(2).lower()]


def parse_intent(*texts: str) -> float | None:
    for text in texts:
        for pattern in INTENT:
            m = pattern.search(text or "")
            if m:
                return float(m.group(1))
    return None


def human(n: float) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k"


def segment_chart(view: RunView, analysis) -> None:
    target = view.strategy.target_segment_id if view.strategy else None
    rows = []
    for s in analysis.segments:
        size, intent = parse_size(s.estimated_size), parse_intent(s.description, " ".join(s.needs), s.estimated_size or "")
        if size is not None and intent is not None:
            rows.append({"id": s.segment_id, "label": s.label, "size": size / 1e6, "intent": intent,
                         "shown": f"{s.segment_id} · {s.label}" + (" · chosen target" if s.segment_id == target else ""),
                         "size_text": human(size),
                         "role": "Chosen target" if s.segment_id == target else "Other segments"})
    if len(rows) < 2:
        return
    unit = "people"
    m = re.search(r"\b(adults|households|freelancers|businesses|people|companies)\b", analysis.segments[0].estimated_size or "")
    if m:
        unit = m.group(1)
    st.subheader("Segments by size and purchase intent")
    st.caption(f"Read from each segment's size and intent figures. Bubble area is the size; the chosen target is in colour.")
    colour = alt.Color("role:N", scale=alt.Scale(domain=["Chosen target", "Other segments"], range=["#c8175d", "#8d8893"]),
                       legend=None)
    base = alt.Chart(alt.Data(values=rows)).encode(
        x=alt.X("size:Q", title=f"Size (millions of {unit})",
                scale=alt.Scale(zero=True, nice=False, domain=[0, max(r["size"] for r in rows) * 1.45]),
                axis=alt.Axis(grid=True, gridColor="#f0eff2", domain=False, tickCount=5, labelFontSize=12, titleFontSize=12,
                              titleColor="#5f5b63", titleFontWeight=400)),
        y=alt.Y("intent:Q", title="Purchase intent (%)", scale=alt.Scale(zero=True, domain=[0, max(r["intent"] for r in rows) * 1.18]),
                axis=alt.Axis(grid=True, gridColor="#f0eff2", domain=False, tickCount=5, labelFontSize=12, titleFontSize=12,
                              titleColor="#5f5b63", titleFontWeight=400)),
    )
    bubbles = base.mark_circle(opacity=0.9, stroke="#ffffff", strokeWidth=1.5).encode(
        size=alt.Size("size:Q", scale=alt.Scale(range=[120, 2600]), legend=None), color=colour,
        tooltip=[alt.Tooltip("shown:N", title="Segment"), alt.Tooltip("size_text:N", title="Size"),
                 alt.Tooltip("intent:Q", title="Intent (%)")])
    # One label layer per bubble, so each label starts just past its own bubble's edge
    largest = max(r["size"] for r in rows)
    labels = [alt.Chart(alt.Data(values=[r])).mark_text(
        align="left", dx=(120 + r["size"] / largest * 2480) ** 0.5 / 1.77 + 6, fontSize=12, font="IBM Plex Sans",
        color="#8f0f41" if r["role"] == "Chosen target" else "#3d3a41",
        fontWeight=600 if r["role"] == "Chosen target" else 400).encode(x="size:Q", y="intent:Q", text="shown:N")
        for r in rows]
    st.altair_chart(alt.layer(bubbles, *labels).properties(height=300).configure_view(strokeWidth=0)
                    .configure(font="IBM Plex Sans"), width="stretch")


def segments_table(view: RunView, analysis, citer: Citer) -> None:
    target = view.strategy.target_segment_id if view.strategy else None
    rows = []
    for s in analysis.segments:
        cls = ' class="target"' if s.segment_id == target else ""
        mark = ' <span class="pm-pill review" style="height:18px;font-size:11px">Target</span>' if cls else ""
        rows.append(f'<tr{cls}><td><span class="pm-id">{esc(s.segment_id)}</span></td>'
                    f'<td><b style="font-weight:500">{esc(s.label)}</b>{mark}<br>'
                    f'<span style="color:var(--muted)">{citer.text(s.description)}</span></td>'
                    f'<td>{citer.text(s.estimated_size) or "<span style=color:var(--faint)>not found</span>"}</td>'
                    f'<td>{citer.ids(s.source_ids)}</td></tr>')
    html_block('<table class="pm-table"><thead><tr><th style="width:64px">Id</th><th>Segment</th>'
               '<th style="width:26%">Estimated size</th><th style="width:96px">Sources</th></tr></thead>'
               f'<tbody>{"".join(rows)}</tbody></table>')


def competitors_table(analysis, citer: Citer) -> None:
    rows = "".join(
        f'<tr><td><b style="font-weight:500">{esc(c.name)}</b></td><td>{citer.text(c.positioning)}</td>'
        f'<td>{"<span style=color:var(--faint)>unknown</span>" if c.price_level == "unknown" else esc(c.price_level)}</td>'
        f'<td>{citer.ids(c.source_ids)}</td></tr>' for c in analysis.competitors)
    html_block('<table class="pm-table"><thead><tr><th style="width:18%">Competitor</th><th>Positioning</th>'
               f'<th style="width:90px">Price level</th><th style="width:96px">Sources</th></tr></thead><tbody>{rows}</tbody></table>')


def searches_block(view: RunView, analysis, citer: Citer, chosen: int) -> None:
    searches = [s for s in view.searches if s.get("round", 1) == chosen] or view.searches
    cited = {s.reference: s.id for s in analysis.sources if s.kind == "web"}
    n_cited = sum(1 for s in searches for r in s.get("results") or [] if r["url"] in cited)
    with st.expander(f"Searches the Analyst made · {len(searches)} queries"
                     + (f", {n_cited} results cited" if n_cited else ""), expanded=False):
        if not searches:
            st.caption("No web search in this round (no Tavily key, or the document was enough).")
        blocks = []
        for s in searches:
            results = s.get("results") or []
            if results:
                items = "".join(
                    f'<li class="{"cited" if r["url"] in cited else ""}"><span class="tag">'
                    f'{citer.source_chip(cited[r["url"]]) if r["url"] in cited else "<span style=width:26px;display:inline-block></span>"}</span>'
                    f'<span>{esc(r.get("title") or r["url"])} · <span style="color:var(--faint)">{esc(domain(r["url"]))}</span></span></li>'
                    for r in results)
                body = f"<ul>{items}</ul>"
            elif s.get("error"):
                body = f'<ul><li>{esc(s["error"])}</li></ul>'
            else:
                count = s.get("count")
                body = f'<ul><li>{count if count is not None else "—"} results (details are kept only for runs made after Phase 15)</li></ul>'
            blocks.append(f'<div class="pm-search"><div class="q">‘{esc(s["query"])}’</div>{body}</div>')
        html_block("".join(blocks))


def render(view: RunView, info, citer: Citer) -> None:
    a = view.analysis
    if a is None:
        title_row(view, info, esc(view.now()) if info.status == "running" else "Not started yet.")
        if view.searches:
            st.subheader("Searching")
            html_block("".join(f'<div class="pm-search"><div class="q">‘{esc(s["query"])}’</div></div>' for s in view.searches))
        return
    title_head(view, info)
    chosen = round_picker(view, "analysis")
    a = version(view, "analysis", chosen, Analysis)
    web = sum(s.kind == "web" for s in a.sources)
    title_sentence(f"{len(a.segments)} segments, {len(a.competitors)} competitors and {len(a.sources)} sources "
                   f"({web} from the web, {len(a.sources) - web} from the document).")
    what_changed(view, "analysis", chosen, citer)
    html_block(f'<p class="pm-lead" style="font-size:16px;font-weight:400;line-height:25px">{citer.text(a.market_overview)}</p>')

    segment_chart(view, a)
    st.subheader("Segments")
    segments_table(view, a, citer)
    st.subheader("Competitors")
    competitors_table(a, citer)

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Customer needs")
        html_block("<ul class='pm-reason'>" + "".join(f"<li>{citer.text(n)}</li>" for n in a.customer_needs) + "</ul>")
    with right:
        st.subheader("Data quality notes")
        if a.data_quality_notes:
            html_block("<ul class='pm-reason'>" + "".join(f"<li>{citer.text(n)}</li>" for n in a.data_quality_notes) + "</ul>")
        else:
            st.caption("None.")
    searches_block(view, a, citer, chosen)
    validator_block(view, "analysis", chosen, info)
