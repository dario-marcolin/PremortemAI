"""Strategy: the target and why, positioning, channels and pricing, each with its citations, and
the analysis items it relies on. The review panel sits under it while the run waits for you."""

import streamlit as st

from premortem.schemas import Strategy
from ui import review
from ui.citations import Citer
from ui.steps.analysis import parse_intent, parse_size, human
from ui.steps.common import round_picker, title_head, title_row, title_sentence, validator_block, version, what_changed
from ui.theme import esc, html_block, pill
from ui.view import RunView


def render(view: RunView, info, citer: Citer) -> None:
    if view.strategy is None:
        title_row(view, info, esc(view.now()) if info.status == "running" else "Not started yet.")
        return
    title_head(view, info)
    chosen = round_picker(view, "strategy")
    s: Strategy = version(view, "strategy", chosen, Strategy)
    segment = view.analysis.find_segment(s.target_segment_id) if view.analysis else None
    name = f"{s.target_segment_id} · {segment.label}" if segment else f"{s.target_segment_id} (not in the analysis)"
    others = len(view.analysis.segments) - 1 if view.analysis else 0
    title_sentence(f"The Strategist targets <b>{esc(name)}</b>, out of {others + 1} segments.")
    what_changed(view, "strategy", chosen, citer)

    if view.status == "waiting" and view.live and chosen == len(view.rounds.get("strategy") or [1]):
        review.panel("strategy", f"Approve the target <b>{esc(name)}</b> to write the campaign, "
                                 "or send the strategy back.", info.unresolved)

    left, right = st.columns([3, 2], gap="large")
    with left:
        html_block(f'<p class="pm-lead">{citer.text(s.target_description)}</p>')
        rows = [("Positioning", s.positioning_statement), ("Value proposition", s.value_proposition),
                ("Pricing direction", s.pricing_direction), ("Why this target", s.rationale)]
        items = "".join(f'<li><span class="k">{esc(k)}</span>{citer.text(v)}</li>' for k, v in rows)
        items += f'<li><span class="k">Channels</span>{esc(" · ".join(s.channels))}</li>'
        html_block(f'<ul class="pm-reason">{items}</ul>')
    with right:
        st.subheader("Relies on")
        if segment:
            size, intent = parse_size(segment.estimated_size), parse_intent(segment.description)
            figures = " · ".join(x for x in [human(size) if size else None,
                                             f"{intent:g}% intent" if intent is not None else None] if x)
            html_block(f'<div class="pm-kv"><div class="k">Target segment</div><div class="v"><b style="font-weight:500">'
                       f'{esc(segment.label)}</b>{" · " + esc(figures) if figures else ""}</div>'
                       f'<div style="font-size:13px;color:var(--muted);line-height:19px;margin-top:4px">'
                       f'{citer.text(segment.description)}</div></div>')
        html_block(f'<div class="pm-kv"><div class="k">Sources the strategy cites · {len(s.supporting_source_ids)}</div>'
                   f'<div class="v">{citer.ids(s.supporting_source_ids) or "—"}</div></div>')
        decisions = view.decisions()
        if decisions:
            rows = []
            for n, d in enumerate(decisions, 1):
                word = pill("approved", "Approved") if d.get("approved") else pill("blocking", "Sent back")
                fb = f' · ‘{esc(d["feedback"])}’' if d.get("feedback") else ""
                rows.append(f'<div class="pm-issue">{word}<div class="t">Review {n}: {esc(d.get("target_segment_id", ""))}{fb}</div></div>')
            st.subheader("Your reviews")
            html_block("".join(rows))
    validator_block(view, "strategy", chosen, info)
