"""Streamlit UI (Phase 11): upload a company document, follow the run log, approve the strategy,
download the Launch Blueprint and read its evaluation (Phase 10 metrics, optionally against the
single-prompt baseline).

    uv run streamlit run app.py

Streamlit re-runs this script on every interaction, so the Run (compiled graph, thread, log)
lives in st.session_state. A run streams inside one script execution and the page is redrawn
after every log line. If an interaction cuts the stream short, the next execution continues
from the last checkpoint (Run.advance with no input).
"""

import html
import re
import tempfile
from pathlib import Path

import streamlit as st

from eval.baseline import run_baseline
from eval.metrics import evaluate, find_case, load_metrics, scores
from premortem import config
from premortem.ingestion.parser import ALLOWED_EXTENSIONS, DocumentParseError
from premortem.output.blueprint import validation_log
from premortem.runner import PIPELINE, LogLine, Run

ROOT = Path(__file__).resolve().parent
SAVED_DIRS = [ROOT / "data" / "demo", ROOT / "eval" / "cases"]
LABELS = {
    "extract_brief": "Brief", "analyst": "Analyst", "validate_analysis": "Check analysis",
    "strategist": "Strategist", "validate_strategy": "Check strategy", "human_approval": "Your approval",
    "creative": "Creative", "validate_campaign": "Check campaign", "blueprint": "Blueprint", "parse": "Document",
}
STAGE_ISSUE = {"blocking, unresolved": ":red-badge[blocking, unresolved]",
               "blocking, resolved": ":gray-badge[blocking, resolved]", "warning": ":orange-badge[warning]"}

CSS = """
<style>
.block-container { padding-top: 2.25rem; max-width: 1240px; }
[data-baseweb="textarea"], [data-baseweb="textarea"] textarea, [data-baseweb="select"] > div { background-color: #ffffff; }
@media (max-width: 768px) { .block-container { padding-left: 20px; padding-right: 20px; } }
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) { background: #ffffff; }
.mark { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 600; margin: 4px 0 20px; }
.subline { color: #6b6b6b; font-size: 15px; margin: -8px 0 16px; }
.track { display: flex; flex-wrap: wrap; gap: 6px 20px; list-style: none; padding: 0; margin: 0 0 24px; font-size: 13px; }
.track li { display: flex; align-items: center; gap: 7px; color: #6b6b6b; margin: 0; }
.track .dot { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid #8a8a8a; flex: none; }
.track .done { color: #0a0a0a; }
.track .done .dot { background: #141414; border-color: #141414; }
.track .current { color: #1d5fbf; font-weight: 500; }
.track .current .dot { background: #1d5fbf; border-color: #1d5fbf; }
.track .failed { color: #c4242a; font-weight: 500; }
.track .failed .dot { background: #c4242a; border-color: #c4242a; }
.track .times { color: #6b6b6b; font-weight: 400; }
.log { width: 100%; border-collapse: collapse; font-size: 13px; }
.log td { padding: 5px 0; vertical-align: top; border-bottom: 1px solid #f0f0f0; }
.log .t { width: 52px; padding-right: 12px; text-align: right; color: #6b6b6b; font-variant-numeric: tabular-nums; white-space: nowrap; }
.log .n { font-weight: 500; margin-right: 6px; }
.log .warning .x { color: #92400e; }
.log .error .x, .log .error .n { color: #c4242a; }
.log .pause .x { color: #1d5fbf; }
.log .sub td { border-bottom: none; padding: 2px 0; }
.log .sub .x { color: #3d3d3d; }
.log .sub.results .x { color: #6b6b6b; padding-left: 14px; }
</style>
"""
MARK = """<div class="mark"><svg width="22" height="10" viewBox="0 0 22 10" aria-hidden="true">
<circle cx="4" cy="5" r="3.2" fill="#141414"/><circle cx="11" cy="5" r="3.2" fill="#141414"/>
<circle cx="18" cy="5" r="2.6" fill="none" stroke="#141414" stroke-width="1.3"/></svg>PremortemAI</div>"""


