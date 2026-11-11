"""The theme (ui/theme.css) and the one visual language for status: the same icon, colour and word
for a status in the timeline, the step view and the badges (roadmap 15.7)."""

import html
from pathlib import Path

import streamlit as st

CSS = (Path(__file__).parent / "theme.css").read_text()
ASSETS = Path(__file__).parent / "assets"

# status -> (word, Material icon for buttons, inline SVG path for pills)
STATUS = {
    "pending":  ("Not started", ":material/radio_button_unchecked:", '<circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/>'),
    "running":  ("Working", ":material/progress_activity:", '<path d="M6 1.5a4.5 4.5 0 1 1-4.5 4.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'),
    "review":   ("Waiting for you", ":material/front_hand:", '<circle cx="6" cy="6" r="5" fill="currentColor"/>'),
    "done":     ("Done", ":material/check_circle:", '<path d="M2.2 6.3 4.8 8.8 9.8 3.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'),
    "approved": ("Approved by you", ":material/verified:", '<path d="M2.2 6.3 4.8 8.8 9.8 3.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'),
    "warning":  ("Warnings", ":material/warning:", '<path d="M6 1.2 11 10.5H1Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M6 4.6v2.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>'),
    "blocking": ("Blocking", ":material/block:", '<circle cx="6" cy="6" r="4.6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M2.8 9.2 9.2 2.8" stroke="currentColor" stroke-width="1.5"/>'),
    "limit":    ("Revision limit reached", ":material/block:", '<circle cx="6" cy="6" r="4.6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M2.8 9.2 9.2 2.8" stroke="currentColor" stroke-width="1.5"/>'),
    "failed":   ("Failed", ":material/cancel:", '<path d="M3 3l6 6M9 3 3 9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'),
    "stopped":  ("Stopped", ":material/pause_circle:", '<path d="M4.2 2.8v6.4M7.8 2.8v6.4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'),
}


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def pill(status: str, word: str | None = None) -> str:
    label, _, svg = STATUS[status]
    cls = "pending" if status == "stopped" else status
    return (f'<span class="pm-pill {cls}"><svg viewBox="0 0 12 12" aria-hidden="true">{svg}</svg>'
            f'{esc(word or label)}</span>')


def icon(status: str) -> str:
    return STATUS[status][1]


def apply() -> None:
    st.html(f"<style>{CSS}</style>")
    st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "logo.svg"), size="large")


def html_block(markup: str) -> None:
    """Our own markup (escaped where it holds data): one call, so Streamlit adds no spacing inside."""
    st.markdown(markup, unsafe_allow_html=True)
