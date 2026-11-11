"""Screen D. D1: the evaluation of one run against the single-prompt baseline (metrics.json, so a
saved run needs no key). D2: the Phase 14 results, read from eval/results.json and eval/findings.md;
the UI never re-runs the evaluation."""

import json
import re

import streamlit as st

from eval.metrics import scores, spread
from ui.theme import esc, html_block, pill
from ui.view import ROOT, RunView

RESULTS = ROOT / "eval" / "results.json"
FINDINGS = ROOT / "eval" / "findings.md"
METRICS = [  # key, label, caption, format, higher is better
    ("traceability", "Traceability", "Claims about the market with a valid source", "pct", True),
    ("faithfulness", "Faithfulness", "Figures found in the document or in a cited source", "pct", True),
    ("coherence_strategy", "Strategy vs analysis", "Coherence, LLM judge, fixed rubric (1–5)", "score", True),
    ("coherence_campaign", "Campaign vs strategy", "Coherence, LLM judge, fixed rubric (1–5)", "score", True),
]


def fmt(value, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value:.0%}"
    if kind == "score":
        return f"{value:.1f}<small>/ 5</small>"
    if kind == "tokens":
        return f"{value:,.0f}"
    if kind == "seconds":
        return f"{value:.0f}<small>s</small>"
    return str(value)


def delta(ours, theirs, kind: str, higher_better: bool) -> str:
    if ours is None or theirs is None:
        return ""
    d = ours - theirs
    text = f"{d * 100:+.0f} pts" if kind == "pct" else f"{d:+.1f}" if kind == "score" else \
        f"{d:+,.0f}" if kind == "tokens" else f"{d:+.0f} s"
    if abs(d) < (0.005 if kind == "pct" else 0.05 if kind == "score" else 0.5):
        return '<div class="d flat">Tie with the single prompt</div>'
    better = (d > 0) == higher_better
    return f'<div class="d {"up" if better else "down"}">{text} vs single prompt</div>'


def kpi_strip(ours: dict, theirs: dict | None, ranges: dict | None = None) -> None:
    cells = []
    for key, label, caption, kind, hb in METRICS:
        r = (ranges or {}).get(key)
        rng = f" · range {fmt(r[0], kind).split('<')[0]}–{fmt(r[1], kind).split('<')[0]}" if r else ""
        cells.append(f'<div><div class="l">{esc(label)}</div><div class="v">{fmt(ours.get(key), kind)}</div>'
                     f'{delta(ours.get(key), (theirs or {}).get(key), kind, hb)}<div class="c">{esc(caption)}{rng}</div></div>')
    html_block(f'<div class="pm-kpis" style="--n:4">{"".join(cells)}</div>')


def cost_line(ours: dict, theirs: dict | None) -> str:
    parts = [f"<b>{fmt(ours.get('tokens'), 'tokens')}</b> tokens", f"<b>{fmt(ours.get('seconds'), 'seconds').replace('<small>s</small>', ' s')}</b> of pipeline time"]
    if theirs and theirs.get("tokens"):
        parts.append(f"the single prompt used {fmt(theirs.get('tokens'), 'tokens')} tokens "
                     f"in {fmt(theirs.get('seconds'), 'seconds').replace('<small>s</small>', ' s')}")
    return " · ".join(parts)


# ── D1: this run ────────────────────────────────────────────────────────────────────────