def saved_documents() -> list[Path]:
    return sorted(p for d in SAVED_DIRS if d.is_dir() for p in d.iterdir() if p.suffix.lower() in ALLOWED_EXTENSIONS)


def missing_keys() -> list[str]:
    return [name for name, value in (("LLM_API_KEY", config.LLM_API_KEY), ("TAVILY_API_KEY", config.TAVILY_API_KEY))
            if not value]


def start_run(upload, saved: Path | None) -> None:
    st.session_state.start_error = st.session_state.eval_error = None
    if upload is not None:
        # The parser takes a path: keep the original name, so the run id names the document
        path = Path(tempfile.mkdtemp(prefix="premortem_")) / upload.name
        path.write_bytes(upload.getvalue())
    else:
        path = saved
    try:
        st.session_state.run = Run(path)
    except DocumentParseError as e:
        st.session_state.start_error = str(e)


def answer(approved: bool) -> None:
    feedback = st.session_state.get("feedback", "").strip()
    st.session_state.run.answer({"approved": True} if approved else {"approved": False, "feedback": feedback})
    st.session_state.feedback = ""


def retry() -> None:
    st.session_state.run.error = None


def request_evaluation(system: str) -> None:
    """Asked from a button; run_evaluation does the work in the next script run, under a spinner."""
    st.session_state.eval_request = system
    st.session_state.eval_error = None


def run_evaluation(run: Run, system: str) -> None:
    """Score the blueprint (multi_agent), or write and score the single-prompt plan (baseline)."""
    case = find_case(run.document)
    out_dir = run.dir if system == "multi_agent" else run.dir / "baseline"
    try:
        if system == "baseline":
            run_baseline(run.document, out_dir)
        evaluate(out_dir, run.document_text, case and case.get("trap"))
    except Exception as e:  # the result stays on screen; the tab shows the error
        st.session_state.eval_error = f"{type(e).__name__}: {e}"


# ── header: title, status line, pipeline track ──────────────────────────────────────────

def status_line(run: Run) -> str:
    state = run.state
    if run.status == "waiting":
        target = run.pending["strategy"]["target_segment_id"]
        segment = state["analysis"].find_segment(target)
        return f"Waiting for your approval: the Strategist targets {target}, {segment.label if segment else 'unknown segment'}."
    if run.status == "done":
        return f"Done in {run.seconds:.0f} s of pipeline time. Saved to outputs/{run.run_id}/."
    if run.status == "failed":
        return f"Stopped at {LABELS.get(run.log[-1].node, run.log[-1].node)}: {run.error}"
    step = next(iter(run.next_nodes), "extract_brief")
    return f"{LABELS[step]} is working. {run.log[-1].seconds:.0f} s so far." if run.log else "Reading the document."


def track(run: Run) -> str:
    runs = {node: sum(1 for l in run.log if l.node == node and l.kind == "node") for node in PIPELINE}
    current = set(run.next_nodes) if run.status in ("running", "waiting", "failed") else set()
    if run.status == "running" and not run.log:
        current = {"extract_brief"}
    items = []
    for node in PIPELINE:
        cls = ("failed" if run.status == "failed" else "current") if node in current else "done" if runs[node] else ""
        times = f' <span class="times">×{runs[node]}</span>' if runs[node] > 1 else ""
        items.append(f'<li class="{cls}"><span class="dot"></span>{LABELS[node]}{times}</li>')
    return f'<ol class="track" aria-label="Pipeline steps">{"".join(items)}</ol>'


def header(run: Run) -> None:
    brief = run.state.get("brief")
    st.title(f"{brief.product_name} launch" if brief else run.document.name)
    st.markdown(f'<p class="subline">{html.escape(status_line(run))}</p>', unsafe_allow_html=True)
    st.markdown(track(run), unsafe_allow_html=True)


# ── run log ─────────────────────────────────────────────────────────────────────────────

