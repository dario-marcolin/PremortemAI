import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from premortem import config
from premortem.agents import analyst
from premortem.schemas import Analysis, CompanyBrief, Competitor, MarketSegment, Source
from premortem.tools import web_search as ws

BRIEF = CompanyBrief(
    company_name="Acme",
    company_description="Snack maker",
    product_name="Crisps",
    product_description="Chickpea crisps",
    target_country="France",
)
URL = "https://example.fr/report"


def make_analysis(sources, competitor_ids=("S1",), segment_ids=("S1",), size="2M adults, S1"):
    return Analysis(
        market_overview="Worth 480M euros [S1].",
        competitors=[Competitor(name="Brand", positioning="p", price_level="unknown", source_ids=list(competitor_ids))],
        customer_needs=["Protein [S1]"],
        segments=[
            MarketSegment(
                segment_id="SEG1", label="l", description="72% intent [S1]", needs=["n"],
                estimated_size=size, source_ids=list(segment_ids),
            )
        ],
        sources=sources,
    )


class FakeLLM:
    """Replays tool-calling turns, then returns a fixed Analysis for the report."""

    def __init__(self, turns, analysis):
        self.turns = list(turns)
        self.analysis = analysis
        self.calls = 0

    def bind_tools(self, _tools):
        return self

    def with_structured_output(self, _schema):
        return type("Structured", (), {"invoke": lambda _self, _messages: self.analysis})()

    def invoke(self, _messages):
        self.calls += 1
        return self.turns.pop(0) if self.turns else AIMessage("Done.")


def search_turn(i):
    return AIMessage("", tool_calls=[{"name": "web_search", "args": {"query": f"q{i}"}, "id": f"c{i}"}])


@pytest.fixture
def fake_search(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    response = {"results": [{"title": "Report", "url": URL, "content": "480M euros"}]}
    monkeypatch.setattr(ws, "_client", lambda: type("C", (), {"invoke": lambda _s, _i: response})())


def run(monkeypatch, llm):
    monkeypatch.setattr(analyst, "get_llm", lambda: llm)
    return analyst.build_analyst().invoke({"brief": BRIEF, "document_text": "Doc text", "messages": []})


def test_subgraph_searches_then_reports(monkeypatch, fake_search):
    sources = [Source(id="S1", kind="document", reference="Doc, section 4"), Source(id="S2", kind="web", reference=URL)]
    llm = FakeLLM([search_turn(1)], make_analysis(sources, competitor_ids=("S2",)))
    out = run(monkeypatch, llm)
    assert llm.calls == 2
    assert [s.reference for s in out["analysis"].sources] == ["Doc, section 4", URL]
    assert out["analysis"].competitors[0].source_ids == ["S2"]


def test_tool_rounds_are_capped(monkeypatch, fake_search):
    sources = [Source(id="S1", kind="document", reference="Doc")]
    llm = FakeLLM([search_turn(i) for i in range(50)], make_analysis(sources))
    out = run(monkeypatch, llm)
    assert analyst._tool_rounds(out["messages"]) == analyst.MAX_TOOL_ROUNDS + 1  # last call is not executed
    assert llm.calls == analyst.MAX_TOOL_ROUNDS + 1


def test_invented_url_is_removed_and_ids_renumbered():
    sources = [
        Source(id="S1", kind="web", reference="https://invented.com"),
        Source(id="S2", kind="web", reference=URL.replace("https://", "http://www.") + "/"),
        Source(id="S3", kind="document", reference="Doc, section 5"),
    ]
    analysis = make_analysis(sources, competitor_ids=("S1", "S2"), segment_ids=("S3",), size="1.3M adults, S3")
    out = analyst.normalize_sources(analysis, {URL})
    assert [(s.id, s.reference) for s in out.sources] == [("S1", "Doc, section 5"), ("S2", URL)]
    assert out.competitors[0].source_ids == ["S2"]
    assert out.segments[0].source_ids == ["S1"]
    assert out.segments[0].estimated_size == "1.3M adults, S1"
    assert out.market_overview == "Worth 480M euros [S?]."  # cited the removed source
    assert any("invented.com" in n for n in out.data_quality_notes)


def test_notes_are_renumbered_and_uncited_sources_dropped():
    sources = [
        Source(id="S1", kind="document", reference="Doc, section 1"),  # cited by nothing
        Source(id="S2", kind="document", reference="Doc, section 4"),
        Source(id="S3", kind="web", reference=URL),
    ]
    analysis = make_analysis(sources, competitor_ids=("S3",), segment_ids=("S2",), size=None)
    analysis = analysis.model_copy(
        update={"market_overview": "480M [S2].", "customer_needs": [], "data_quality_notes": ["Conflict with [S3]."]}
    )
    analysis.segments[0].description = "72% intent [S2]"
    out = analyst.normalize_sources(analysis, {URL})
    assert [s.reference for s in out.sources] == ["Doc, section 4", URL]
    assert out.data_quality_notes == ["Conflict with [S2]."]
    assert out.market_overview == "480M [S1]."


def test_unknown_citation_is_dropped_with_note():
    analysis = make_analysis([Source(id="S1", kind="document", reference="Doc")], competitor_ids=("S1", "S9"))
    out = analyst.normalize_sources(analysis, set())
    assert out.competitors[0].source_ids == ["S1"]
    assert any("Competitor Brand: removed 1 citation" in n for n in out.data_quality_notes)


def test_research_log_and_urls():
    messages = [search_turn(1), ToolMessage(json.dumps([{"title": "t", "url": URL}]), tool_call_id="c1"),
                ToolMessage(json.dumps([{"error": "No results"}]), tool_call_id="c2")]
    assert "Search: q1" in analyst.research_log(messages)
    assert analyst.searched_urls(messages) == {URL}


def test_unanswered_search_is_marked_not_run():
    messages = [search_turn(1), ToolMessage("[]", tool_call_id="c1"), search_turn(2)]
    log = analyst.research_log(messages)
    assert "Search: q1" in log and "Search not run (limit reached): q2" in log


def test_product_names_are_not_taken_for_source_ids():
    sources = [Source(id="S1", kind="document", reference="Doc"), Source(id="S3", kind="web", reference=URL)]
    analysis = make_analysis(sources, competitor_ids=("S3",))
    analysis.competitors[0].positioning = "Bundled with Galaxy S24 phones [S3]"
    out = analyst.normalize_sources(analysis, {URL})
    assert out.competitors[0].positioning == "Bundled with Galaxy S24 phones [S2]"
