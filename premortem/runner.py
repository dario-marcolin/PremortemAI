"""Run the pipeline on one document, one log line per step. Shared by the CLI, the UI and the evaluation.

A Run keeps the compiled graph, its thread and the run record (decisions, tokens, seconds),
so it can pause at the human approval and be resumed later: the CLI asks with input(),
the Streamlit UI across reruns, the evaluation approves automatically.

    run = Run("data/demo/demo_company.pdf", settings=RunSettings.from_env())
    for line in run.advance():          # until the approval pause, the end or an error
        print(line)
    run.answer({"approved": True})      # then advance() again

Each run writes outputs/<run_id>/: log.txt as it goes, then blueprint.md (written by the
graph's last node), state.json and run.json when the run ends or fails.

The run's settings (provider, keys, models) travel in config["configurable"]["settings"]. LangGraph
copies only plain str/int/float/bool configurable values into checkpoint metadata, so the settings
object, and the keys inside it, are never checkpointed; run.json records RunSettings.to_record().
"""

import json
import traceback
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Iterator, Literal

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import TypeAdapter

from premortem import config
from premortem.config import RunSettings
from premortem.graph import build_graph, initial_state
from premortem.ingestion.parser import parse_document
from premortem.state import LaunchState

# Enough for several rejections: each one adds up to 2 * (MAX_REVISIONS + 1) + 1 steps
RECURSION_LIMIT = 100
PIPELINE = ["extract_brief", "analyst", "validate_analysis", "strategist", "validate_strategy",
            "human_approval", "creative", "validate_campaign", "blueprint"]

Kind = Literal["node", "search", "results", "pause", "warning", "error"]
Status = Literal["running", "waiting", "done", "failed"]


@dataclass
class LogLine:
    node: str  # the graph node; searches and their results belong to "analyst"
    text: str
    kind: Kind = "node"
    seconds: float = 0.0  # pipeline time since the start of the run, human wait excluded

    def __str__(self) -> str:
        return f"{self.seconds:7.1f}s  {self.node:18} {self.kind:8} {self.text}"


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
        feedback = update.get("human_feedback")
        return f"rejected: {feedback}" if feedback else "approved"
    if node == "blueprint":
        return "blueprint.md written"
    return ""


def _results(message: ToolMessage) -> tuple[str, Kind]:
    """A search result as one log line: the count, or the error the tool returned (a warning)."""
    if message.status == "error":
        return str(message.content)[:200], "warning"
    try:
        results = json.loads(message.content)
    except (TypeError, ValueError):
        return str(message.content)[:200], "results"
    if isinstance(results, list) and results and all(isinstance(r, dict) and "error" in r for r in results):
        return results[0]["error"][:200], "warning"
    return (f"{len(results)} results" if isinstance(results, list) else str(results)[:200]), "results"


def describe(namespace: tuple, update: dict) -> list[tuple[str, str, Kind]]:
    """The log lines of one stream update: (node, text, kind)."""
    lines = []
    for node, values in update.items():
        if node == "__interrupt__":
            strategy = values[0].value["strategy"]
            lines.append(("human_approval", f"waiting for approval of target {strategy['target_segment_id']}", "pause"))
        elif namespace:  # inside the Analyst subgraph: show the searches and what they returned
            for message in (values or {}).get("messages", []):
                for call in getattr(message, "tool_calls", []):
                    lines.append(("analyst", call["args"].get("query", ""), "search"))
                if isinstance(message, ToolMessage):
                    lines.append(("analyst", *_results(message)))
        else:
            lines.append((node, summary(node, values or {}), "node"))
    return lines