def _rows(lines: list[LogLine], sub: bool = False) -> str:
    rows = []
    for l in lines:
        text = html.escape(("→ " if l.kind == "results" else "") + l.text)
        node = "" if sub else f'<span class="n">{html.escape(LABELS.get(l.node, l.node))}</span>'
        rows.append(f'<tr class="{l.kind}{" sub" if sub else ""}"><td class="t">{l.seconds:.0f} s</td>'
                    f'<td class="x">{node}{text}</td></tr>')
    return f'<table class="log">{"".join(rows)}</table>'


def run_log(run: Run) -> None:
    st.subheader(f"Run log · {len(run.log)} lines")
    # Consecutive searches and their results fold into one expander
    blocks: list[tuple[bool, list[LogLine]]] = []
    for line in run.log:
        is_search = line.kind in ("search", "results")
        if blocks and blocks[-1][0] == is_search:
            blocks[-1][1].append(line)
        else:
            blocks.append((is_search, [line]))
    if not blocks:
        st.caption("Each step appears here as it finishes.")
    for is_search, lines in blocks:
        if is_search:
            searching = run.status == "running" and lines is blocks[-1][1]
            with st.expander(f"Analyst searches · {sum(l.kind == 'search' for l in lines)}", expanded=searching):
                st.markdown(_rows(lines, sub=True), unsafe_allow_html=True)
        else:
            st.markdown(_rows(lines), unsafe_allow_html=True)
    st.caption(f"Also written to outputs/{run.run_id}/log.txt")


# ── main panel ──────────────────────────────────────────────────────────────────────────

def brief_card(brief) -> None:
    with st.container(border=True):
        st.subheader("Company brief")
        st.markdown(f"**{brief.company_name}** · {brief.product_name} · {brief.target_country}"
                    f"{' · ' + brief.price_hint if brief.price_hint else ''}")
        st.write(brief.product_description)
        if brief.stated_goals:
            st.markdown("Goals: " + "; ".join(brief.stated_goals))
        if brief.missing_info:
            st.caption("Missing from the document: " + "; ".join(brief.missing_info))


def segments_table(analysis, target_id: str | None = None) -> None:
    st.dataframe(
        [{"": "→" if s.segment_id == target_id else "", "Id": s.segment_id, "Segment": s.label,
          "Estimated size": s.estimated_size or "—", "Needs": "; ".join(s.needs),
          "Sources": ", ".join(s.source_ids) or "—"} for s in analysis.segments],
        hide_index=True, width="stretch",
    )


def progress_view(run: Run) -> None:
    state = run.state
    if not state.get("brief"):
        with st.container(border=True):
            st.subheader("Company brief")
            st.caption("The brief appears here when the extractor has read the document.")
        return
    brief_card(state["brief"])
    if state.get("analysis"):
        with st.container(border=True):
            a = state["analysis"]
            st.subheader(f"Market analysis · {len(a.competitors)} competitors, {len(a.sources)} sources")
            segments_table(a, state["strategy"].target_segment_id if state.get("strategy") else None)


def issues_list(issues: list[tuple[str, str, str]]) -> None:
    """(badge markdown, check, message) rows."""
    if not issues:
        st.caption("No issues.")
    for badge, check, message in issues:
        st.markdown(f"{badge} **{check}**: {message}")


