"""Run the Validator (Phase 7) on fixed cases, twice each, to check the judge and its stability.

Not collected by pytest (no test_ prefix) because it calls the LLM. Run it by hand:

    uv run python tests/run_judge.py
    uv run python tests/run_judge.py --repeats 3

Cases come from tests/fixtures/small_segment_case.json (the "small segment" trap and a
control strategy) and, when present, from the Phase 6 runs in outputs/strategy_runs/.
Writes outputs/judge_runs/<timestamp>/results.json with every ValidationResult.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from premortem.config import RunSettings  # noqa: E402
from premortem.llm import using_settings  # noqa: E402
from premortem.agents.validator import make_validator  # noqa: E402
from premortem.ingestion.parser import parse_document  # noqa: E402
from premortem.schemas import Analysis, Campaign, CompanyBrief, Strategy  # noqa: E402

FIXTURE = ROOT / "tests/fixtures/small_segment_case.json"
DEMO_DOC = ROOT / "data/demo/demo_company.pdf"  # the document the fixture analysis was built from
STRATEGY_RUNS = ROOT / "outputs/strategy_runs"
OUTPUT_DIR = ROOT / "outputs/judge_runs"


def cases() -> list[tuple[str, str, dict]]:
    data = json.loads(FIXTURE.read_text())
    base = {"brief": CompanyBrief(**data["brief"]), "analysis": Analysis(**data["analysis"]),
            "document_text": parse_document(DEMO_DOC), "validations": [], "human_feedback": None}
    found = [
        ("analysis", "analysis", base),
        ("strategy_small_segment", "strategy", {**base, "strategy": Strategy(**data["strategy_small_segment"])}),
        ("strategy_large_segment", "strategy", {**base, "strategy": Strategy(**data["strategy_large_segment"])}),
    ]
    if STRATEGY_RUNS.exists():
        for run in sorted(p for p in STRATEGY_RUNS.iterdir() if p.is_dir()):
            if json.loads((run / "run.json").read_text()).get("feedback"):
                continue
            state = {**base, "strategy": Strategy.model_validate_json((run / "strategy.json").read_text()),
                     "campaign": Campaign.model_validate_json((run / "campaign.json").read_text())}
            found.append((f"campaign_{run.name}", "campaign", state))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Validator on fixed cases.")
    parser.add_argument("--repeats", type=int, default=2, help="Runs per case (default: 2)")
    args = parser.parse_args()

    print(f"Judge model: {SETTINGS.model('validator')}, temperature: {SETTINGS.judge_temperature}")
    results = {}
    for name, stage, state in cases():
        results[name] = []
        for i in range(args.repeats):
            start = time.perf_counter()
            result = make_validator(stage)(state)["validations"][0]
            seconds = round(time.perf_counter() - start, 1)
            results[name].append({"seconds": seconds, **result.model_dump()})
            blocking = [x.check for x in result.issues if x.severity == "blocking"]
            warnings = [x.check for x in result.issues if x.severity == "warning"]
            print(f"{name:34} run {i + 1}: passed={result.passed!s:5} blocking={blocking} warnings={warnings}")

    run_dir = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}"
    run_dir.mkdir(parents=True)
    (run_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Saved to {run_dir.relative_to(ROOT)}/")
    return 0


# A local script: keys and models from .env, as one run would get them
SETTINGS = RunSettings.from_env(mode="local")

if __name__ == "__main__":
    with using_settings(SETTINGS):
        sys.exit(main())
