"""Run the full pipeline from the terminal (Phase 8).

    uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf
    uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf --auto-approve
    uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf --reject "Target vegans"

The progress of each node is printed as it finishes. At the human approval step the
strategy and its validation issues are printed and the script asks Approve? [y/n/feedback]:
"y" approves, "n" asks for feedback, any other text is taken as the feedback of a rejection.
--auto-approve approves every time; --reject rejects the first strategy with that text.

Each run writes a folder outputs/<run_id>/ with:
    state.json     the final LaunchState
    run.json       document, models, human decisions, tokens, duration
"""

import argparse
import json
import sys
import textwrap
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.callbacks import get_usage_metadata_callback  # noqa: E402
from langgraph.types import Command  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

from premortem import config  # noqa: E402
from premortem.graph import build_graph, initial_state  # noqa: E402
from premortem.ingestion.parser import DocumentParseError, parse_document  # noqa: E402
from premortem.state import LaunchState  # noqa: E402

OUTPUT_DIR = ROOT / "outputs"
# Enough for several rejections: each one adds up to 2 * (MAX_REVISIONS + 1) + 1 steps
RECURSION_LIMIT = 100


def summary(node: str, update: dict) -> str:
    """One line describing what a node wrote."""
    if node == "extract_brief":
        b = update["brief"]
        return f"{b.company_name}, {b.product_name} ({b.target_country}), {len(b.missing_info)} missing info"
    if node == "analyst":
        a = update["analysis"]
        return f"{len(a.competitors)} competitors, {len(a.segments)} segments, {len(a.sources)} sources"
    if node.startswith("validate_"):
        (v,) = update["validations"]
        blocking = sum(i.severity == "blocking" for i in v.issues)
        return f"{'passed' if v.passed else 'FAILED'}, {blocking} blocking, {len(v.issues) - blocking} warnings"
    if node == "strategist":
        s = update["strategy"]
        return f"target {s.target_segment_id}, channels {', '.join(s.channels)} (revisions: {update['strategy_revisions']})"
    if node == "creative":
        c = update["campaign"]
        return f'"{c.tagline}", {len(c.key_messages)} messages (revisions: {update["campaign_revisions"]})'
    if node == "human_approval":
        return "rejected" if update.get("human_feedback") else "approved"
    return ""


def print_update(namespace: tuple, update: dict) -> None:
    for node, values in update.items():
        if node == "__interrupt__":
            continue
        if namespace:  # inside the Analyst subgraph: show the searches only
            for message in (values or {}).get("messages", []):
                for call in getattr(message, "tool_calls", []):
                    print(f"      search: {call['args'].get('query')}")
            continue
        print(f"  ✔ {node:18} {summary(node, values or {})}")


def show_approval(payload: dict) -> None:
    s = payload["strategy"]
    print("\n" + "=" * 72 + "\nHUMAN APPROVAL\n" + "=" * 72)
    print(f"Target segment: {s['target_segment_id']} {s['target_description']}")
    for label, key in (("Positioning", "positioning_statement"), ("Value proposition", "value_proposition"),
                       ("Pricing", "pricing_direction"), ("Rationale", "rationale")):
        print(f"\n{label}:\n" + textwrap.indent(textwrap.fill(s[key], 88), "  "))
    print(f"\nChannels: {', '.join(s['channels'])}")
    print(f"Sources: {', '.join(s['supporting_source_ids'])}")
    print(f"\nValidation issues (after {payload['strategy_revisions']} revision(s)):")
    if not payload["issues"]:
        print("  none")
    for i in payload["issues"]:
        print(textwrap.indent(textwrap.fill(f"[{i['severity']}] {i['check']}: {i['message']}", 88), "  "))
    if payload["unresolved"]:
        print("\n  ⚠ Blocking issues are still unresolved: the revision limit was reached.")


def ask_human() -> dict:
    while True:
        answer = input("\nApprove? [y/n/feedback] ").strip()
        if answer.lower() in ("y", "yes"):
            return {"approved": True}
        if answer.lower() in ("n", "no"):
            return {"approved": False, "feedback": input("Feedback for the Strategist: ").strip()}
        if answer:
            return {"approved": False, "feedback": answer}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PremortemAI pipeline on a document.")
    parser.add_argument("--doc", required=True, help="Company/product document (PDF, DOCX, PPTX, MD, TXT)")
    parser.add_argument("--auto-approve", action="store_true", help="Approve the strategy without asking")
    parser.add_argument("--reject", metavar="FEEDBACK", help="Reject the first strategy with this feedback")
    args = parser.parse_args()

    try:
        text = parse_document(args.doc)
    except DocumentParseError as e:
        print(f"Error: {e}")
        return 1

    run_id = f"{datetime.now():%Y%m%d_%H%M%S}_{Path(args.doc).stem}"
    app = build_graph()
    cfg = {"configurable": {"thread_id": f"{run_id}_{uuid.uuid4().hex[:6]}"}, "recursion_limit": RECURSION_LIMIT}
    print(f"Run {run_id}\nAgents: {config.LLM_MODEL}, judge: {config.JUDGE_MODEL}\n")

    decisions = []
    command = initial_state(text)
    start = time.perf_counter()
    with get_usage_metadata_callback() as usage:
        while True:
            for namespace, update in app.stream(command, cfg, stream_mode="updates", subgraphs=True):
                print_update(namespace, update)
            snapshot = app.get_state(cfg)
            if not snapshot.next:
                break
            payload = snapshot.interrupts[0].value
            show_approval(payload)
            if args.reject and not decisions:
                answer = {"approved": False, "feedback": args.reject}
            elif args.auto_approve:
                answer = {"approved": True}
            else:
                answer = ask_human()
            print(f"\n→ {'approved' if answer['approved'] else 'rejected: ' + (answer.get('feedback') or '(no text)')}\n")
            decisions.append({**answer, "target_segment_id": payload["strategy"]["target_segment_id"],
                              "unresolved": payload["unresolved"]})
            command = Command(resume=answer)
    seconds = round(time.perf_counter() - start, 1)

    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True)
    state = TypeAdapter(LaunchState).dump_python(snapshot.values, mode="json")
    (run_dir / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False))
    run = {
        "document": str(Path(args.doc).resolve()),
        "model": config.LLM_MODEL,
        "judge_model": config.JUDGE_MODEL,
        "decisions": decisions,
        "strategy_revisions": state["strategy_revisions"],
        "campaign_revisions": state["campaign_revisions"],
        "validations": [{"stage": v["stage"], "passed": v["passed"]} for v in state["validations"]],
        "tokens": {model: dict(u) for model, u in usage.usage_metadata.items()},
        "seconds": seconds,
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))

    unresolved = [v for v in state["validations"][-1:] if not v["passed"]]
    print(f"Done in {seconds}s. Tagline: {state['campaign']['tagline']}")
    if unresolved:
        print("⚠ The campaign still has blocking issues (revision limit reached): see state.json.")
    print(f"Saved to {run_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