def approval_panel(run: Run) -> None:
    payload, analysis = run.pending, run.state["analysis"]
    s = payload["strategy"]
    segment = analysis.find_segment(s["target_segment_id"])
    with st.container(border=True):
        st.subheader("Approve the strategy")
        st.markdown(f"### {s['target_segment_id']} · {segment.label if segment else 'segment not in the analysis'}")
        st.caption(f"Estimated size: {segment.estimated_size or '—'}" if segment else "")
        st.write(s["target_description"])
        for label, key in (("Positioning", "positioning_statement"), ("Value proposition", "value_proposition"),
                           ("Pricing", "pricing_direction"), ("Rationale", "rationale")):
            st.markdown(f"**{label}**  \n{s[key]}")
        st.markdown(f"**Channels**  \n{', '.join(s['channels'])}")
        st.caption(f"Sources: {', '.join(s['supporting_source_ids'])}")

        st.markdown(f"**Validation issues** · after {payload['strategy_revisions']} revision(s)")
        if payload["unresolved"]:
            st.warning("Blocking issues are still unresolved: the revision limit was reached.")
        issues_list([(":red-badge[blocking]" if i["severity"] == "blocking" else ":orange-badge[warning]",
                      i["check"], i["message"]) for i in payload["issues"]])

        st.text_area("Feedback for the Strategist", key="feedback", height=90,
                     help="Only needed to reject. Say what to change, e.g. a different target or channel.")
        approve, reject, _ = st.columns([1, 1, 1])
        approve.button("Approve strategy", type="primary", on_click=answer, args=(True,), width="stretch")
        reject.button("Reject with feedback", on_click=answer, args=(False,), width="stretch")
    with st.expander("Company brief and market analysis"):
        brief_card(run.state["brief"])
        segments_table(analysis, s["target_segment_id"])


def result_panel(run: Run) -> None:
    state = run.state
    path = run.dir / "blueprint.md"
    blueprint = path.read_text() if path.exists() else ""
    download, record, _ = st.columns([1.2, 1, 1.6])
    download.download_button("Download blueprint.md", blueprint, file_name=f"{run.run_id}_blueprint.md",
                             mime="text/markdown", type="primary", width="stretch", disabled=not blueprint)
    record.download_button("Download state.json", (run.dir / "state.json").read_text(),
                           file_name=f"{run.run_id}_state.json", mime="application/json", width="stretch")
    tab_blueprint, tab_segments, tab_log, tab_eval = st.tabs(["Blueprint", "Segments", "Validation log", "Evaluation"])
    with tab_blueprint, st.container(border=True):
        # One h1 per screen: the blueprint's headings move down one level
        st.markdown(re.sub(r"^#", "##", blueprint, flags=re.M) or "No blueprint was written.")
    with tab_segments:
        segments_table(state["analysis"], state["strategy"].target_segment_id)
        for note in state["analysis"].data_quality_notes:
            st.caption(note)
    with tab_log:
        for entry in validation_log(state):
            r = entry["result"]
            st.markdown(f"**{r.stage.capitalize()}, check {entry['attempt']}** · {'passed' if r.passed else 'failed'}")
            issues_list([(STAGE_ISSUE[status], i.check, i.message) for i, status in entry["issues"]])
    with tab_eval:
        evaluation_tab(run)


# ── evaluation (Phase 10 metrics) ───────────────────────────────────────────────────────

def _pct(x) -> str:
    return "—" if x is None else f"{x:.0%}"


def _delta(ours, theirs, fmt) -> str | None:
    return None if ours is None or theirs is None else f"{fmt(ours - theirs)} vs single prompt"


def metric_tiles(m: dict, b: dict | None) -> None:
    """The headline scores of the blueprint; with the baseline, the difference under each one."""
    ours, theirs = scores(m), scores(b) if b else {}
    tiles = [
        ("Traceability", _pct(ours["traceability"]), "Claims about the market with a valid source",
         _delta(ours["traceability"], theirs.get("traceability"), lambda d: f"{d * 100:+.0f} pts"), "normal"),
        ("Faithfulness", _pct(ours["faithfulness"]), "Figures found in the document or in a cited source",
         _delta(ours["faithfulness"], theirs.get("faithfulness"), lambda d: f"{d * 100:+.0f} pts"), "normal"),
        ("Strategy vs analysis", f"{ours['coherence_strategy'] or '—'} / 5", "Coherence, LLM judge with a fixed rubric",
         _delta(ours["coherence_strategy"], theirs.get("coherence_strategy"), lambda d: f"{d:+d}"), "normal"),
        ("Campaign vs strategy", f"{ours['coherence_campaign'] or '—'} / 5", "Coherence, LLM judge with a fixed rubric",
         _delta(ours["coherence_campaign"], theirs.get("coherence_campaign"), lambda d: f"{d:+d}"), "normal"),
        ("Tokens", f"{ours['tokens']:,}" if ours["tokens"] is not None else "—", "All models of the run",
         _delta(ours["tokens"], theirs.get("tokens"), lambda d: f"{d:+,}"), "inverse"),
        ("Pipeline time", f"{ours['seconds']:.0f} s" if ours["seconds"] is not None else "—", "Human wait excluded",
         _delta(ours["seconds"], theirs.get("seconds"), lambda d: f"{d:+.0f} s"), "inverse"),
    ]
    for row in (tiles[:3], tiles[3:]):
        for col, (label, value, help_text, delta, color) in zip(st.columns(3), row):
            col.metric(label, value, delta=delta, delta_color=color, help=help_text, border=True)


