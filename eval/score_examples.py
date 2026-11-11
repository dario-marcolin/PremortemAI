"""Phase 14.2: score the saved example runs, so the Evaluation tab works on them with no key.

    uv run python -m eval.score_examples                       # every folder of examples/
    uv run python -m eval.score_examples --only demo_gemini    # one of them

For each examples/<name>/ (a finished pipeline run): write the single-prompt baseline with the same
preset as the run (examples/<name>/baseline/), then score both plans with the anthropic judge (Haiku),
3 runs each. Writes metrics.json in both folders. An existing baseline is kept, so a re-run costs
only the judge.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.baseline import run_baseline  # noqa: E402
from eval.metrics import evaluate_repeated, find_case, scores  # noqa: E402
from eval.run_eval import REFERENCE  # noqa: E402
from premortem.config import RunSettings  # noqa: E402
from premortem.ingestion.parser import parse_document  # noqa: E402

EXAMPLES = ROOT / "examples"


def score(folder: Path, judge: RunSettings, judge_runs: int = 3, fetch: bool = True) -> dict:
    run = json.loads((folder / "run.json").read_text())
    document = ROOT / run["document"]
    document_text = parse_document(document)
    trap = (find_case(document) or {}).get("trap")
    baseline_dir = folder / "baseline"
    if not (baseline_dir / "blueprint.md").exists():
        print("  baseline")
        run_baseline(document, baseline_dir, RunSettings.from_env(mode="local", provider=run["provider"]))
    out = {}
    for name, path in (("multi_agent", folder), ("baseline", baseline_dir)):
        print(f"  evaluating {name}")
        out[name] = evaluate_repeated(path, document_text, trap, fetch=fetch, settings=judge, runs=judge_runs)
        print(f"    {scores(out[name])}")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score the saved example runs and their baseline.")
    parser.add_argument("--only", nargs="+", help="folder names in examples/ (default: all)")
    parser.add_argument("--judge-runs", type=int, default=3)
    parser.add_argument("--no-fetch", action="store_true", help="do not open the source URLs")
    args = parser.parse_args(argv)
    try:
        judge = RunSettings.from_env(mode="local", provider=REFERENCE)
    except ValueError as e:
        sys.exit(str(e))
    if not judge.llm_api_key:
        sys.exit(f"The judge needs {REFERENCE.upper()}_API_KEY (or LLM_API_KEY) in .env")
    for folder in sorted(p for p in EXAMPLES.iterdir() if (p / "run.json").exists()):
        if args.only and folder.name not in args.only:
            continue
        print(f"\n{folder.name}")
        score(folder, judge, args.judge_runs, fetch=not args.no_fetch)


if __name__ == "__main__":
    main()
