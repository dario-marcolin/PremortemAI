"""PremortemAI, the Streamlit UI (Phase 15): routing only. The screens are in ui/.

    uv run streamlit run app.py

A: New run (ui/setup.py) · B: the run workspace with its timeline (ui/workspace.py) · C: the blueprint
reader · D: evaluation of a run and the Phase 14 results (ui/evaluation.py) · E: saved runs · F: how it
works. Live runs work in a background thread (ui/live.py); every screen reads a RunView (ui/view.py),
so live and saved runs share the same views.
"""

import streamlit as st

from premortem.config import RunSettings, current_mode
from premortem.providers import PRESETS
from ui import evaluation, how_it_works, saved_runs, setup, theme, workspace
from ui.theme import esc
from ui.view import ROOT

st.set_page_config(page_title="PremortemAI", page_icon="ui/assets/mark.svg", layout="wide",
                   initial_sidebar_state="auto")
theme.apply()

pages = {
    "new": st.Page(setup.page, title="New run", url_path="new", default=True),
    "run": st.Page(workspace.page, title="Run", url_path="run"),
    "saved": st.Page(saved_runs.page, title="Saved runs", url_path="saved"),
    "evaluation": st.Page(evaluation.results_page, title="Evaluation", url_path="evaluation"),
    "how": st.Page(how_it_works.page, title="How it works", url_path="how"),
}
st.session_state.pages = pages

# A link to a saved run: ?saved=examples/demo_anthropic (and &step=analysis), e.g. shared after the talk
saved = st.query_params.get("saved")
if saved and st.session_state.get("opened_link") != (saved, st.query_params.get("step")):
    st.session_state.opened_link = (saved, st.query_params.get("step"))
    path = (ROOT / saved).resolve()
    if path.is_relative_to(ROOT) and (path / "state.json").exists():
        st.session_state.current = {"kind": "saved", "path": str(path), "label": None}
        step = st.query_params.get("step")
        st.session_state.step = step if step in workspace.ITEMS else None
        if st.session_state.get("_page") != "run":
            st.session_state.goto = "run"
goto = st.session_state.pop("goto", None)
if goto:
    st.switch_page(pages[goto])

st.navigation(list(pages.values()), position="top").run()

# Top bar, right (fixed position, so it is drawn last): which model access this session has
label = st.session_state.get("provider_label")
mode = current_mode()
if label is None and mode == "local" and "provider_label" not in st.session_state:
    try:
        settings = RunSettings.from_env(mode="local")
        label = (PRESETS[settings.provider].label.split(" (")[0] if settings.provider in PRESETS else settings.provider) \
            if settings.llm_api_key else None
    except ValueError:
        label = None
state = (f"{label} · {'key from .env' if mode == 'local' else 'your key'}" if label
         else "No key · saved runs only")
st.html(f'<div class="pm-topright"><span class="dot{"" if label else " off"}"></span>{esc(state)}</div>')

