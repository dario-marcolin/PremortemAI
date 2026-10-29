"""End-to-end run of the main graph with fake LLMs, auto-approving at the interrupt."""

from premortem.graph import build_graph
from tests.graph_fakes import STATE, FakeModel, install, run_graph

PIPELINE = ["extract_brief", "analyst", "validate_analysis", "strategist", "validate_strategy",
            "human_approval", "creative", "validate_campaign", "blueprint"]


def test_graph_has_the_nine_nodes():
    assert set(PIPELINE) <= set(build_graph().get_graph().nodes)


def test_auto_approved_run_reaches_end_with_every_field_filled(monkeypatch):
    install(monkeypatch, FakeModel())
    values, payloads, nodes = run_graph()

    assert nodes == PIPELINE
    for field in ("brief", "analysis", "strategy", "campaign"):
        assert values[field] is not None, field
    assert [v.stage for v in values["validations"]] == ["analysis", "strategy", "campaign"]
    assert all(v.passed for v in values["validations"])
    assert values["strategy_revisions"] == 0 and values["campaign_revisions"] == 0
    assert values["human_feedback"] is None
    # The subgraph state (messages) does not leak into LaunchState
    assert "messages" not in values


def test_analyst_searches_and_keeps_web_sources(monkeypatch):
    model = install(monkeypatch, FakeModel())
    values, _, _ = run_graph()
    assert len(model.prompts["analyst_llm"]) == 2  # one search turn, then done
    assert [s.reference for s in values["analysis"].sources] == [s.reference for s in STATE["analysis"].sources]


def test_human_sees_strategy_and_issues(monkeypatch):
    install(monkeypatch, FakeModel())
    _, payloads, _ = run_graph()
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["strategy"]["target_segment_id"] == STATE["strategy"].target_segment_id
    assert payload["unresolved"] is False and payload["strategy_revisions"] == 0
    # The fixture's SEG1 has an estimated_size; the rule-level warnings, if any, are listed
    assert all({"severity", "check", "message"} <= set(i) for i in payload["issues"])
