"""Screen B, the run workspace: the timeline in the sidebar, the selected step in the sheet.

While the pipeline works (in its own thread, ui/live.py), a small fragment ticks every second: it
shows what is happening now and the time, and reruns the page when a new step or search arrives.
The review panel appears under the step that waits for you, and the timeline jumps to it."""

import streamlit as st

from premortem.llm import explain_error
from ui import blueprint_reader, evaluation
from ui.citations import Citer
from ui.steps import analysis, brief, campaign, strategy
from ui.theme import esc, html_block, icon
from ui.view import STEP_LABELS, STEPS, RunView

ITEMS = [*STEPS, "evaluation"]


def current_view() -> tuple[RunView | None, object]:
    current = st.session_state.get("current")
    if not current:
        return None, None
    if current["kind"] == "live" and st.session_state.get("live"):
        live = st.session_state.live
        return RunView.from_live(live), live
    if current["kind"] == "saved":
        return saved_view(current["path"], current.get("label")), None
    return None, None


@st.cache_resource(show_spinner=False, max_entries=16)
def saved_view(path: str, label: str | None) -> RunView:
    return RunView.from_dir(path, label)


def _select(key: str) -> None:
    st.session_state.step = key
    st.session_state.followed = None


def mmss(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def timeline(view: RunView, live, selected: str) -> None:
    sub = " · ".join(x for x in [view.provider, view.date, "read-only" if not view.live else None] if x)
    html_block(f'<div class="pm-run-name">{esc(view.title)}</div><div class="pm-run-meta">{esc(sub)}</div>')
    for key in ITEMS:
        if key == "evaluation":
            m = view.metrics
            status = "done" if m and not m.get("error") else "pending"
            note = "Scored against the single prompt" if m and view.baseline else ("Scored" if m else "Not evaluated")
            if live is not None and live.evaluating:
                status, note = "running", "Scoring the blueprint…"
        else:
            info = view.step(key)
            status = info.status
            note = _note(view, info)
        sel = "_sel" if key == selected else ""
        with st.container(key=f"tl_{status}_{key}{sel}", gap=None):
            st.button(STEP_LABELS[key], icon=icon(status), key=f"tlb_{key}", on_click=_select, args=(key,),
                      width="stretch", help=None)
            if note:
                html_block(f'<div class="pm-tl-note">{esc(note)}</div>')
    meter(view, live)


def _note(view: RunView, info) -> str:
    parts = []
    if info.status == "running":
        return "Working now"
    if info.status == "review":
        return "Waiting for your review"
    if info.status == "failed":
        return "Stopped here"
    if info.rounds > 1:
        parts.append(f"{info.rounds} rounds")
    if info.unresolved:
        parts.append("revision limit reached")
    elif info.warnings:
        parts.append(f"{info.warnings} warning{'s' if info.warnings > 1 else ''}")
    if info.status == "approved":
        parts.insert(0, "approved by you")
    return " · ".join(parts).capitalize() if parts else ""


def meter(view: RunView, live) -> None:
    tokens = f"{view.tokens:,}" if view.tokens else "—"
    html_block(f'<div class="pm-meter"><div class="row"><span>Pipeline time</span><b>{mmss(view.seconds)}</b></div>'
               f'<div class="row"><span>Tokens</span><b>{tokens}</b></div>'
               f'<div class="row"><span>Searches</span><b>{len(view.searches)}</b></div></div>')
    if live is None:
        st.button("Start a new run", key="new_from_saved", icon=":material/add:", width="stretch",
                  on_click=lambda: st.session_state.update(goto="new"))
        return
    if live.busy:
        st.button("Stopping…" if live.stopping else "Stop", key="stop", icon=":material/stop:", width="stretch",
                  disabled=live.stopping, on_click=live.stop,
                  help="Stops after the current step. You can resume from there.")
    elif view.status in ("stopped", "failed"):
        st.button("Resume" if view.status == "stopped" else "Retry from the last step", key="resume",
                  icon=":material/play_arrow:", type="primary", width="stretch", on_click=live.start)


def status_banner(view: RunView, live) -> None:
    """The line over the step view: what is happening now, never a silent wait."""
    if live is None:
        return
    if view.status == "failed":
        provider = view.provider
        st.error(f"**The run stopped at the {STEP_LABELS.get(view.current_step() or '', 'pipeline').lower()}.** "
                 f"{explain_error(Exception(view.error or ''), provider)}  \nThe steps already done are kept: "
                 "Retry continues from the last finished step. The full error is in log.txt.")
    elif view.status == "stopped":
        html_block('<div class="pm-notice info">Paused by you. Resume continues from the last finished step.</div>')
    search_trouble = [l for l in view.log if l.node == "analyst" and l.kind == "warning"]
    if search_trouble:
        quota = any(w in l.text.lower() for l in search_trouble for w in ("quota", "limit", "432", "429", "credits"))
        html_block('<div class="pm-notice">' + ("Web search unavailable (the search quota is used up): the agents "
                   "are working from the document only." if quota else
                   f"Web search had {len(search_trouble)} problem{'s' if len(search_trouble) > 1 else ''}: "
                   f"{esc(search_trouble[-1].text[:160])}") + "</div>")
    if live.eval_error:
        st.warning(f"The evaluation stopped: {explain_error(Exception(live.eval_error), view.provider)}")


@st.fragment(run_every=1.0)
def ticker() -> None:
    """While the pipeline works: what is happening now and the time; a rerun when something changed."""
    live = st.session_state.get("live")
    if live is None:
        return
    version = live.version()
    if st.session_state.get("seen_version") != version:
        st.session_state.seen_version = version
        st.rerun(scope="app")
    if not live.busy:
        return
    view_now = RunView.from_live(live)
    html_block(f'<div class="pm-now"><span class="pm-pill running" style="margin-right:8px">'
               f'<svg viewBox="0 0 12 12" aria-hidden="true" style="animation:pm-spin 1.4s linear infinite">'
               f'<path d="M6 1.5a4.5 4.5 0 1 1-4.5 4.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
               f'</svg>{mmss(live.elapsed)}</span>{esc(view_now.now() if not live.evaluating else "Evaluation · scoring the blueprint")}</div>')


def empty() -> None:
    html_block('<h1 style="margin:0 0 6px;padding:0">No run open</h1>'
               '<p class="pm-sub">Start a run on a document, or open a saved run: no key needed.</p>')
    a, b, _ = st.columns([1, 1, 3])
    a.button("New run", type="primary", icon=":material/add:", on_click=lambda: st.session_state.update(goto="new"),
             width="stretch")
    b.button("Saved runs", icon=":material/folder_open:", on_click=lambda: st.session_state.update(goto="saved"),
             width="stretch")


def page() -> None:
    view, live = current_view()
    if view is None:
        empty()
        return
    # The timeline follows the run: it jumps to the step that works or waits, until you pick one yourself
    follow = view.current_step() or ("blueprint" if view.status == "done" else "brief")
    if st.session_state.get("step") is None or (view.live and st.session_state.get("followed") == st.session_state.get("step")):
        st.session_state.step = follow
        st.session_state.followed = follow
    if view.status == "waiting" and st.session_state.get("jumped_review") != view.run_id + str(len(view.decisions())):
        st.session_state.step = "strategy"
        st.session_state.jumped_review = view.run_id + str(len(view.decisions()))
    selected = st.session_state.step

    with st.sidebar:
        timeline(view, live, selected)
    if live is not None and (live.busy or live.evaluating):
        ticker()
    status_banner(view, live)

    citer = Citer(view)
    if selected == "evaluation":
        evaluation.run_tab(view, live)
    elif selected == "blueprint":
        blueprint_reader.render(view)
    else:
        info = view.step(selected)
        {"brief": lambda: brief.render(view, info), "analysis": lambda: analysis.render(view, info, citer),
         "strategy": lambda: strategy.render(view, info, citer),
         "campaign": lambda: campaign.render(view, info, citer)}[selected]()
