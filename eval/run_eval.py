"""Phases 10 and 14: run the multi-agent pipeline and the single-prompt baseline on every eval case,
score both with eval/metrics.py and write eval/report.md.

    uv run python -m eval.run_eval                         # every case, both systems, anthropic preset
    uv run python -m eval.run_eval --cases nordbrew_de     # some cases; the others stay in the report
    uv run python -m eval.run_eval --cases demo_fr --provider gemini   # the free preset (Phase 14.2)
    uv run python -m eval.run_eval --no-fetch              # do not open the source URLs
    uv run python -m eval.run_eval --report-only           # rebuild the report, e.g. after the human rating

The pipeline runs with auto-approve. Both systems use the --provider preset (default anthropic, the
reference). The judge is always the --judge-provider preset's eval judge (default anthropic: Haiku), so
a gemini run is scored by the same judge as an anthropic one. It scores each plan --judge-runs times
(default 3) and the report gives the mean and the spread. Keys: <PROVIDER>_API_KEY or LLM_API_KEY in .env.
Outputs:

    eval/runs/<provider>/<case>/multi_agent/   blueprint.md, state.json, run.json, log.txt, metrics.json
    eval/runs/<provider>/<case>/baseline/      blueprint.md, run.json, log.txt, metrics.json
                         (committed; the run itself writes to outputs/eval_<stamp>/ first)
    eval/results.json    metrics of every case ("cases": the anthropic preset; "presets": the others),
                         the models, the judge and the ratings; the report and the UI read it
    eval/rating/         the blind pairs and the rating sheet (see eval/rating.py)
    eval/findings.md     written by the team after the rating; copied into the report
    eval/report.md
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval import rating  # noqa: E402
from eval.baseline import run_baseline  # noqa: E402
from eval.metrics import EVAL_DIR, evaluate_repeated, load_cases, scores, spread  # noqa: E402
from premortem import config  # noqa: E402
from premortem.config import RunSettings  # noqa: E402
from premortem.ingestion.parser import parse_document  # noqa: E402
from premortem.runner import Run  # noqa: E402

RESULTS = EVAL_DIR / "results.json"
REPORT = EVAL_DIR / "report.md"
FINDINGS = EVAL_DIR / "findings.md"
RUNS_DIR = EVAL_DIR / "runs"
SYSTEMS = {"multi_agent": "Multi-agent", "baseline": "Single prompt"}
REFERENCE = "anthropic"  # the preset of the main results; the others go under results["presets"]


def run_multi_agent(document: Path, run_id: str, settings: RunSettings) -> Path:
    """The full pipeline, approving every strategy. A failure is recorded in run.json."""
    run = Run(document, run_id=run_id, settings=settings)
    while True:
        for line in run.advance():
            print(f"    {line}")
        if run.status != "waiting":
            return run.dir
        run.answer({"approved": True})


def run_case(case: dict, out_root: Path, settings: RunSettings, fetch: bool = True,
             judge: RunSettings | None = None, judge_runs: int = 1) -> dict:
    """Both systems on one case with `settings`; the plans are scored by `judge` (default: settings)."""
    judge = judge or settings
    document = ROOT / case["document"]
    document_text = parse_document(document)
    entry = {"case": case}
    for system in SYSTEMS:
        print(f"  {SYSTEMS[system]}")
        out_dir = out_root / case["id"] / system
        if system == "multi_agent":
            out_dir = run_multi_agent(document, str(out_dir.relative_to(config.OUTPUT_DIR)), settings)
        else:
            run_baseline(document, out_dir, settings)
        print("    evaluating")
        try:
            metrics = evaluate_repeated(out_dir, document_text, case.get("trap"), fetch=fetch, settings=judge,
                                        runs=judge_runs)
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


def _with_spread(metrics: dict, key: str, fmt) -> str:
    """The score, with the (min-max) of the repeated judge runs when they differ."""
    value = fmt(scores(metrics)[key])
    low_high = spread(metrics).get(key)
    if low_high and low_high[0] != low_high[1]:
        value += f" ({fmt(low_high[0])}–{fmt(low_high[1])})"
    return value


def _models_line(results: dict) -> str:
    models = results.get("models") or {}
    blueprint = models.get("blueprint")
    big = f", `{blueprint}` for the blueprint summary" if blueprint and blueprint != results["model"] else ""
    runs = results.get("judge_runs", 1)
    judge = f"the judge `{results['judge_model']}`" + (f", {runs} runs per plan (mean, min–max in brackets)"
                                                       if runs > 1 else "")
    return (f"The agents and the single prompt use `{results['model']}`{big}, on the same document; "
            f"the metrics use {judge}.")


def _preset_section(results: dict) -> list[str]:
    """Phase 14.2: the same case on another preset (e.g. the free Gemini tier), scored by the same judge."""
    presets = results.get("presets") or {}
    if not presets:
        return []
    lines = ["## Other presets (same judge)", "",
             "The same case run on another provider's preset, scored by the same judge as the main results. "
             "It shows the quality gap of the free models in numbers.", "",
             "| Case | Preset | System | Traceability | Faithfulness | Coherence S/A | Coherence C/S | Trap avoided | "
             "Sources | Tokens | Seconds |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for provider, cases in presets.items():
        for case_id, e in cases.items():
            rows = [(provider, e)]
            if case_id in results["cases"]:
                rows.insert(0, (results.get("provider", REFERENCE), results["cases"][case_id]))
            for name, entry in rows:
                for system, label in SYSTEMS.items():
                    if system not in entry:
                        continue
                    m = entry[system]["metrics"]
                    s = scores(m)
                    if m.get("error"):
                        lines.append(f"| {case_id} | {name} | {label} | failed: {_error(m['error'])} | | | | | | | |")
                        continue
                    sources = m.get("sources") or []
                    lines.append(
                        f"| {case_id} | {name} | {label} | {_with_spread(m, 'traceability', _pct)} | "
                        f"{_with_spread(m, 'faithfulness', _pct)} | {_with_spread(m, 'coherence_strategy', _num)} | "
                        f"{_with_spread(m, 'coherence_campaign', _num)} | {_yes_no(s['trap_avoided'])} | "
                        f"{sum(x['valid'] for x in sources)} of {len(sources)} | {_num(s['tokens'], 0)} | "
                        f"{_num(s['seconds'], 0)} |")
    return lines + [""]


def render_report(results: dict, ratings: dict | None = None, findings: str | None = None) -> str:
    entries = list(results["cases"].values())
    lines = [
        "# Evaluation report (Phase 14)",
        "",
        "Research question: *can coordinated specialized agents produce a launch plan that is more coherent, "
        "traceable and reusable than isolated AI prompts?*",
        "",
        f"Updated {results['updated'][:16].replace('T', ' ')}. {_models_line(results)} "
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
            lines.append(f"| {e['case']['id']} | {name} | {_with_spread(m, 'traceability', _pct)} | "
                         f"{_with_spread(m, 'faithfulness', _pct)} | "
                         f"{_with_spread(m, 'coherence_strategy', _num)} | {_with_spread(m, 'coherence_campaign', _num)} | "
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

    lines += _preset_section(results)
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
              "does not see the validation log. It is a cheaper model than the pipeline's Validator (professor's "
              "notes), and the same judge scores every system and every preset.",
              "- **Judge spread.** The judge scores each plan several times; the tables give the mean and, in "
              "brackets, the lowest and highest run. A gap between the systems smaller than this spread is a tie.",
              "- **Cost and latency.** Tokens and seconds of the system itself (pipeline time, human wait excluded); "
              "the evaluation's own judge calls are not counted.",
              "- Small sample (one pipeline run per case and system): read the per-case table, not only the averages.",
              ""]
    return "\n".join(lines)


def keep_run(case_dir: Path, provider: str, entry: dict) -> dict:
    """Copy the case's folders to eval/runs/<provider>/<case>/ (committed) and point the entry at them."""
    target = RUNS_DIR / provider / case_dir.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(case_dir, target)
    for system in SYSTEMS:
        if system in entry:
            entry[system]["dir"] = _rel(target / system)
    return entry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare the multi-agent pipeline with a single-prompt baseline.")
    parser.add_argument("--cases", nargs="+", help="case ids from eval/cases/cases.json (default: all)")
    parser.add_argument("--provider", default=REFERENCE,
                        help=f"preset of both systems (default {REFERENCE}; another one is reported as a preset run)")
    parser.add_argument("--judge-provider", default=REFERENCE, help=f"preset of the judge (default {REFERENCE})")
    parser.add_argument("--judge-runs", type=int, default=3, help="judge runs per plan (default 3)")
    parser.add_argument("--no-fetch", action="store_true", help="do not open the source URLs")
    parser.add_argument("--report-only", action="store_true", help="rebuild eval/report.md from eval/results.json")
    args = parser.parse_args(argv)

    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {"cases": {}}
    if not args.report_only:
        try:  # the evaluation is a local tool: keys from .env
            settings = RunSettings.from_env(mode="local", provider=args.provider)
            judge = RunSettings.from_env(mode="local", provider=args.judge_provider)
        except ValueError as e:
            sys.exit(str(e))
        for s in {settings.provider: settings, judge.provider: judge}.values():
            if not s.llm_api_key:
                sys.exit(f"No key for {s.provider}: set {s.provider.upper()}_API_KEY (or LLM_API_KEY) in .env")
        if not settings.tavily_api_key:
            sys.exit("TAVILY_API_KEY must be set in .env")
        cases = load_cases()
        unknown = set(args.cases or []) - {c["id"] for c in cases}
        if unknown:
            sys.exit(f"Unknown case(s): {', '.join(sorted(unknown))}")
        out_root = config.OUTPUT_DIR / f"eval_{datetime.now():%Y%m%d_%H%M%S}"
        reference = settings.provider == REFERENCE
        print(f"Systems: {settings.provider} ({settings.model('strategist')}); judge: {judge.eval_judge} "
              f"x {args.judge_runs}")
        for case in cases:
            if args.cases and case["id"] not in args.cases:
                continue
            print(f"\n{case['id']} ({case['document']})")
            entry = run_case(case, out_root, settings, fetch=not args.no_fetch, judge=judge,
                             judge_runs=args.judge_runs)
            entry = keep_run(out_root / case["id"], settings.provider, entry)
            entry["settings"] = settings.to_record()
            entry["judge"] = {"model": judge.eval_judge, "runs": args.judge_runs}
            if reference:
                results["cases"][case["id"]] = entry
                # "model" is the agents' model (the baseline uses it too); "models" has every role
                results.update(provider=settings.provider, model=settings.model("strategist"),
                               models=settings.models, judge_model=judge.eval_judge, judge_runs=args.judge_runs)
            else:
                results.setdefault("presets", {}).setdefault(settings.provider, {})[case["id"]] = entry
            results["updated"] = datetime.now().isoformat()
            RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False))  # saved after each case
        order = [c["id"] for c in cases]
        results["cases"] = dict(sorted(results["cases"].items(), key=lambda kv: order.index(kv[0])))
        RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        # The blind rating compares the two systems of the reference preset only
        if reference and rating.read_ratings():
            print("Ratings exist in eval/rating/ratings/: the blind pairs were not rewritten.")
        elif reference:
            rating.write_sheet({cid: {s: ROOT / e[s]["dir"] / "blueprint.md" for s in SYSTEMS}
                                for cid, e in results["cases"].items()
                                if all(not e[s]["metrics"].get("error") for s in SYSTEMS)})
    if not results["cases"]:
        if results.get("presets"):
            print(f"\nSaved to {_rel(RESULTS)}. The report is written once the {REFERENCE} cases have run.")
            return
        sys.exit("No results yet: run without --report-only first.")
    results["ratings"] = rating.read_ratings()  # the UI reads the ratings from results.json too
    results["findings"] = FINDINGS.read_text() if FINDINGS.exists() else None
    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    REPORT.write_text(render_report(results, results["ratings"], results["findings"]))
    print(f"\nReport: {_rel(REPORT)}")


if __name__ == "__main__":
    main()
