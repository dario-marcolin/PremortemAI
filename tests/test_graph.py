"""Routing, revision loops and human approval of the main graph (fake LLMs, offline)."""

import pytest

from premortem import config
from premortem.graph import DEFAULT_FEEDBACK, route_campaign, route_human, route_strategy
from premortem.schemas import ValidationIssue, ValidationResult
from tests.graph_fakes import BLOCK_CAMPAIGN, BLOCK_STRATEGY, FakeModel, install, run_graph


def validation(stage, severity):
    issues = [ValidationIssue(severity=severity, check="c", message="m")] if severity else []
    return ValidationResult(stage=stage, passed=severity != "blocking", issues=issues)


@pytest.mark.parametrize(
    "severity, revisions, expected",
    [("blocking", 0, "revise"), ("blocking", config.MAX_REVISIONS - 1, "revise"),
     ("blocking", config.MAX_REVISIONS, "ok"), ("warning", 0, "ok"), (None, 0, "ok")],
)
def test_route_revision(severity, revisions, expected):
    for stage, route in (("strategy", route_strategy), ("campaign", route_campaign)):
        # An older blocking result of the same stage must not count: only the latest one does
        state = {"validations": [validation(stage, "blocking"), validation(stage, severity)],
                 f"{stage}_revisions": revisions}
        assert route(state) == expected


def test_route_human():
    assert route_human({"human_feedback": "Target SEG2"}) == "rejected"
    assert route_human({"human_feedback": None}) == "approved"


def test_strategy_revised_once_then_approved(monkeypatch):
    install(monkeypatch, FakeModel(judge={"strategy": lambda call: [BLOCK_STRATEGY] if call == 0 else []}))
    values, payloads, nodes = run_graph()
    assert nodes[3:8] == ["strategist", "validate_strategy", "strategist", "validate_strategy", "human_approval"]
    assert values["strategy_revisions"] == 1
    assert payloads[0]["unresolved"] is False


def test_strategy_loop_stops_after_max_revisions_and_carries_issues(monkeypatch):
    model = install(monkeypatch, FakeModel(judge={"strategy": [BLOCK_STRATEGY]}))
    values, payloads, nodes = run_graph()
    assert nodes.count("strategist") == config.MAX_REVISIONS + 1
    assert values["strategy_revisions"] == config.MAX_REVISIONS
    # The revisions received the blocking issue
    assert all("segment_size_and_access" in p for p in model.prompts["Strategy"][1:])
    # The human sees the unresolved issue, and it stays in the history after approval
    assert payloads[0]["unresolved"] is True
    assert [i["check"] for i in payloads[0]["issues"]] == ["judge.segment_size_and_access"]
    strategy_results = [v for v in values["validations"] if v.stage == "strategy"]
    assert len(strategy_results) == config.MAX_REVISIONS + 1 and not strategy_results[-1].passed
    assert nodes[-1] == "blueprint"


def test_rejection_sends_feedback_to_strategist_and_judge(monkeypatch):
    model = install(monkeypatch, FakeModel())
    values, payloads, nodes = run_graph([{"approved": False, "feedback": "Target SEG2 instead."}])
    assert len(payloads) == 2
    assert nodes.count("strategist") == 2 and nodes.count("human_approval") == 2
    assert "Target SEG2 instead." in model.prompts["Strategy"][1]
    assert "<human_feedback>" in model.prompts["judge_strategy"][1]
    assert values["human_feedback"] is None  # cleared on approval
    assert "<human_feedback>" not in model.prompts["judge_campaign"][0]


def test_rejection_resets_the_budget_and_keeps_feedback_in_every_revision(monkeypatch):
    model = install(monkeypatch, FakeModel(judge={"strategy": [BLOCK_STRATEGY]}))
    _, payloads, nodes = run_graph([{"approved": False, "feedback": "Target SEG2 instead."}])
    # Before the rejection: 1 strategy + MAX_REVISIONS revisions. After it, the first revision
    # answers the feedback and the unresolved blocking issue, so it counts: MAX_REVISIONS runs
    assert nodes.count("strategist") == (config.MAX_REVISIONS + 1) + config.MAX_REVISIONS
    assert [p["strategy_revisions"] for p in payloads] == [config.MAX_REVISIONS] * 2
    after_rejection = model.prompts["Strategy"][config.MAX_REVISIONS + 1:]
    assert all("Target SEG2 instead." in p for p in after_rejection)


def test_rejection_without_text_uses_default_feedback(monkeypatch):
    model = install(monkeypatch, FakeModel())
    run_graph([{"approved": False, "feedback": "  "}])
    assert DEFAULT_FEEDBACK in model.prompts["Strategy"][1]


def test_campaign_loop_stops_after_max_revisions(monkeypatch):
    install(monkeypatch, FakeModel(judge={"campaign": [BLOCK_CAMPAIGN]}))
    values, _, nodes = run_graph()
    assert nodes.count("creative") == config.MAX_REVISIONS + 1
    assert values["campaign_revisions"] == config.MAX_REVISIONS
    assert not values["validations"][-1].passed  # carried to the blueprint
    assert nodes[-1] == "blueprint"
