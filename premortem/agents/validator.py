"""Validator node: deterministic rules first, then the LLM judge."""

from premortem.schemas import Stage, ValidationResult
from premortem.state import LaunchState
from premortem.validation.judge import judge
from premortem.validation.rules import run_rules


def make_validator(stage: Stage):
    def validator(state: LaunchState) -> dict:
        issues = run_rules(stage, state)
        # A rule-level blocking issue (e.g. a target segment that does not exist) makes the
        # judge's review meaningless, so the judge only runs on structurally valid output.
        if not any(i.severity == "blocking" for i in issues):
            issues += judge(stage, state)
        passed = not any(i.severity == "blocking" for i in issues)
        return {"validations": [ValidationResult(stage=stage, passed=passed, issues=issues)]}

    validator.__name__ = f"validate_{stage}"
    return validator