def evaluation_details(m: dict) -> None:
    t, f = m["traceability"], m["faithfulness"]
    with st.expander(f"Claims · {t['traced']} of {t['claims']} with a valid source"):
        st.dataframe([{"Claim": i["quote"], "References": ", ".join(i["refs"]) or "—", "Valid source": i["traced"]}
                      for i in t["items"]], hide_index=True, width="stretch")
        if t["unquoted"]:
            st.caption(f"{t['unquoted']} claim(s) left out: the judge's quote is not in the plan.")
    with st.expander(f"Figures · {f['matched']} of {f['checked']} found, {f['unverifiable']} unverifiable"):
        st.dataframe([{"Figure": i["figure"], "Found in": i["status"], "Claim": i["quote"]} for i in f["items"]],
                     hide_index=True, width="stretch")
        st.caption("Unverifiable: a cited page could not be read; these figures are not in the score.")
    with st.expander(f"Sources · {sum(s['valid'] for s in m['sources'])} of {len(m['sources'])} valid"):
        st.dataframe([{"#": s["number"], "Reference": s["reference"], "Status": s["status"], "Valid": s["valid"]}
                      for s in m["sources"]], hide_index=True, width="stretch")


def evaluation_tab(run: Run) -> None:
    m, b = load_metrics(run.dir), load_metrics(run.dir / "baseline")
    if st.session_state.get("eval_error"):
        st.error(f"The evaluation stopped: {st.session_state.eval_error}")
    if m is None:
        st.caption("Scores the blueprint: traceability, faithfulness of the figures, coherence. "
                   "Two calls to the judge model; the pages of the cited sources are opened.")
        st.button("Evaluate this run", type="primary", on_click=request_evaluation, args=("multi_agent",))
        return
    if m.get("error"):
        st.error(f"Not evaluated: {m['error']}")
        return
    metric_tiles(m, b if b and not b.get("error") else None)

    for label, key in (("Strategy vs analysis", "strategy_vs_analysis"), ("Campaign vs strategy", "campaign_vs_strategy")):
        score = m["coherence"][key]
        st.markdown(f"**{label} · {score['score']}/5.** {score['reason']}")
    trap = m["trap"]
    if trap["applies"]:
        verdict = ":green-badge[trap avoided]" if trap["avoided"] else ":red-badge[trap segment targeted]"
        st.markdown(f"{verdict} The plan targets *{trap['target']}*. Trap segment of this case: {trap['segment']}.")
    evaluation_details(m)

    if b is None:
        st.button("Compare with the single-prompt baseline", on_click=request_evaluation, args=("baseline",),
                  help="Same model, same document, one prompt asking for the full plan (no tools, no validator).")
    elif b.get("error"):
        st.error(f"Baseline: {b['error']}")
    else:
        with st.expander("Single-prompt plan (baseline) and its scores"):
            evaluation_details(b)
            plan = (run.dir / "baseline" / "blueprint.md").read_text()
            st.markdown(re.sub(r"^#", "##", plan, flags=re.M))
    st.caption(f"Judge: {config.JUDGE_MODEL}, rubric in eval/prompts/coherence.md; references and figures are "
               f"checked in code. Saved to outputs/{run.run_id}/metrics.json.")


