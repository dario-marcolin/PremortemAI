import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from premortem.agents import creative as creative_module
from premortem.agents import strategist as strategist_module
from premortem.schemas import ValidationIssue, ValidationResult
from premortem.state import LaunchState

FIXTURE = Path(__file__).parent / "fixtures" / "dummy_state.json"


class FakeLLM:
    """Records the prompt and returns the fixture's own strategy or campaign."""

    def __init__(self, output):
        self.output = output
        self.prompt = None

    def with_structured_output(self, _schema):
        return self

    def invoke(self, messages):
        self.prompt = messages[-1].content
        return self.output


@pytest.fixture
def state() -> dict:
    return TypeAdapter(LaunchState).validate_python(json.loads(FIXTURE.read_text()))


def first_run(state, stage):
    """The state as the node sees it the first time: no output, no validations, no feedback."""
    return {**state, stage: None, "validations": [], "human_feedback": None, f"{stage}_revisions": 0}


def blocking(stage):
    issue = ValidationIssue(severity="blocking", check="target_exists", message="SEG9 is not in the analysis.")
    return ValidationResult(stage=stage, passed=False, issues=[issue])


def run(monkeypatch, module, node, state, output):
    llm = FakeLLM(output)
    monkeypatch.setattr(module, "get_llm", lambda *_a, **_k: llm)
    return node(state), llm.prompt


def test_strategist_first_run(monkeypatch, state):
    out, prompt = run(monkeypatch, strategist_module, strategist_module.strategist,
                      first_run(state, "strategy"), state["strategy"])
    assert out["strategy_revisions"] == 0
    assert "Revise" not in prompt and "<analysis>" in prompt


def test_strategist_revises_on_blocking_issue(monkeypatch, state):
    state["validations"] = [*state["validations"], blocking("strategy")]
    state["human_feedback"] = None
    out, prompt = run(monkeypatch, strategist_module, strategist_module.strategist, state, state["strategy"])
    assert out["strategy_revisions"] == state["strategy_revisions"] + 1
    assert "Revise the strategy." in prompt and "SEG9 is not in the analysis." in prompt
    assert "<previous_strategy>" in prompt


def test_strategist_revises_on_human_feedback(monkeypatch, state):
    state["validations"] = [v for v in state["validations"] if v.passed]
    state["human_feedback"] = "Target office workers instead."
    state["strategy_revisions"] = 0  # human_approval resets the counter on a rejection
    out, prompt = run(monkeypatch, strategist_module, strategist_module.strategist, state, state["strategy"])
    # Feedback alone does not use the validation budget, and only human_approval clears it
    assert out["strategy_revisions"] == 0 and "human_feedback" not in out
    assert "Target office workers instead." in prompt


def test_strategist_keeps_feedback_in_validator_revisions(monkeypatch, state):
    state["validations"] = [*state["validations"], blocking("strategy")]
    state["human_feedback"] = "Target office workers instead."
    state["strategy_revisions"] = 0
    out, prompt = run(monkeypatch, strategist_module, strategist_module.strategist, state, state["strategy"])
    assert out["strategy_revisions"] == 1
    assert "Target office workers instead." in prompt and "SEG9 is not in the analysis." in prompt


def test_strategist_retries_then_fails_on_missing_output(monkeypatch, state):
    with pytest.raises(RuntimeError, match="no structured output"):
        run(monkeypatch, strategist_module, strategist_module.strategist, first_run(state, "strategy"), None)


def test_strategist_ignores_warnings_and_other_stages(monkeypatch, state):
    # The fixture's last strategy validation passed; the campaign warning must not trigger a revision
    state["human_feedback"] = None
    out, _ = run(monkeypatch, strategist_module, strategist_module.strategist, state, state["strategy"])
    assert out["strategy_revisions"] == state["strategy_revisions"]


def test_creative_first_run_gets_target_segment(monkeypatch, state):
    out, prompt = run(monkeypatch, creative_module, creative_module.creative,
                      first_run(state, "campaign"), state["campaign"])
    assert out["campaign_revisions"] == 0
    assert "Urban coffee enthusiasts" in prompt and "Gift buyers" not in prompt


def test_creative_revises_on_blocking_issue_but_not_on_feedback(monkeypatch, state):
    # Human feedback is about the strategy: it must not make the Creative revise
    out, _ = run(monkeypatch, creative_module, creative_module.creative, state, state["campaign"])
    assert out["campaign_revisions"] == 0
    state["validations"] = [*state["validations"], blocking("campaign")]
    out, prompt = run(monkeypatch, creative_module, creative_module.creative, state, state["campaign"])
    assert out["campaign_revisions"] == 1
    assert "Revise the campaign." in prompt and "<previous_campaign>" in prompt
