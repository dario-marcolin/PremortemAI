"""Run the Analyst subgraph (Phase 5) on one document and save the result.

Not collected by pytest (no test_ prefix) because it calls the LLM and Tavily. Run it by hand:

    uv run python tests/run_analyst.py                      # demo document
    uv run python tests/run_analyst.py --doc path/to/file.pdf

Each run writes a folder outputs/analyst_runs/<timestamp>_<document name>/ with:
    brief.json         the CompanyBrief given to the Analyst
    analysis.json      the Analysis returned by the subgraph
    research_log.md    every search and its results, as the report step saw them
    run.json           run details: model, searches, tool rounds, tokens, duration
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

from premortem.config import RunSettings  # noqa: E402
from premortem.llm import using_settings  # noqa: E402
from premortem.agents.analyst import build_analyst, research_log  # noqa: E402
from premortem.ingestion.brief_extractor import extract_brief  # noqa: E402
from premortem.ingestion.parser import parse_document  # noqa: E402

DEFAULT_DOC = ROOT / "data/demo/demo_company.pdf"
OUTPUT_DIR = ROOT / "outputs/analyst_runs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Analyst subgraph on one document.")
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC, help="Document to analyse (default: demo PDF)")
    args = parser.parse_args()
    doc = args.doc.expanduser().resolve()

    start = time.perf_counter()
    with get_usage_metadata_callback() as usage:
        print(f"[1/2] Parsing {doc.name} and extracting the brief with {SETTINGS.model('analyst')}")
        text = parse_document(doc)
        brief = extract_brief(text)

        print("[2/2] Running the Analyst")
        state = {"brief": brief, "document_text": text, "messages": []}
        messages, queries, analysis = [], [], None
        for update in build_analyst().stream(state, stream_mode="updates"):
            for node, data in update.items():
                for m in data.get("messages", []):
                    messages.append(m)
                    for call in getattr(m, "tool_calls", []):
                        queries.append(call["args"].get("query"))
                        print(f"      search: {queries[-1]}")
                if node == "analyst_report":
                    analysis = data["analysis"]
                    print("      report written")
    duration = round(time.perf_counter() - start, 1)

    run_dir = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{doc.stem}"
    run_dir.mkdir(parents=True)
    (run_dir / "brief.json").write_text(brief.model_dump_json(indent=2))
    (run_dir / "analysis.json").write_text(analysis.model_dump_json(indent=2))
    (run_dir / "research_log.md").write_text(research_log(messages))
    run_info = {
        "document": str(doc),
        "model": SETTINGS.model('analyst'),
        "searches": queries,
        "tool_rounds": sum(1 for m in messages if getattr(m, "tool_calls", None)),
        "competitors": len(analysis.competitors),
        "segments": len(analysis.segments),
        "sources": len(analysis.sources),
        "tokens": {model: dict(u) for model, u in usage.usage_metadata.items()},
        "seconds": duration,
    }
    (run_dir / "run.json").write_text(json.dumps(run_info, indent=2, default=str))

    print()
    print(analysis.model_dump_json(indent=2))
    print()
    print(json.dumps({k: run_info[k] for k in ("tool_rounds", "competitors", "segments", "sources", "seconds")}))
    print(f"Saved to {run_dir.relative_to(ROOT)}/")
    return 0


# A local script: keys and models from .env, as one run would get them
SETTINGS = RunSettings.from_env(mode="local")

if __name__ == "__main__":
    with using_settings(SETTINGS):
        sys.exit(main())