def main_panel(run: Run) -> None:
    if run.status == "waiting":
        approval_panel(run)
    elif run.status == "done":
        result_panel(run)
    else:
        if run.status == "failed":
            with st.container(border=True):
                st.error(f"The run stopped: {run.error}")
                st.caption(f"The traceback is in outputs/{run.run_id}/log.txt. "
                           "Retry continues from the last finished step.")
                st.button("Retry", type="primary", on_click=retry)
        progress_view(run)


# ── page ────────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="PremortemAI", layout="wide")
st.html(CSS)

with st.sidebar:
    st.markdown(MARK, unsafe_allow_html=True)
    upload = st.file_uploader("Company data", type=[e.lstrip(".") for e in sorted(ALLOWED_EXTENSIONS)],
                              help="The company or product document. Text must be selectable (no scans).")
    docs = saved_documents()
    saved = st.selectbox("Or a saved document", docs, index=None, placeholder="data/demo, eval/cases",
                         format_func=lambda p: str(p.relative_to(ROOT)), disabled=upload is not None)
    missing = missing_keys()
    if missing:
        st.error(f"Missing in .env: {', '.join(missing)}. Copy .env.example to .env and fill it in.")
    st.button("Run the pipeline", type="primary", width="stretch", on_click=start_run, args=(upload, saved),
              disabled=bool(missing) or (upload is None and saved is None))
    if st.session_state.get("start_error"):
        st.error(st.session_state.start_error)
    st.toggle("Evaluate the result", value=True, key="auto_eval",
              help="When the run ends, score the blueprint (Phase 10 metrics). Two calls to the judge model.")
    st.caption(f"Agents: {config.LLM_MODEL}  \nJudge: {config.JUDGE_MODEL}")

run: Run | None = st.session_state.get("run")
if run is None:
    st.title("New launch run")
    st.markdown('<p class="subline">Add the company document in the sidebar, then run the pipeline.</p>',
                unsafe_allow_html=True)
    st.markdown('<ol class="track">' + "".join(
        f'<li><span class="dot"></span>{LABELS[n]}</li>' for n in PIPELINE) + "</ol>", unsafe_allow_html=True)
    left, right = st.columns([5, 3], gap="medium")
    with left, st.container(border=True):
        st.subheader("What happens")
        st.markdown("The brief is extracted from the document, the Analyst researches the market on the web, "
                    "and the Strategist picks a target segment. Each output is checked by the validator and "
                    "revised up to twice. You approve or reject the strategy, then the Creative writes the "
                    "campaign and the Launch Blueprint is saved.")
    with right, st.container(border=True):
        st.subheader("Run log")
        st.caption("Each step appears here as it finishes.")
    st.stop()

top = st.empty()
left, right = st.columns([5, 3], gap="medium")
with left:
    main_box = st.empty()
with right:
    log_box = st.empty()


def redraw_live() -> None:
    with top.container():
        header(run)
    with log_box.container(border=True):
        run_log(run)


if run.status == "running":
    redraw_live()
    with main_box.container():
        progress_view(run)
    for line in run.advance():
        redraw_live()
        if line.kind == "node":
            with main_box.container():
                progress_view(run)
    st.rerun()

with top.container():
    header(run)
with log_box.container(border=True):
    run_log(run)

if run.status == "done":
    request = st.session_state.pop("eval_request", None)
    if (request is None and st.session_state.get("auto_eval", True) and not st.session_state.get("eval_error")
            and load_metrics(run.dir) is None):
        request = "multi_agent"
    if request:
        with main_box.container(), st.spinner("Writing the single-prompt plan and scoring it…" if request == "baseline"
                                              else "Evaluating the blueprint: claims, figures, coherence…"):
            run_evaluation(run, request)

with main_box.container():
    main_panel(run)
