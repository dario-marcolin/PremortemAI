"""Screen E: the committed runs (and, in local mode, the runs in outputs/). A card opens the run
read-only: screens B to D with no key and no API call."""

import json
from pathlib import Path

import streamlit as st

from premortem.config import current_mode
from ui.theme import esc, html_block
from ui.view import ROOT, RunView

COMMITTED = [
    (ROOT / "examples" / "demo_anthropic", "Demo document · Anthropic preset"),
    (ROOT / "examples" / "demo_gemini", "Demo document · Gemini free preset"),
]


def demo_runs() -> list[tuple[Path, str]]:
    return [(p, label) for p, label in COMMITTED if (p / "state.json").exists()]


def case_runs() -> list[tuple[Path, str]]:
    cases = {c["id"]: c for c in json.loads((ROOT / "eval" / "cases" / "cases.json").read_text())}
    runs = []
    for provider in ("anthropic", "gemini"):
        for case_dir in sorted((ROOT / "eval" / "runs" / provider).glob("*/multi_agent")):
            case = cases.get(case_dir.parent.name, {})
            runs.append((case_dir, f"{case.get('category', case_dir.parent.name)} · {case.get('country', '')}"))
    return runs


def local_runs(limit: int = 12) -> list[tuple[Path, str]]:
    out = ROOT / "outputs"
    dirs = sorted((d for d in out.glob("2*") if (d / "state.json").exists()), reverse=True) if out.is_dir() else []
    return [(d, "Your run in outputs/") for d in dirs[:limit]]


@st.cache_data(show_spinner=False, max_entries=64)
def card_data(path: str, mtime: float, label: str) -> dict:
    view = RunView.from_dir(path, label)
    target = view.target
    return {"title": view.title, "provider": view.provider, "date": view.date, "document": Path(view.document).name,
            "target": f"{target.segment_id} · {target.label}" if target else "—", "status": view.status,
            "evaluated": view.metrics is not None}


def open_saved(path: Path, label: str) -> None:
    st.session_state.current = {"kind": "saved", "path": str(path), "label": label}
    st.session_state.step = None
    st.session_state.goto = "run"


def grid(runs: list[tuple[Path, str]], key: str) -> None:
    for start in range(0, len(runs), 3):  # one row of columns per three cards, so rows line up
        cols = st.columns(3, gap="medium")
        for n, (path, label) in enumerate(runs[start:start + 3], start):
            data = card_data(str(path), (path / "state.json").stat().st_mtime, label)
            with cols[n - start], st.container(border=True, key=f"card_{key}_{n}"):
                _card(path, label, data, key, n)


def _card(path: Path, label: str, data: dict, key: str, n: int) -> None:
    html_block(f'<div class="pm-run-card"><div class="doc">{esc(data["title"])}</div>'
               f'<div class="meta"><span>{esc(label)}</span><span>{esc(data["provider"])} · {esc(data["date"])} · {esc(data["document"])}</span></div>'
               f'<div class="tg"><span class="pm-label" style="display:block">Chosen target</span>{esc(data["target"])}</div></div>')
    st.button("Open run", key=f"open_{key}_{n}", on_click=open_saved, args=(path, label), width="stretch",
              icon=":material/arrow_forward:")


def page() -> None:
    html_block('<h1 style="margin:0 0 6px;padding:0">Saved runs</h1>'
               '<p class="pm-sub">Finished runs committed to the repository. They open read-only, with no key and no API call: '
               'every agent page, the blueprint and the evaluation.</p>')
    st.subheader("Demo document")
    grid(demo_runs(), "demo")
    st.subheader("Evaluation cases")
    grid(case_runs(), "cases")
    if current_mode() == "local":
        mine = local_runs()
        if mine:
            st.subheader("Your runs on this computer")
            grid(mine, "local")
