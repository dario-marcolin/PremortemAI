"""Offline fakes for the whole pipeline (no LLM, no Tavily), shared by the graph tests.

One FakeModel replaces get_llm in every module. It answers by output schema with the
objects of tests/fixtures/dummy_state.json, runs one web search in the Analyst loop, and
lets each test decide which issues the judge raises per stage. Plain invoke() calls return
SUMMARY (the executive summary) or BASELINE_PLAN (the single-prompt baseline of eval/).
The evaluation judge gets CLAIMS and a fixed coherence verdict; source pages are not fetched.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.types import Command
from pydantic import TypeAdapter

from eval import baseline as baseline_module
from eval import metrics
from eval.metrics import Claim, Claims, CoherenceVerdict, Page
from premortem.config import RunSettings
from premortem.agents import analyst, creative, strategist
from premortem.graph import build_graph, initial_state
from premortem.ingestion import brief_extractor
from premortem.output import blueprint
from premortem.schemas import Analysis, Campaign, CompanyBrief, Strategy
from premortem.state import LaunchState
from premortem.tools import web_search as ws
from premortem.validation import judge as judge_module
from premortem.validation.judge import JudgeIssue, JudgeVerdict

SUMMARY = "Launch the product for SEG1 in Italy."
# Every fake run uses these settings: the keys are fake, get_llm and the Tavily client are replaced
SETTINGS = RunSettings.preset("anthropic", "sk-ant-test", tavily_api_key="tvly-test")
FIXTURE = Path(__file__).parent / "fixtures" / "dummy_state.json"
STATE = TypeAdapter(LaunchState).validate_python(json.loads(FIXTURE.read_text()))
# Blocking issues the quote check accepts: the quotes are real values of the fixture
BLOCK_STRATEGY = JudgeIssue(severity="blocking", check="segment_size_and_access",
                            field="analysis.segments[SEG1].estimated_size", quote="~400k people, S3",
                            message="SEG1 is too small.")
BASELINE_CLAIM = "27% of adults bought a protein snack in the last three months [1]."
BASELINE_PLAN = f"""# Launch plan

## 1. Executive summary

Target students in Italy.

## 3. Market and competitors

{BASELINE_CLAIM} The market grows fast [2].

## Sources

1. Document: company.md, section 4
2. <https://example.com/report>
"""
# One claim of the blueprint (its summary) and one of the baseline: each plan finds only its own
CLAIMS = Claims(claims=[Claim(quote=SUMMARY), Claim(quote=BASELINE_CLAIM, figures=["27%"], refs=["1"])])
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

    def invoke(self, messages, **_kwargs):
        if "marketing consultant" in _text(messages[0]):
            self.prompts["baseline"].append(_text(messages[-1]))
            return AIMessage(BASELINE_PLAN)
        self.prompts["summary"].append(_text(messages[-1]))
        return AIMessage(SUMMARY)

    def with_structured_output(self, schema):
        return _Bound(self, schema)


class _Bound:
    def __init__(self, model: FakeModel, schema):
        self.model, self.schema = model, schema

    def with_config(self, **_kwargs):
        return self

    def invoke(self, messages):
        prompt = _text(messages[-1])
        if self.schema in (Claims, CoherenceVerdict):
            self.model.prompts[self.schema.__name__].append(prompt)
            if self.schema is Claims:
                return CLAIMS
            return CoherenceVerdict(strategy_vs_analysis=4, strategy_reason="Follows the analysis.",
                                    campaign_vs_strategy=5, campaign_reason="Every message fits.", target="SEG1", targets_trap=False if "<trap_segment>" in prompt else None)
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
    for module in (brief_extractor, analyst, strategist, creative, judge_module, blueprint, metrics, baseline_module):
        monkeypatch.setattr(module, "get_llm", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(metrics, "fetch_page", lambda url: Page(url, "ok", "The market grew 12% in 2024."))
    # The web sources of the fixture are returned by the search, so the Analyst keeps them
    results = [{"title": s.id, "url": s.reference, "content": "snippet"}
               for s in STATE["analysis"].sources if s.kind == "web"]
    monkeypatch.setattr(ws, "_client", lambda _key: type("C", (), {"invoke": lambda _s, _i: {"results": results}})())
    return model


def run_graph(answers: list[dict] | None = None):
    """Run to END, answering each interrupt with the next answer (then approving).

    Returns the final state values, the interrupt payloads and the nodes in run order.
    The blueprint is written to config.OUTPUT_DIR / "test" / "blueprint.md".
    """
    answers = list(answers or [])
    app = build_graph()
    cfg = {"configurable": {"thread_id": "test", "settings": SETTINGS}, "recursion_limit": 100}
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
