"""Screen F: how the pipeline works, one paragraph per agent, and the project map (docs/architecture.html)."""

import streamlit as st
import streamlit.components.v1 as components

from premortem import config
from ui.theme import esc, html_block
from ui.view import ROOT

AGENTS = [
    ("Brief extractor", "brief", "Reads the company document and fills a fixed form: company, product, launch "
     "country, price, the competitors and goals it names, and the information it does not give. Nothing is added "
     "that the document does not say."),
    ("Analyst", "analyst", "A ReAct agent with a web search tool. It plans searches for what the document leaves "
     "open (competitors, prices, market size), reads the results and writes the market analysis: segments with "
     "their size, competitors and needs, each fact with a source id."),
    ("Strategist", "strategist", "Chooses one target segment from the analysis and writes the positioning, the value "
     "proposition, the pricing direction and the channels, citing the sources it relies on."),
    ("Your review", None, "The run pauses after the strategy. Approve it, or send it back with feedback: the "
     "Strategist revises with your words, and the campaign is written only after you approve."),
    ("Creative", "creative", "Writes the campaign concept, the tagline in the language of the country and one "
     "message per channel of the strategy."),
    ("Validator", "validator", f"Checks every output twice: rules in Python (ids exist, sources are cited, channels "
     f"match) and an LLM judge with a fixed rubric. A blocking issue sends the output back, up to "
     f"{config.MAX_REVISIONS} times; what is still open is marked in the timeline and at the top of the blueprint."),
    ("Blueprint", "blueprint", "Renders the Launch Blueprint from the state with a template, so it cannot drift from "
     "what the agents decided. Only the executive summary is written by a model, the biggest of the preset."),
]


def page() -> None:
    html_block('<h1 style="margin:0 0 6px;padding:0">How it works</h1>'
               '<p class="pm-sub">A graph of specialised agents (LangGraph), each checked by a validator, with you in the loop.</p>')
    flow = ["Document", "Brief", "Analyst", "Strategist", "Your review", "Creative", "Blueprint"]
    strip = '<span class="a">→</span>'.join(
        f'<span class="s{" rv" if s == "Your review" else ""}">{s}{" ⇄ Validator" if s in ("Analyst", "Strategist", "Creative") else ""}</span>'
        for s in flow)
    html_block(f'<div class="pm-strip" style="margin:0 0 28px">{strip}</div>')
    left, right = st.columns(2, gap="large")
    for n, (name, role, text) in enumerate(AGENTS):
        with (left if n % 2 == 0 else right):
            st.subheader(name)
            html_block(f'<p style="line-height:22px;margin:0 0 4px">{esc(text)}</p>'
                       + (f'<p class="pm-label">Model role: <span class="pm-id">{role}</span></p>' if role else ""))
    st.subheader("Project map")
    st.caption("Every file and how they connect. Drag to pan, scroll to zoom.")
    path = ROOT / "docs" / "architecture.html"
    if path.exists():
        components.html(path.read_text(), height=720, scrolling=False)
