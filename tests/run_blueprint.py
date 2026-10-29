"""Render the Launch Blueprint (Phase 9) from a run saved by scripts/run_cli.py.

Not collected by pytest (no test_ prefix) because the executive summary calls the LLM.
Run it by hand:

    uv run python tests/run_blueprint.py                              # latest run in outputs/
    uv run python tests/run_blueprint.py --run outputs/<run_id>
    uv run python tests/run_blueprint.py --no-summary                 # no LLM call

Writes outputs/<run_id>/blueprint.md, replacing the one written by the graph.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import TypeAdapter  # noqa: E402

from premortem import config  # noqa: E402
from premortem.output.blueprint import save_blueprint  # noqa: E402
from premortem.state import LaunchState  # noqa: E402


def latest_run() -> Path:
    runs = sorted(p.parent for p in config.OUTPUT_DIR.glob("*/state.json"))
    if not runs:
        sys.exit("No run with a state.json in outputs/: run scripts/run_cli.py first.")
    return runs[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the blueprint of a saved run.")
    parser.add_argument("--run", type=Path, help="Run folder with state.json (default: latest)")
    parser.add_argument("--no-summary", action="store_true", help="Skip the LLM executive summary")
    args = parser.parse_args()

    run_dir = args.run or latest_run()
    state = TypeAdapter(LaunchState).validate_python(json.loads((run_dir / "state.json").read_text()))
    path = save_blueprint(state, run_dir / "blueprint.md", summary="(skipped)" if args.no_summary else None)
    print(f"Saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
