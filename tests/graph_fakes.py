"""Offline fakes for the whole pipeline (no LLM, no Tavily), shared by the graph tests.

One FakeModel replaces get_llm in every module. It answers by output schema with the
objects of tests/fixtures/dummy_state.json, runs one web search in the Analyst loop, and
lets each test decide which issues the judge raises per stage.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.types import Command
from pydantic import TypeAdapter

from premortem import config
from premortem.agents import analyst, creative, strategist
from premortem.graph import build_graph, initial_state
from premortem.ingestion import brief_extractor
from premortem.schemas import Analysis, Campaign, CompanyBrief, Strategy
from premortem.state import LaunchState
from premortem.tools import web_search as ws
from premortem.validation import judge as judge_module
from premortem.validation.judge import JudgeIssue, JudgeVerdict

FIXTURE = Path(__file__).parent / "fixtures" / "dummy_state.json"
STATE = TypeAdapter(LaunchState).validate_python(json.loads(FIXTURE.read_text()))
# Blocking issues the quote check accepts: the quotes are real values of the fixture
BLOCK_STRATEGY = JudgeIssue(severity="blocking", check="segment_size_and_access",
                            field="analysis.segments[SEG1].estimated_size", quote="~400k people, S3",
                            message="SEG1 is too small.")
BLOCK_CAMPAIGN = JudgeIssue(severity="blocking", check="claims_supported", field="strategy.positioning_statement",
                            quote=STATE["strategy"].positioning_statement, message="The tagline promises too much.")


def _text(message) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(part["text"] for part in message.content)


class FakeModel:
    def __init__(self, judge: dict | None = None):
        # stage -> issues raised at every call, or a function of the call number (0, 1...)
        self.judge = judge or {}
        self.prompts: dict[str, list[str]] = defaultdict(list)
        self.outputs = {CompanyBrief: STATE["brief"], Analysis: STATE["analysis"],
                        Strategy: STATE["strategy"], Campaign: STATE["campaign"]}

    def bind_tools(self, _tools):
        return _Bound(self, None)

    def with_structured_output(self, schema):
        return _Bound(self, schema)


class _Bound:
    def __init__(self, model: FakeModel, schema):
        self.model, self.schema = model, schema

    def invoke(self, messages):
        prompt = _text(messages[-1])
        if self.schema is JudgeVerdict:
            stage = re.search(r"Validate the (\w+)", prompt).group(1)
            calls = self.model.prompts[f"judge_{stage}"]
            calls.append(prompt)
            issues = self.model.judge.get(stage, [])
            return JudgeVerdict(issues=issues(len(calls) - 1) if callable(issues) else issues)
        name = self.schema.__name__ if self.schema else "analyst_llm"
        self.model.prompts[name].append(prompt)
        if self.schema is None:
            # First turn: one search; then the research is done
            if len(self.model.prompts[name]) == 1:
                return AIMessage("", tool_calls=[{"name": "web_search", "args": {"query": "coffee Italy"}, "id": "c1"}])
            return AIMessage("Done.")
        return self.model.outputs[self.schema]


def install(monkeypatch, model: FakeModel) -> FakeModel:
    for module in (brief_extractor, analyst, strategist, creative, judge_module):
        monkeypatch.setattr(module, "get_llm", lambda *_args, **_kwargs: model)
    # The web sources of the fixture are returned by the search, so the Analyst keeps them
    results = [{"title": s.id, "url": s.reference, "content": "snippet"}
               for s in STATE["analysis"].sources if s.kind == "web"]
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(ws, "_client", lambda: type("C", (), {"invoke": lambda _s, _i: {"results": results}})())
    return model


def run_graph(answers: list[dict] | None = None):
    """Run to END, answering each interrupt with the next answer (then approving).

    Returns the final state values, the interrupt payloads and the nodes in run order.
    """
    answers = list(answers or [])
    app = build_graph()
    cfg = {"configurable": {"thread_id": "test"}, "recursion_limit": 100}
    payloads, nodes = [], []
    command = initial_state(STATE["document_text"])
    while True:
        for update in app.stream(command, cfg, stream_mode="updates"):
            nodes += [name for name in update if name != "__interrupt__"]
        snapshot = app.get_state(cfg)
        if not snapshot.next:
            return snapshot.values, payloads, nodes
        payloads.append(snapshot.interrupts[0].value)
        command = Command(resume=answers.pop(0) if answers else {"approved": True})
