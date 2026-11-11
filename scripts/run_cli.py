"""Run the full pipeline from the terminal (Phase 8).

    uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf
    uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf --auto-approve
    uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf --reject "Target vegans"

The progress of each node is printed as it finishes. At the human approval step the
strategy and its validation issues are printed and the script asks Approve? [y/n/feedback]:
"y" approves, "n" asks for feedback, any other text is taken as the feedback of a rejection.
--auto-approve approves every time; --reject rejects the first strategy with that text.

Each run writes a folder outputs/<run_id>/ with:
    log.txt        every log line, as the run goes (and the traceback of a failure)
    blueprint.md   the Launch Blueprint (written by the graph's last node)
    state.json     the final LaunchState
    run.json       document, models, status, human decisions, tokens, pipeline seconds
"""

import argparse
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from premortem.config import RunSettings  # noqa: E402
from premortem.ingestion.parser import DocumentParseError  # noqa: E402
from premortem.runner import LogLine, Run  # noqa: E402

MARKS = {"node": "✔", "warning": "⚠", "error": "✘"}


def print_line(line: LogLine) -> None:
    if line.kind in ("search", "results"):
        print(f"      {'search: ' if line.kind == 'search' else '→ '}{line.text}")
    elif line.kind != "pause":  # the approval screen follows
        print(f"  {MARKS[line.kind]} {line.node:18} {line.text}")


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
        run = Run(args.doc, settings=RunSettings.from_env(mode="local"))  # the CLI is a local tool
    except DocumentParseError as e:
        print(f"Error: {e}")
        return 1
    models = ", ".join(f"{role} {model}" for role, model in run.settings.models.items())
    print(f"Run {run.run_id}\nProvider: {run.settings.provider}. Models: {models}\n")
    for line in run.log:  # parser warnings
        print_line(line)

    while True:
        for line in run.advance():
            print_line(line)
        if run.status != "waiting":
            break
        payload = run.pending
        show_approval(payload)
        if args.reject and not run.decisions:
            answer = {"approved": False, "feedback": args.reject}
        elif args.auto_approve:
            answer = {"approved": True}
        else:
            answer = ask_human()
        print(f"\n→ {'approved' if answer['approved'] else 'rejected: ' + (answer.get('feedback') or '(no text)')}\n")
        run.answer(answer)

    if run.status == "failed":
        print(f"\nThe run failed: {run.error}\nTraceback in {run.dir}/log.txt")
        return 1
    state = run.state
    print(f"Done in {run.seconds:.1f}s of pipeline time. Tagline: {state['campaign'].tagline}")
    if not state["validations"][-1].passed:
        print("⚠ The campaign still has blocking issues (revision limit reached): see the blueprint.")
    print(f"Saved to {run.dir}/ (blueprint.md, state.json, run.json, log.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
