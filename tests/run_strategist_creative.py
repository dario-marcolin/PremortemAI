"""Run the Strategist and the Creative (Phase 6) on an Analysis saved by run_analyst.py.

Not collected by pytest (no test_ prefix) because it calls the LLM. Run it by hand:

    uv run python tests/run_strategist_creative.py                         # latest analyst run
    uv run python tests/run_strategist_creative.py --analysis-dir outputs/analyst_runs/<run>
    uv run python tests/run_strategist_creative.py --feedback "Target office workers"

With --feedback, the first strategy is rejected with that text (as a human would) and the
Strategist revises it before the Creative runs.

Each run writes a folder outputs/strategy_runs/<timestamp>/ with:
    strategy.json      the final Strategy (and strategy_first.json when --feedback is used)
    campaign.json      the Campaign
    run.json           run details: analysis used, model, checks, tokens, duration
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.callbacks import get_usage_metadata_callback  # noqa: E402

from premortem import config  # noqa: E402
from premortem.agents.creative import creative  # noqa: E402
from premortem.agents.strategist import strategist  # noqa: E402
from premortem.ingestion.brief_extractor import extract_brief  # noqa: E402
from premortem.ingestion.parser import parse_document  # noqa: E402
from premortem.schemas import Analysis, CompanyBrief  # noqa: E402

ANALYST_RUNS = ROOT / "outputs/analyst_runs"
OUTPUT_DIR = ROOT / "outputs/strategy_runs"


def load_inputs(analysis_dir: Path) -> tuple[CompanyBrief, Analysis]:
    analysis = Analysis.model_validate_json((analysis_dir / "analysis.json").read_text())
    brief_file = analysis_dir / "brief.json"
    if brief_file.exists():
        return CompanyBrief.model_validate_json(brief_file.read_text()), analysis
    # Older analyst runs did not save the brief: extract it again from the same document
    document = json.loads((analysis_dir / "run.json").read_text())["document"]
    print(f"      no brief.json, extracting the brief from {Path(document).name}")
    return extract_brief(parse_document(document)), analysis


def checks(analysis: Analysis, strategy, campaign) -> dict:
    """The deterministic checks Phase 7 will turn into validation rules."""
    source_ids = {s.id for s in analysis.sources}
    segment = next((s for s in analysis.segments if s.segment_id == strategy.target_segment_id), None)
    message_channels = [m.channel for m in campaign.key_messages]
    return {
        "target_segment": f"{strategy.target_segment_id} {segment.label if segment else '(NOT IN ANALYSIS)'}",
        "target_size": segment.estimated_size if segment else None,
        "unknown_source_ids": sorted(set(strategy.supporting_source_ids) - source_ids),
        "channels_without_message": [c for c in strategy.channels if c not in message_channels],
        "messages_outside_channels": [c for c in message_channels if c not in strategy.channels],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Strategist and the Creative on a saved Analysis.")
    parser.add_argument("--analysis-dir", type=Path, help="Analyst run folder (default: the latest one)")
    parser.add_argument("--feedback", help="Reject the first strategy with this feedback")
    args = parser.parse_args()
    analysis_dir = args.analysis_dir or sorted(p for p in ANALYST_RUNS.iterdir() if p.is_dir())[-1]
    analysis_dir = analysis_dir.resolve()

    start = time.perf_counter()
    with get_usage_metadata_callback() as usage:
        print(f"[1/3] Loading {analysis_dir.relative_to(ROOT)}")
        brief, analysis = load_inputs(analysis_dir)
        state = {"brief": brief, "analysis": analysis, "strategy": None, "campaign": None, "validations": [],
                 "strategy_revisions": 0, "campaign_revisions": 0, "human_feedback": None}

        print(f"[2/3] Strategist ({config.LLM_MODEL})")
        state.update(strategist(state))
        first_strategy = state["strategy"]
        print(f"      target: {first_strategy.target_segment_id}, channels: {first_strategy.channels}")
        if args.feedback:
            state["human_feedback"] = args.feedback
            state.update(strategist(state))
            print(f"      revised with feedback, target: {state['strategy'].target_segment_id}")

        print("[3/3] Creative")
        state.update(creative(state))
        print(f"      tagline: {state['campaign'].tagline}")
    duration = round(time.perf_counter() - start, 1)

    run_dir = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}"
    run_dir.mkdir(parents=True)
    if args.feedback:
        (run_dir / "strategy_first.json").write_text(first_strategy.model_dump_json(indent=2))
    (run_dir / "strategy.json").write_text(state["strategy"].model_dump_json(indent=2))
    (run_dir / "campaign.json").write_text(state["campaign"].model_dump_json(indent=2))
    run_info = {
        "analysis_dir": str(analysis_dir.relative_to(ROOT)),
        "model": config.LLM_MODEL,
        "feedback": args.feedback,
        "strategy_revisions": state["strategy_revisions"],
        "checks": checks(analysis, state["strategy"], state["campaign"]),
        "tokens": {model: dict(u) for model, u in usage.usage_metadata.items()},
        "seconds": duration,
    }
    (run_dir / "run.json").write_text(json.dumps(run_info, indent=2, default=str))

    print()
    print(state["strategy"].model_dump_json(indent=2))
    print(state["campaign"].model_dump_json(indent=2))
    print()
    print(json.dumps(run_info["checks"], indent=2, ensure_ascii=False))
    print(f"Saved to {run_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
