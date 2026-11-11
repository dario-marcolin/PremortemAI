"""Campaign: the concept and tagline, one card per channel, the content ideas and the visual direction."""

import streamlit as st

from premortem.schemas import Campaign
from ui.citations import Citer
from ui.steps.common import round_picker, title_head, title_row, title_sentence, validator_block, version, what_changed
from ui.theme import esc, html_block
from ui.view import RunView


def render(view: RunView, info, citer: Citer) -> None:
    if view.campaign is None:
        sentence = esc(view.now()) if info.status == "running" else (
            "Starts after you approve the strategy." if view.status == "waiting" else "Not started yet.")
        title_row(view, info, sentence)
        return
    title_head(view, info)
    chosen = round_picker(view, "campaign")
    c: Campaign = version(view, "campaign", chosen, Campaign)
    channels = sorted({m.channel for m in c.key_messages})
    title_sentence(f"{len(c.key_messages)} messages for {len(channels)} channels, "
                          f"{len(c.content_ideas)} content ideas.")
    what_changed(view, "campaign", chosen, citer)
    html_block(f'<p class="pm-tagline">{esc(c.tagline)}</p><p class="pm-lead" style="font-weight:400;font-size:16px;'
               f'line-height:25px;color:var(--text)">{citer.text(c.concept)}</p>')
    st.subheader("Messages by channel")
    cards = "".join(f'<div class="pm-msg"><div class="ch">{esc(m.channel)}</div><div class="hl">{esc(m.headline)}</div>'
                    f'<div class="bd">{citer.text(m.body)}</div></div>' for m in c.key_messages)
    html_block(f'<div class="pm-msgs">{cards}</div>')
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Content ideas")
        html_block("<ul class='pm-reason'>" + "".join(f"<li>{citer.text(i)}</li>" for i in c.content_ideas) + "</ul>")
    with right:
        st.subheader("Visual direction")
        st.write(c.visual_direction)
    validator_block(view, "campaign", chosen, info)