class Run:
    def __init__(self, document: str | Path, run_id: str | None = None, settings: RunSettings | None = None):
        """Parse the document (raises DocumentParseError) and prepare the graph; nothing runs yet.

        settings=None reads them from the environment (the CLI, the evaluation, `local` mode)."""
        self.settings = settings or RunSettings.from_env()
        self.document = Path(document)
        self.run_id = run_id or f"{datetime.now():%Y%m%d_%H%M%S}_{self.document.stem}"
        self.dir = config.OUTPUT_DIR / self.run_id
        self.log: list[LogLine] = []
        self.decisions: list[dict] = []
        self.seconds = 0.0
        self.error: str | None = None
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.document_text = parse_document(self.document)
        for w in caught:
            self._add("parse", str(w.message), "warning")
        if not self.settings.tavily_api_key:
            self._add("analyst", "No Tavily key: web search is off, the analysis uses the document only.", "warning")

        self.app = build_graph()
        self.usage = UsageMetadataCallbackHandler()
        # The thread_id is the run_id: the blueprint node writes to outputs/<thread_id>/
        self.cfg = {"configurable": {"thread_id": self.run_id, "settings": self.settings},
                    "recursion_limit": RECURSION_LIMIT,
                    "callbacks": [self.usage]}
        # What the next advance() sends: the initial state, a resume Command, or None to
        # continue from the last checkpoint (after an error, or a stream cut short by the UI)
        self._input = initial_state(self.document_text)

    @property
    def state(self) -> dict:
        return self.app.get_state(self.cfg).values

    @property
    def next_nodes(self) -> tuple[str, ...]:
        return self.app.get_state(self.cfg).next

    @property
    def pending(self) -> dict | None:
        """The approval payload while the graph waits for the human (strategy, issues, unresolved)."""
        snapshot = self.app.get_state(self.cfg)
        if snapshot.next and snapshot.interrupts and self._input is None:
            return snapshot.interrupts[0].value
        return None

    @property
    def status(self) -> Status:
        if self.error:
            return "failed"
        if self.pending:
            return "waiting"
        if self._input is None and not self.next_nodes:
            return "done"
        return "running"

    def advance(self) -> Iterator[LogLine]:
        """Run until the approval pause, the end or an error, yielding each log line."""
        command, self._input, self.error = self._input, None, None
        start = perf_counter()
        elapsed = lambda: self.seconds + perf_counter() - start  # noqa: E731
        try:
            for namespace, update in self.app.stream(command, self.cfg, stream_mode="updates", subgraphs=True):
                for node, text, kind in describe(namespace, update):
                    yield self._add(node, text, kind, elapsed())
        except Exception as e:  # the UI and the evaluation go on; the CLI exits
            failed_at = ", ".join(self.next_nodes) or "graph"
            self.error = f"{type(e).__name__}: {e}"
            self._write_log(traceback.format_exc())
            yield self._add(failed_at, self.error, "error", elapsed())
        finally:
            self.seconds = elapsed()
        if self.status in ("done", "failed"):
            self.save()

    def answer(self, answer: dict) -> None:
        """The human decision at the approval pause: {"approved": bool, "feedback": str}."""
        payload = self.pending
        if payload is None:
            raise RuntimeError("The run is not waiting for an approval")
        self.decisions.append({**answer, "target_segment_id": payload["strategy"]["target_segment_id"],
                               "unresolved": payload["unresolved"]})
        self._input = Command(resume=answer)

    def save(self) -> Path:
        """Write state.json and run.json next to blueprint.md and log.txt."""
        self.dir.mkdir(parents=True, exist_ok=True)
        state = TypeAdapter(LaunchState).dump_python(self.state, mode="json")
        (self.dir / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False))
        run = {
            "document": str(self.document.resolve()),
            **self.settings.to_record(),  # provider and the model of each role, never the keys
            "status": self.status,
            "error": self.error,
            "decisions": self.decisions,
            "strategy_revisions": state.get("strategy_revisions", 0),
            "campaign_revisions": state.get("campaign_revisions", 0),
            "validations": [{"stage": v["stage"], "passed": v["passed"]} for v in state.get("validations", [])],
            "tokens": {model: dict(u) for model, u in self.usage.usage_metadata.items()},
            "seconds": round(self.seconds, 1),
        }
        (self.dir / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))
        return self.dir

    def _add(self, node: str, text: str, kind: Kind = "node", seconds: float | None = None) -> LogLine:
        line = LogLine(node, text, kind, round(self.seconds if seconds is None else seconds, 1))
        self.log.append(line)
        self._write_log(str(line))
        return line

    def _write_log(self, text: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "log.txt").open("a") as f:
            f.write(text.rstrip() + "\n")
