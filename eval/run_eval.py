"""Phase 10: run the multi-agent pipeline and the single-prompt baseline on every eval case,
score both with eval/metrics.py and write eval/report.md.

    uv run python -m eval.run_eval                         # every case, both systems
    uv run python -m eval.run_eval --cases nordbrew_de     # some cases; the others stay in the report
    uv run python -m eval.run_eval --no-fetch              # do not open the source URLs
    uv run python -m eval.run_eval --report-only           # rebuild the report, e.g. after the human rating

The pipeline runs with auto-approve. Outputs:

    outputs/eval_<stamp>/<case>/multi_agent/   blueprint.md, state.json, run.json, log.txt, metrics.json
    outputs/eval_<stamp>/<case>/baseline/      blueprint.md, run.json, log.txt, metrics.json
    eval/results.json    metrics of every case; the report is rebuilt from it
    eval/rating/         the blind pairs and the rating sheet (see eval/rating.py)
    eval/findings.md     written by the team after the rating; copied into the report
    eval/report.md
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval import rating  # noqa: E402
from eval.baseline import run_baseline  # noqa: E402
from eval.metrics import EVAL_DIR, evaluate, load_cases, scores  # noqa: E402
from premortem import config  # noqa: E402
from premortem.ingestion.parser import parse_document  # noqa: E402
from premortem.runner import Run  # noqa: E402

RESULTS = EVAL_DIR / "results.json"
REPORT = EVAL_DIR / "report.md"
FINDINGS = EVAL_DIR / "findings.md"
SYSTEMS = {"multi_agent": "Multi-agent", "baseline": "Single prompt"}


def run_multi_agent(document: Path, run_id: str) -> Path:
    """The full pipeline, approving every strategy. A failure is recorded in run.json."""
    run = Run(document, run_id=run_id)
    while True:
        for line in run.advance():
            print(f"    {line}")
        if run.status != "waiting":
            return run.dir
        run.answer({"approved": True})


def run_case(case: dict, out_root: Path, fetch: bool = True) -> dict:
    document = ROOT / case["document"]
    document_text = parse_document(document)
    entry = {"case": case}
    for system in SYSTEMS:
        print(f"  {SYSTEMS[system]}")
        out_dir = out_root / case["id"] / system
        if system == "multi_agent":
            out_dir = run_multi_agent(document, str(out_dir.relative_to(config.OUTPUT_DIR)))
        else:
            run_baseline(document, out_dir)
        print("    evaluating")
        try:
            metrics = evaluate(out_dir, document_text, case.get("trap"), fetch=fetch)
        except Exception as e:  # the other systems and cases still run; --cases redoes this one
            metrics = {"system": system, "error": f"evaluation failed: {type(e).__name__}: {e}"}
        entry[system] = {"dir": _rel(out_dir), "metrics": metrics}
        print(f"    {scores(metrics)}")
    return entry


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


# ── report ──────────────────────────────────────────────────────────────────────────────

def _pct(x) -> str:
    return "—" if x is None else f"{x:.0%}"


def _num(x, digits: int = 1) -> str:
    return "—" if x is None else f"{x:,.{digits}f}"


def _yes_no(x) -> str:
    return "n/a" if x is None else "yes" if x else "**no**"


def _cell(text) -> str:
    return " ".join(str(text or "—").split()).replace("|", "\\|")


def _complete(entries: list[dict]) -> list[dict]:
    """The cases where both systems ran and were evaluated: the averages compare like with like."""
    return [e for e in entries if all(s in e and not e[s]["metrics"].get("error") for s in SYSTEMS)]


def _error(text: str) -> str:
    return _cell(text)[:100] + ("…" if len(_cell(text)) > 100 else "")


def _average(entries: list[dict], system: str, key: str):
    values = [scores(e[system]["metrics"])[key] for e in entries]
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _trap_count(entries: list[dict], system: str) -> str:
    values = [scores(e[system]["metrics"])["trap_avoided"] for e in entries if e["case"].get("trap")]
    known = [v for v in values if v is not None]
    return f"{sum(known)}/{len(known)}" if known else "—"


def render_report(results: dict, ratings: dict | None = None, findings: str | None = None) -> str:
    entries = list(results["cases"].values())
    lines = [
        "# Evaluation report (Phase 10)",
        "",
        "Research question: *can coordinated specialized agents produce a launch plan that is more coherent, "
        "traceable and reusable than isolated AI prompts?*",
        "",
        f"Updated {results['updated'][:16].replace('T', ' ')}. Both systems use `{results['model']}` on the same "
        f"document; the metrics use the judge `{results['judge_model']}`. "
        "The multi-agent pipeline runs with auto-approve. Generated by `eval/run_eval.py` from `eval/results.json`.",
        "",
        "## Cases",
        "",
        "| Case | Category | Country | Trap segment |",
        "|---|---|---|---|",
        *(f"| {e['case']['id']} | {e['case']['category']} | {e['case']['country']} | {_cell(e['case'].get('trap'))} |"
          for e in entries),
        "",
        "## Results (average over the cases)",
        "",
        f"Cases where both systems ran and were evaluated: {len(_complete(entries))} of {len(entries)}"
        + (f" ({', '.join(e['case']['id'] for e in _complete(entries))})." if _complete(entries) else "."),
        "",
        "| Metric | Multi-agent | Single prompt |",
        "|---|---|---|",
    ]
    rows = [("Traceability: claims with a valid source", "traceability", _pct),
            ("Faithfulness: figures found in the document or a cited source", "faithfulness", _pct),
            ("Coherence: strategy vs analysis (1-5)", "coherence_strategy", _num),
            ("Coherence: campaign vs strategy (1-5)", "coherence_campaign", _num),
            ("Trap avoided (trap cases)", "trap_avoided", None),
            ("Tokens per run", "tokens", lambda x: _num(x, 0)),
            ("Seconds per run", "seconds", lambda x: _num(x, 0))]
    complete = _complete(entries)
    for label, key, fmt in rows:
        lines.append(f"| {label} | " + " | ".join(
            _trap_count(complete, s) if fmt is None else fmt(_average(complete, s, key)) for s in SYSTEMS) + " |")

    lines += ["", "## Results per case", "",
              "| Case | System | Traceability | Faithfulness | Coherence S/A | Coherence C/S | Trap avoided | Tokens | Seconds |",
              "|---|---|---|---|---|---|---|---|---|"]
    for e in entries:
        for system, name in SYSTEMS.items():
            if system not in e:
                continue
            m = e[system]["metrics"]
            s = scores(m)
            if m.get("error"):
                lines.append(f"| {e['case']['id']} | {name} | failed: {_error(m['error'])} | | | | | "
                             f"{_num(s['tokens'], 0)} | {_num(s['seconds'], 0)} |")
                continue
            lines.append(f"| {e['case']['id']} | {name} | {_pct(s['traceability'])} | {_pct(s['faithfulness'])} | "
                         f"{_num(s['coherence_strategy'], 0)} | {_num(s['coherence_campaign'], 0)} | "
                         f"{_yes_no(s['trap_avoided'])} | {_num(s['tokens'], 0)} | {_num(s['seconds'], 0)} |")

    lines += ["", "## Details per case", ""]
    for e in entries:
        lines += [f"### {e['case']['id']}", "",
                  "| | Multi-agent | Single prompt |", "|---|---|---|"]
        detail = {system: e[system]["metrics"] for system in SYSTEMS if system in e}
        def row(label, fn):
            return f"| {label} | " + " | ".join(_cell(fn(detail[s])) if s in detail and not detail[s].get("error")
                                                 else "—" for s in SYSTEMS) + " |"
        lines += [
            row("Target chosen", lambda m: m["trap"].get("target")),
            row("Claims with a valid source", lambda m: f"{m['traceability']['traced']} of {m['traceability']['claims']}"),
            row("Figures found / checked", lambda m: f"{m['faithfulness']['matched']} of {m['faithfulness']['checked']}"
                f" ({m['faithfulness']['unverifiable']} unverifiable)"),
            row("Valid sources", lambda m: f"{sum(s['valid'] for s in m['sources'])} of {len(m['sources'])}"),
            row("Coherence S/A", lambda m: f"{m['coherence']['strategy_vs_analysis']['score']}: "
                f"{m['coherence']['strategy_vs_analysis']['reason']}"),
            row("Coherence C/S", lambda m: f"{m['coherence']['campaign_vs_strategy']['score']}: "
                f"{m['coherence']['campaign_vs_strategy']['reason']}"),
            "| Output | " + " | ".join(f"`{e[s]['dir']}`" if s in e else "—" for s in SYSTEMS) + " |",
            "",
        ]

    lines += ["## Human rating (blind)", ""]
    if ratings:
        lines += [f"Raters: {', '.join(ratings['raters'])}. Scores from 1 to 5, average over raters and cases.", "",
                  "| Question | Multi-agent | Single prompt |", "|---|---|---|"]
        for name, question in rating.RUBRIC:
            lines.append(f"| {name}: {question} | {_num(ratings['averages'].get('multi_agent', {}).get(name))} | "
                         f"{_num(ratings['averages'].get('baseline', {}).get(name))} |")
        lines += ["", "Disagreements (2 points or more between raters):", ""]
        lines += [f"- {d['case']}, {SYSTEMS[d['system']]}, {d['question']}: "
                  + ", ".join(f"{r} {v}" for r, v in d["scores"].items()) for d in ratings["disagreements"]] or ["- None."]
    else:
        lines.append("Pending: the blind pairs and the sheet are in `eval/rating/` (see its README).")

    lines += ["", "## Findings", "",
              findings.strip() if findings else "To write after the human rating (`eval/findings.md`).",
              "", "## Method and limits", "",
              "- **Traceability.** The judge extracts the factual claims about market, competitors, customers and "
              "segments (not the company's facts about itself). A claim counts only if its quote is in the plan, and "
              "a reference only if it is cited on the same line. Valid source: the company document, or a URL that "
              "exists (a page that refuses bots still counts; a 404 or an unknown domain does not).",
              "- **Faithfulness.** Each figure of those claims is searched in code in the document and in the pages of "
              "the cited URLs, with rounding (\"1.3 million\" matches 1,276,000). *Unverifiable*: a cited page could "
              "not be read; these figures are left out of the score. Figures the plan computed (ratios) are not checked.",
              "- **Coherence and trap.** One judge call with a fixed rubric (`eval/prompts/coherence.md`). The judge "
              "does not see the validation log, but it is the same model as the pipeline's validator, which may "
              "favour the multi-agent plans.",
              "- **Cost and latency.** Tokens and seconds of the system itself (pipeline time, human wait excluded); "
              "the evaluation's own judge calls are not counted.",
              "- Small sample (one run per case and system): read the per-case table, not only the averages.",
              ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare the multi-agent pipeline with a single-prompt baseline.")
    parser.add_argument("--cases", nargs="+", help="case ids from eval/cases/cases.json (default: all)")
    parser.add_argument("--no-fetch", action="store_true", help="do not open the source URLs")
    parser.add_argument("--report-only", action="store_true", help="rebuild eval/report.md from eval/results.json")
    args = parser.parse_args()

    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {"cases": {}}
    if not args.report_only:
        if not config.LLM_API_KEY or not config.TAVILY_API_KEY:
            sys.exit("LLM_API_KEY and TAVILY_API_KEY must be set in .env")
        cases = load_cases()
        unknown = set(args.cases or []) - {c["id"] for c in cases}
        if unknown:
            sys.exit(f"Unknown case(s): {', '.join(sorted(unknown))}")
        out_root = config.OUTPUT_DIR / f"eval_{datetime.now():%Y%m%d_%H%M%S}"
        for case in cases:
            if args.cases and case["id"] not in args.cases:
                continue
            print(f"\n{case['id']} ({case['document']})")
            results["cases"][case["id"]] = run_case(case, out_root, fetch=not args.no_fetch)
            results.update(updated=datetime.now().isoformat(), model=config.LLM_MODEL, judge_model=config.JUDGE_MODEL)
            RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False))  # saved after each case
        order = [c["id"] for c in cases]
        results["cases"] = dict(sorted(results["cases"].items(), key=lambda kv: order.index(kv[0])))
        RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        if rating.read_ratings():
            print("Ratings exist in eval/rating/ratings/: the blind pairs were not rewritten.")
        else:
            rating.write_sheet({cid: {s: ROOT / e[s]["dir"] / "blueprint.md" for s in SYSTEMS}
                                for cid, e in results["cases"].items()
                                if all(not e[s]["metrics"].get("error") for s in SYSTEMS)})
    if not results["cases"]:
        sys.exit("No results yet: run without --report-only first.")
    REPORT.write_text(render_report(results, rating.read_ratings(),
                                    FINDINGS.read_text() if FINDINGS.exists() else None))
    print(f"\nReport: {_rel(REPORT)}")


if __name__ == "__main__":
    main()
