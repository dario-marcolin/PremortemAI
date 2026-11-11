"""RunView: what every screen reads, built the same way for a live run and a saved one (roadmap 15.8).

A saved run is a folder with state.json, run.json, log.txt and blueprint.md (examples/, eval/runs/,
outputs/). Runs made after Phase 15 also have searches.json and rounds.json; older ones fall back to
the queries in log.txt and to one round per step.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import TypeAdapter

from eval.metrics import load_metrics, parse_sources
from premortem.agents.revision import blocking_issues
from premortem.runner import LogLine
from premortem.schemas import Analysis, Campaign, CompanyBrief, Source, Strategy
from premortem.state import LaunchState

ROOT = Path(__file__).resolve().parent.parent

# The timeline: one entry per agent. Each graph node belongs to one step.
STEPS = ["brief", "analysis", "strategy", "campaign", "blueprint"]
STEP_LABELS = {"brief": "Brief", "analysis": "Analysis", "strategy": "Strategy", "campaign": "Campaign",
               "blueprint": "Blueprint", "evaluation": "Evaluation"}
NODE_STEP = {"parse": "brief", "extract_brief": "brief", "analyst": "analysis", "validate_analysis": "analysis",
             "strategist": "strategy", "validate_strategy": "strategy", "human_approval": "strategy",
             "creative": "campaign", "validate_campaign": "campaign", "blueprint": "blueprint"}
AGENT_NODE = {"brief": "extract_brief", "analysis": "analyst", "strategy": "strategist", "campaign": "creative",
              "blueprint": "blueprint"}
AGENT_NAME = {"extract_brief": "Brief extractor", "analyst": "Analyst", "validate_analysis": "Validator",
              "strategist": "Strategist", "validate_strategy": "Validator", "human_approval": "Your review",
              "creative": "Creative", "validate_campaign": "Validator", "blueprint": "Blueprint writer",
              "parse": "Document"}
LOG_LINE = re.compile(r"^\s*([\d.]+)s\s+(\S+)\s+(node|search|results|pause|warning|error)\s+(.*)$")


def parse_log(text: str) -> list[LogLine]:
    """log.txt back into LogLines; traceback lines of a failed run are skipped."""
    lines = []
    for raw in text.splitlines():
        m = LOG_LINE.match(raw)
        if m:
            lines.append(LogLine(m.group(2), m.group(4), m.group(3), float(m.group(1))))
    return lines


def domain(url: str | None) -> str:
    host = urlparse(url or "").netloc
    return host[4:] if host.startswith("www.") else host


@dataclass
class StepInfo:
    key: str
    status: str  # pending, running, review, done, approved, warning, limit, failed
    rounds: int = 0
    warnings: int = 0
    blocking: int = 0
    unresolved: bool = False


@dataclass
class RunView:
    dir: Path
    run_id: str
    live: bool
    status: str  # running, waiting, done, failed, stopped
    record: dict
    brief: CompanyBrief | None = None
    analysis: Analysis | None = None
    strategy: Strategy | None = None
    campaign: Campaign | None = None
    validations: list = field(default_factory=list)
    state: dict = field(default_factory=dict)
    log: list[LogLine] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)
    rounds: dict[str, list[dict]] = field(default_factory=dict)
    pending: dict | None = None
    current_nodes: tuple = ()
    error: str | None = None
    seconds: float = 0.0
    tokens: int | None = None
    document_text: str = ""
    label: str | None = None  # e.g. "Demo document · Anthropic" for a committed run

    # ── construction ────────────────────────────────────────────────────────────────────
    @classmethod
    def from_dir(cls, path: str | Path, label: str | None = None) -> "RunView":
        path = Path(path)
        record = json.loads((path / "run.json").read_text()) if (path / "run.json").exists() else {}
        state = TypeAdapter(LaunchState).validate_python(json.loads((path / "state.json").read_text()))
        log = parse_log((path / "log.txt").read_text()) if (path / "log.txt").exists() else []
        searches = json.loads((path / "searches.json").read_text()) if (path / "searches.json").exists() \
            else searches_from_log(log)
        rounds = json.loads((path / "rounds.json").read_text()) if (path / "rounds.json").exists() else {}
        status = record.get("status", "done")
        view = cls(dir=path, run_id=path.name, live=False, status=status, record=record, state=state, log=log,
                   searches=searches, rounds=rounds, error=record.get("error"), seconds=record.get("seconds") or 0.0,
                   tokens=total_tokens(record.get("tokens")), document_text=state.get("document_text", ""),
                   label=label)
        view._fill(state)
        return view

    @classmethod
    def from_live(cls, live) -> "RunView":
        run = live.run
        state = _retry(lambda: run.state)
        status = live.status
        view = cls(dir=run.dir, run_id=run.run_id, live=True, status=status,
                   record={**run.settings.to_record(), "document": str(run.document.name), "decisions": run.decisions},
                   state=state, log=list(run.log), searches=[dict(s) for s in run.searches],
                   rounds=_retry(run.rounds) if state else {}, pending=_retry(lambda: run.pending),
                   current_nodes=_retry(lambda: run.next_nodes), error=run.error, seconds=live.elapsed,
                   tokens=total_tokens(run.usage.usage_metadata), document_text=run.document_text)
        view._fill(state)
        return view

    def _fill(self, state: dict) -> None:
        self.brief, self.analysis = state.get("brief"), state.get("analysis")
        self.strategy, self.campaign = state.get("strategy"), state.get("campaign")
        self.validations = list(state.get("validations") or [])
        for name in ("analysis", "strategy", "campaign"):  # an old saved run: its final version is round 1
            if not self.rounds.get(name) and getattr(self, name) is not None:
                self.rounds[name] = [getattr(self, name).model_dump(mode="json")]

    # ── what the screens ask ────────────────────────────────────────────────────────────
    @property
    def title(self) -> str:
        return f"{self.brief.product_name} launch" if self.brief else Path(self.document).stem.replace("_", " ")

    @property
    def document(self) -> str:
        return self.record.get("document") or self.run_id

    @property
    def provider(self) -> str:
        from premortem.providers import PRESETS
        p = self.record.get("provider") or "—"
        return PRESETS[p].label.split(" (")[0] if p in PRESETS else ("Custom" if p == "custom" else p)

    @property
    def date(self) -> str:
        m = re.match(r"(\d{8})_(\d{6})", self.run_id)
        if m:
            return datetime.strptime(m.group(1), "%Y%m%d").strftime("%-d %b %Y")
        path = self.dir / "run.json"
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%-d %b %Y") if path.exists() else ""

    @property
    def blueprint_md(self) -> str:
        path = self.dir / "blueprint.md"
        return path.read_text() if path.exists() else ""

    @property
    def metrics(self) -> dict | None:
        return load_metrics(self.dir)

    @property
    def baseline(self) -> dict | None:
        return load_metrics(self.dir / "baseline")

    @property
    def target(self):
        return self.analysis.find_segment(self.strategy.target_segment_id) if self.analysis and self.strategy else None

    def validations_of(self, stage: str) -> list:
        return [v for v in self.validations if v.stage == stage]

    def node_runs(self, node: str) -> int:
        return sum(1 for l in self.log if l.node == node and l.kind == "node")

    def decisions(self) -> list[dict]:
        return self.record.get("decisions") or []

    def current_step(self) -> str | None:
        """The step that works now, waits for you or failed."""
        if self.status == "waiting":
            return "strategy"
        if self.status in ("running", "failed", "stopped"):
            nodes = self.current_nodes or ((self.log[-1].node,) if self.status == "failed" and self.log else ())
            if not nodes and not self.log:
                return "brief"
            for node in nodes:
                if node in NODE_STEP:
                    return NODE_STEP[node]
        return None

    def step(self, key: str) -> StepInfo:
        stage = key if key in ("analysis", "strategy", "campaign") else None
        runs = self.node_runs(AGENT_NODE[key])
        info = StepInfo(key, "pending", rounds=len(self.rounds.get(key) or []) or runs)
        if stage:
            latest = (self.validations_of(stage) or [None])[-1]
            if latest:
                info.warnings = sum(i.severity == "warning" for i in latest.issues)
                info.blocking = sum(i.severity == "blocking" for i in latest.issues)
            info.unresolved = bool(self.state and blocking_issues(self.state, stage)) and self._stage_finished(stage)
        current = self.current_step()
        if current == key:
            info.status = {"waiting": "review", "failed": "failed", "stopped": "pending"}.get(self.status, "running")
            if self.status == "stopped":
                info.status = "stopped"
            return info
        if runs == 0 and not (key == "brief" and self.brief):
            return info
        if key == "blueprint" and not self.blueprint_md:
            return info
        if info.unresolved:
            info.status = "limit"
        elif key == "strategy" and any(d.get("approved") for d in self.decisions()):
            info.status = "approved"
        else:
            info.status = "done"
        return info

    def _stage_finished(self, stage: str) -> bool:
        """Blocking issues count as unresolved only when the stage moved on (the revision limit was reached)."""
        after = {"analysis": "strategist", "strategy": "human_approval", "campaign": "blueprint"}[stage]
        return self.node_runs(after) > 0 or (stage == "strategy" and self.status == "waiting")

    def now(self) -> str:
        """What is happening now, in one line: "Analyst · searching 'protein crisps France'"."""
        if self.status == "waiting":
            return "Waiting for your review of the strategy"
        if self.status == "done":
            return "Finished"
        if self.status == "failed":
            return "Stopped by an error"
        if self.status == "stopped":
            return "Paused by you"
        if not self.log:
            return "Brief extractor · reading the document"
        node = next(iter(self.current_nodes), None)
        last = self.log[-1]
        if node == "analyst" or (last.node == "analyst" and last.kind in ("search", "results")):
            searching = [l for l in self.log if l.kind == "search"]
            if searching and last.kind in ("search", "results"):
                return f"Analyst · searching ‘{searching[-1].text}’"
            return "Analyst · reading the document and planning the searches"
        doing = {"extract_brief": "reading the document", "validate_analysis": "checking the analysis",
                 "strategist": "choosing the target", "validate_strategy": "checking the strategy",
                 "creative": "writing the campaign", "validate_campaign": "checking the campaign",
                 "blueprint": "writing the executive summary"}
        return f"{AGENT_NAME.get(node, node or 'Pipeline')} · {doing.get(node, 'working')}"

    # ── sources and citations ───────────────────────────────────────────────────────────
    def sources(self) -> dict[str, Source]:
        return {s.id: s for s in (self.analysis.sources if self.analysis else [])}

    def search_hits(self) -> dict[str, dict]:
        """url -> the search result that found it (title, snippet, query)."""
        hits = {}
        for s in self.searches:
            for r in s.get("results") or []:
                hits.setdefault(r["url"], {**r, "query": s["query"]})
        return hits

    def source_checks(self) -> dict[str, dict]:
        """reference -> the evaluation's check of that source (status, valid), when the run was evaluated."""
        m = self.metrics or {}
        return {s["reference"]: s for s in m.get("sources") or []}

    def document_passage(self, reference: str, chars: int = 280) -> str:
        """The start of the document section a document source names, e.g. "section 4 (Market context)"."""
        text = self.document_text or ""
        names = re.findall(r"\(([^)]+)\)", reference) + re.findall(r"section\s+([\w.]+)", reference, re.I)
        for name in names:
            i = text.lower().find(name.lower())
            if i >= 0:
                passage = re.sub(r"\s+", " ", text[i + len(name): i + len(name) + chars * 2]).strip(" :.-\n")
                return passage[:chars].rsplit(" ", 1)[0] + "…"
        return ""

    def blueprint_numbers(self) -> dict[str, dict]:
        """The blueprint's [n] -> its Sources entry (reference, url)."""
        return parse_sources(self.blueprint_md) if self.blueprint_md else {}


def searches_from_log(log: list[LogLine]) -> list[dict]:
    """A run saved before Phase 15: its queries and result counts from log.txt, without the results."""
    searches, analyst_round, pending = [], 1, []
    for line in log:
        if line.node == "analyst" and line.kind == "node":
            analyst_round += 1
        elif line.kind == "search":
            entry = {"query": line.text, "results": [], "round": analyst_round, "count": None}
            searches.append(entry)
            pending.append(entry)
        elif line.kind in ("results", "warning") and line.node == "analyst" and pending:
            entry = pending.pop(0)
            m = re.match(r"(\d+) results", line.text)
            entry["count"] = int(m.group(1)) if m else 0
            if not m:
                entry["error"] = line.text
    return searches


def total_tokens(usage: dict | None) -> int | None:
    if not usage:
        return None
    return sum(int(u.get("total_tokens") or 0) for u in usage.values())


def _retry(fn, tries: int = 3):
    """Reads of the graph state from the UI thread while the worker thread writes a checkpoint."""
    for attempt in range(tries):
        try:
            return fn()
        except RuntimeError:
            if attempt == tries - 1:
                raise