def run_tab(view: RunView, live=None) -> None:
    m, b = view.metrics, view.baseline
    html_block('<h1 style="margin:0 0 6px;padding:0">Evaluation</h1>')
    if st.session_state.get("eval_error"):
        st.error(f"The evaluation stopped: {st.session_state.eval_error}")
    if m is None:
        html_block('<p class="pm-sub">Scores the blueprint: traceability, faithfulness of the figures and coherence. '
                   'Two calls to the judge model; the pages of the cited sources are opened.</p>')
        if live is not None and view.status == "done":
            if st.button("Evaluate this run", type="primary", icon=":material/fact_check:"):
                _evaluate(live, "multi_agent")
        elif view.status != "done":
            st.caption("Available when the run is finished.")
        else:
            st.caption("This saved run has no evaluation.")
        return
    if m.get("error"):
        st.error(f"Not evaluated: {m['error']}")
        return
    ours, theirs = scores(m), scores(b) if b and not b.get("error") else None
    runs = len(m.get("judge_runs") or []) or 1
    html_block(f'<p class="pm-sub">Judge {esc(m.get("judge_model") or "")}'
               f'{f", mean of {runs} runs" if runs > 1 else ""}. References and figures are checked in code. '
               f'{cost_line(ours, theirs)}.</p>')
    kpi_strip(ours, theirs, spread(m))
    trap = m.get("trap") or {}
    if trap.get("applies"):
        verdict = pill("approved", "Trap avoided") if trap.get("avoided") else pill("blocking", "Trap segment targeted")
        html_block(f'<div class="pm-issue" style="margin:0 0 16px">{verdict}<div class="t">The plan targets '
                   f'<b>{esc(trap.get("target"))}</b>. Trap of this case: {esc(trap.get("segment"))}.</div></div>')
    left, right = st.columns(2, gap="large")
    for col, (label, key) in zip((left, right), (("Strategy vs analysis", "strategy_vs_analysis"),
                                                 ("Campaign vs strategy", "campaign_vs_strategy"))):
        score = (m.get("coherence") or {}).get(key) or {}
        with col:
            st.subheader(f"{label} · {score.get('score', '—')} / 5")
            st.write(score.get("reason") or "—")
    details(m)
    if b is None:
        if live is not None:
            st.button("Compare with the single-prompt baseline", icon=":material/compare_arrows:",
                      on_click=lambda: st.session_state.update(eval_request="baseline"),
                      help="Same model, same document, one prompt asking for the full plan (no tools, no validator).")
            if st.session_state.pop("eval_request", None) == "baseline":
                _evaluate(live, "baseline")
    elif b.get("error"):
        st.error(f"Baseline: {b['error']}")
    else:
        with st.expander("The single-prompt plan (baseline) and its checks"):
            details(b)
            plan = (view.dir / "baseline" / "blueprint.md")
            if plan.exists():
                st.markdown(re.sub(r"^#", "##", plan.read_text(), flags=re.M))


def details(m: dict) -> None:
    t, f = m["traceability"], m["faithfulness"]
    with st.expander(f"Claims · {t['traced']} of {t['claims']} with a valid source"):
        st.dataframe([{"Claim": i["quote"], "References": ", ".join(i["refs"]) or "—", "Valid source": i["traced"]}
                      for i in t["items"]], hide_index=True, width="stretch")
        if t.get("unquoted"):
            st.caption(f"{t['unquoted']} claim(s) left out: the judge's quote is not in the plan.")
    with st.expander(f"Figures · {f['matched']} of {f['checked']} found, {f['unverifiable']} unverifiable"):
        st.dataframe([{"Figure": i["figure"], "Found in": i["status"], "Claim": i["quote"]} for i in f["items"]],
                     hide_index=True, width="stretch")
        st.caption("Unverifiable: a cited page could not be read; these figures are not in the score.")
    with st.expander(f"Sources · {sum(s['valid'] for s in m['sources'])} of {len(m['sources'])} valid"):
        st.dataframe([{"#": s["number"], "Reference": s["reference"], "Status": s["status"], "Valid": s["valid"]}
                      for s in m["sources"]], hide_index=True, width="stretch")


def _evaluate(live, system: str) -> None:
    from eval.baseline import run_baseline
    from eval.metrics import evaluate, find_case

    run = live.run
    case = find_case(run.document)
    out = run.dir if system == "multi_agent" else run.dir / "baseline"
    with st.spinner("Writing the single-prompt plan and scoring it…" if system == "baseline"
                    else "Evaluating the blueprint: claims, figures, coherence…"):
        try:
            if system == "baseline":
                run_baseline(run.document, out, run.settings)
            evaluate(out, run.document_text, case and case.get("trap"), settings=run.settings)
            st.session_state.eval_error = None
        except Exception as e:  # the result stays on screen; the tab shows the error
            st.session_state.eval_error = f"{type(e).__name__}: {e}"
    st.rerun()


# ── D2: evaluation results (a page in the top bar) ──────────────────────────────────────

def _mean(rows: list[dict], key: str):
    values = [r[key] for r in rows if r.get(key) is not None and not isinstance(r[key], bool)]
    return sum(values) / len(values) if values else None


