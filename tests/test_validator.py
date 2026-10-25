import json
from pathlib import Path

import pytest

from premortem.agents import validator as validator_module
from premortem.schemas import Analysis, CompanyBrief, Strategy
from premortem.validation import judge as judge_module
from premortem.validation.judge import JudgeIssue, JudgeVerdict

FIXTURE = Path(__file__).parent / "fixtures" / "small_segment_case.json"


@pytest.fixture
def state() -> dict:
    data = json.loads(FIXTURE.read_text())
    return {
        "brief": CompanyBrief(**data["brief"]),
        "analysis": Analysis(**data["analysis"]),
        "strategy": Strategy(**data["strategy_small_segment"]),
        "validations": [],
        "human_feedback": None,
    }


class FakeJudge:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        self.calls += 1
        return self.verdict


def install(monkeypatch, *issues):
    fake = FakeJudge(JudgeVerdict(issues=list(issues)))
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=None, model=None: fake)
    return fake


def issue(severity="blocking", quote="1.3 million adults, 2.5% of adults"):
    return JudgeIssue(severity=severity, check="segment_size_and_access", field="analysis.segments[SEG1].estimated_size",
                      quote=quote, message="SEG1 is too small for the 2% share goal.")


def test_blocking_judge_issue_fails_the_stage(monkeypatch, state):
    install(monkeypatch, issue())
    result = validator_module.make_validator("strategy")(state)["validations"][0]
    assert not result.passed
    assert [(i.check, i.severity) for i in result.issues] == [("judge.segment_size_and_access", "blocking")]
    assert 'Evidence: analysis.segments[SEG1].estimated_size = "1.3 million adults' in result.issues[0].message


def test_quote_is_matched_ignoring_case_and_spaces(monkeypatch, state):
    install(monkeypatch, issue(quote="  1.3 MILLION adults,\n 2.5% of adults "))
    result = validator_module.make_validator("strategy")(state)["validations"][0]
    assert result.issues[0].severity == "blocking"


def test_invented_quote_is_downgraded(monkeypatch, state):
    install(monkeypatch, issue(quote="0.1% of adults"))
    result = validator_module.make_validator("strategy")(state)["validations"][0]
    assert result.passed
    assert result.issues[0].severity == "warning" and "quote not found" in result.issues[0].message


def test_analysis_issues_are_always_warnings(monkeypatch, state):
    install(monkeypatch, issue())
    result = validator_module.make_validator("analysis")(state)["validations"][0]
    assert result.passed and result.issues[0].severity == "warning"


def test_judge_is_skipped_when_a_rule_blocks(monkeypatch, state):
    fake = install(monkeypatch, issue())
    state["strategy"].target_segment_id = "SEG9"
    result = validator_module.make_validator("strategy")(state)["validations"][0]
    assert fake.calls == 0
    assert [i.check for i in result.issues] == ["target_segment_exists"]


def test_clean_stage_passes(monkeypatch, state):
    install(monkeypatch)
    node = validator_module.make_validator("strategy")
    assert node.__name__ == "validate_strategy"
    assert node(state)["validations"][0].model_dump() == {"stage": "strategy", "passed": True, "issues": []}


def test_feedback_reaches_the_strategy_judge_only(state):
    state["human_feedback"] = "Target vegans."
    assert "<human_feedback>" in judge_module.judge_input("strategy", state)
    assert "<human_feedback>" not in judge_module.judge_input("analysis", state)
