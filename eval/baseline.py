"""Baseline for the evaluation: the same model and the same document, one single prompt.

No tools, no validator, no human approval: one call asks for the full launch plan with
the same outline as the Launch Blueprint (eval/prompts/baseline.md). The output is saved
like a multi-agent run, so the metrics read both the same way:

    <out_dir>/blueprint.md   the launch plan
    <out_dir>/run.json       document, model, status, error, tokens, seconds
    <out_dir>/log.txt        one line for the call, or the traceback
"""

import json
import traceback
from pathlib import Path
from time import perf_counter

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage

from premortem import config
from premortem.ingestion.parser import parse_document
from premortem.llm import get_llm

PROMPT = Path(__file__).parent / "prompts" / "baseline.md"


def run_baseline(document: str | Path, out_dir: str | Path) -> Path:
    """Write the baseline plan and its run record to out_dir. A failed call is recorded, not raised."""
    document, out_dir = Path(document), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    usage = UsageMetadataCallbackHandler()
    start = perf_counter()
    status, error, log = "done", None, ""
    try:
        text = parse_document(document)
        response = get_llm().invoke(
            [SystemMessage(PROMPT.read_text()),
             HumanMessage(f'<document name="{document.name}">\n{text}\n</document>\n\nWrite the launch plan.')],
            config={"callbacks": [usage]},
        )
        (out_dir / "blueprint.md").write_text(response.text)
        log = f"{perf_counter() - start:7.1f}s  baseline           node     {len(response.text)} characters written"
    except Exception as e:  # the evaluation goes on with the other cases
        status, error, log = "failed", f"{type(e).__name__}: {e}", traceback.format_exc()
    seconds = perf_counter() - start
    (out_dir / "log.txt").write_text(log.rstrip() + "\n")
    run = {
        "system": "baseline",
        "document": str(document.resolve()),
        "model": config.LLM_MODEL,
        "status": status,
        "error": error,
        "tokens": {model: dict(u) for model, u in usage.usage_metadata.items()},
        "seconds": round(seconds, 1),
    }
    (out_dir / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))
    return out_dir
