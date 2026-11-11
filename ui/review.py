"""The review panel under a step that waits for you (roadmap 15.5): approve, or send it back with
feedback. Suggestion chips fill the text area; they never send it."""

import streamlit as st

from ui.theme import esc, html_block

SUGGESTIONS = {
    "strategy": ["Target a bigger segment", "Cheaper positioning", "Use fewer channels",
                 "Explain the price with competitor figures"],
    "analysis": ["Search for competitor prices", "Find a source for the market size", "Add a segment for students"],
    "campaign": ["Make the messages shorter", "Use the language of the target country", "One message per channel"],
}
RERUNS = {"analysis": "the analysis, the strategy and the campaign",
          "strategy": "the strategy and the campaign", "campaign": "the campaign"}


def _approve(step: str) -> None:
    st.session_state.live.answer(True)
    st.session_state[f"feedback_{step}"] = ""


def _reject(step: str) -> None:
    feedback = st.session_state.get(f"feedback_{step}", "")
    st.session_state.live.answer(False, feedback)
    st.session_state[f"feedback_{step}"] = ""


def _suggest(step: str, text: str) -> None:
    key = f"feedback_{step}"
    current = (st.session_state.get(key) or "").strip()
    st.session_state[key] = f"{current} {text}." if current else f"{text}."


def panel(step: str, summary: str, unresolved: bool) -> None:
    with st.container(border=True, key=f"review_{step}"):
        html_block(f'<h2 style="font-size:16px;margin:0 0 4px;padding:0">Your review</h2>'
                   f'<p class="pm-sub" style="margin:0 0 14px">{summary}</p>')
        if unresolved:
            html_block('<div class="pm-notice">The Validator could not fix every blocking issue within the revision '
                       'limit. You can still approve, or send it back with what to change.</div>')
        approve, _ = st.columns([1, 2])
        approve.button("Approve and continue", type="primary", icon=":material/check:", on_click=_approve,
                       args=(step,), key=f"approve_{step}", width="stretch")
        st.text_area("Or send it back with feedback", key=f"feedback_{step}", height=96,
                     placeholder="What should change? For example: target a segment with more buyers.")
        with st.container(horizontal=True, gap="small"):
            for n, text in enumerate(SUGGESTIONS.get(step, [])):
                st.button(text, key=f"chip_{step}_{n}", on_click=_suggest, args=(step, text), type="tertiary")
        send, note = st.columns([1, 2], vertical_alignment="center")
        send.button("Send back", icon=":material/undo:", on_click=_reject, args=(step,), key=f"reject_{step}",
                    width="stretch")
        note.caption(f"Sending back re-runs {esc(RERUNS[step])}.")