def results_page() -> None:
    html_block('<h1 style="margin:0 0 6px;padding:0">Evaluation results</h1>')
    if not RESULTS.exists():
        st.info("No evaluation results yet: run `uv run python -m eval.run_eval`.")
        return
    r = json.loads(RESULTS.read_text())
    cases = {cid: c for cid, c in r["cases"].items() if c.get("multi_agent") and c.get("baseline")}
    html_block('<p class="pm-sub" style="max-width:780px">Can coordinated, specialised agents write a launch plan that '
               'is more coherent, traceable and reusable than one prompt? Both systems use '
               f'<span class="pm-id">{esc(r["models"]["analyst"])}</span> on the same documents; the judge is '
               f'<span class="pm-id">{esc(r["judge_model"])}</span>, {r.get("judge_runs", 1)} runs per plan. '
               'Ties and losses are reported as they are.</p>')
    ma = [scores(c["multi_agent"]["metrics"]) for c in cases.values()]
    bl = [scores(c["baseline"]["metrics"]) for c in cases.values()]
    ours = {k: _mean(ma, k) for k in ("traceability", "faithfulness", "coherence_strategy", "coherence_campaign", "tokens", "seconds")}
    theirs = {k: _mean(bl, k) for k in ours}
    st.subheader(f"Average over {len(cases)} cases · multi-agent, with the difference to the single prompt")
    kpi_strip(ours, theirs)
    html_block(f'<p class="pm-sub" style="margin-top:-12px">Cost: {fmt(ours["tokens"], "tokens")} tokens and '
               f'{ours["seconds"]:.0f} s per multi-agent run, against {fmt(theirs["tokens"], "tokens")} tokens and '
               f'{theirs["seconds"]:.0f} s for one prompt.</p>')

    st.subheader("Per case")
    head = ("<tr><th>Case</th><th>System</th><th class='num'>Traceability</th><th class='num'>Faithfulness</th>"
            "<th class='num'>Strategy vs analysis</th><th class='num'>Campaign vs strategy</th><th>Trap</th>"
            "<th class='num'>Tokens</th></tr>")
    rows = []
    for cid, c in cases.items():
        for system, label in (("multi_agent", "Multi-agent"), ("baseline", "Single prompt")):
            s = scores(c[system]["metrics"])
            trap = "—" if s.get("trap_avoided") is None else ("avoided" if s["trap_avoided"] else "targeted")
            first = (f'<td rowspan="2"><b style="font-weight:500">{esc(cid)}</b><br><span style="color:var(--muted);'
                     f'font-size:12px">{esc(c["case"]["category"])} · {esc(c["case"]["country"])}</span></td>'
                     if system == "multi_agent" else "")
            rows.append(f"<tr>{first}<td>{label}</td>"
                        f"<td class='num'>{fmt(s['traceability'], 'pct')}</td><td class='num'>{fmt(s['faithfulness'], 'pct')}</td>"
                        f"<td class='num'>{_score(s['coherence_strategy'])}</td><td class='num'>{_score(s['coherence_campaign'])}</td>"
                        f"<td>{trap}</td><td class='num'>{fmt(s['tokens'], 'tokens')}</td></tr>")
    html_block(f'<table class="pm-table">{head}{"".join(rows)}</table>')
    st.caption("Each case's saved run is in Saved runs, read-only.")

    gem = (r.get("presets") or {}).get("gemini", {}).get("demo_fr")
    if gem and cases.get("demo_fr"):
        st.subheader("Free models on the demo document · Gemini against Anthropic")
        g, a = scores(gem["multi_agent"]["metrics"]), scores(cases["demo_fr"]["multi_agent"]["metrics"])
        rows = "".join(
            f"<tr><td>{label}</td><td class='num'>{fmt(a[k], kind).replace('<small>/ 5</small>', '')}</td>"
            f"<td class='num'>{fmt(g[k], kind).replace('<small>/ 5</small>', '')}</td></tr>"
            for k, label, _, kind, _ in METRICS)
        rows += (f"<tr><td>Tokens</td><td class='num'>{fmt(a['tokens'], 'tokens')}</td><td class='num'>{fmt(g['tokens'], 'tokens')}</td></tr>"
                 f"<tr><td>Pipeline time</td><td class='num'>{a['seconds']:.0f} s</td><td class='num'>{g['seconds']:.0f} s</td></tr>")
        html_block('<table class="pm-table" style="max-width:640px"><tr><th>Metric</th><th class="num">Anthropic preset</th>'
                   f'<th class="num">Gemini free preset</th></tr>{rows}</table>')

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Findings")
        if FINDINGS.exists():
            st.markdown(FINDINGS.read_text().split("\n", 1)[-1])
        elif r.get("findings"):
            st.markdown(r["findings"])
        else:
            st.caption("Not written yet (Phase 14.3). Until then, the per-case table above is the result.")
    with right:
        st.subheader("Blind ratings")
        if r.get("ratings"):
            st.json(r["ratings"], expanded=False)
        else:
            st.caption("Not done yet (Phase 14.3): each pair of plans is rated without knowing which system wrote it.")


def _score(v) -> str:
    return "—" if v is None else f"{v:.1f}"
