"""End-to-end run of the pipeline up to Phase 2: document → text → CompanyBrief.

Not collected by pytest (no test_ prefix) because it calls the LLM. Run it by hand:

    uv run python tests/run_e2e_up_to_phase2.py                      # demo document
    uv run python tests/run_e2e_up_to_phase2.py --doc path/to/file.pdf

Each run writes a folder outputs/e2e_phase2/<timestamp>_<document name>/ with:
    document_text.md   the text the LLM receives (output of the parser)
    brief.json         the extracted CompanyBrief
    run.json           run details: document, model, tokens, duration, warnings
"""

import argparse
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from premortem import config  # noqa: E402
from premortem.ingestion.brief_extractor import extract_brief  # noqa: E402
from premortem.ingestion.parser import DocumentParseError, estimate_tokens, parse_document  # noqa: E402

DEFAULT_DOC = ROOT / "data/demo/demo_company.pdf"
OUTPUT_DIR = ROOT / "outputs/e2e_phase2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the pipeline up to Phase 2 on one document.")
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC, help="Document to analyse (default: demo PDF)")
    args = parser.parse_args()
    doc = args.doc.expanduser().resolve()

    print(f"[1/2] Parsing {doc}")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            text = parse_document(doc)
        except DocumentParseError as e:
            print(f"Error: {e}")
            return 1
    for w in caught:
        print(f"      Warning: {w.message}")
    print(f"      {len(text)} characters, about {estimate_tokens(text)} tokens")

    print(f"[2/2] Extracting the brief with {config.LLM_MODEL}")
    start = time.perf_counter()
    brief = extract_brief(text)
    duration = round(time.perf_counter() - start, 1)
    print(f"      Done in {duration} s")

    run_dir = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{doc.stem}"
    run_dir.mkdir(parents=True)
    (run_dir / "document_text.md").write_text(text)
    (run_dir / "brief.json").write_text(brief.model_dump_json(indent=2))
    run_info = {
        "document": str(doc),
        "model": config.LLM_MODEL,
        "estimated_tokens": estimate_tokens(text),
        "extraction_seconds": duration,
        "parser_warnings": [str(w.message) for w in caught],
    }
    (run_dir / "run.json").write_text(json.dumps(run_info, indent=2))

    print()
    print(brief.model_dump_json(indent=2))
    print()
    print(f"Saved to {run_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
