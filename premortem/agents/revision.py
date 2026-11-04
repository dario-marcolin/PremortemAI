"""Revision input shared by the Strategist and the Creative.

A node revises when the last validation of its stage has blocking issues, or when the
human left feedback. The previous output, every issue of that validation and the
feedback are then added to the prompt. The feedback stays in the state until the human
approves (see graph.human_approval).
"""

from pydantic import BaseModel

from premortem.schemas import Stage, ValidationIssue, ValidationResult
from premortem.state import LaunchState


def latest_validation(state: LaunchState, stage: Stage) -> ValidationResult | None:
    return next((v for v in reversed(state.get("validations") or []) if v.stage == stage), None)


def blocking_issues(state: LaunchState, stage: Stage) -> list[ValidationIssue]:
    """Blocking issues of the latest validation of a stage (empty if it passed)."""
    validation = latest_validation(state, stage)
    return [i for i in validation.issues if i.severity == "blocking"] if validation else []


def revision_request(
    state: LaunchState, stage: Stage, previous: BaseModel | None, feedback: str | None = None
) -> str | None:
    """Text to append to the prompt when the node must revise, otherwise None."""
    validation = latest_validation(state, stage) if previous is not None else None
    issues = validation.issues if validation else []
    if not feedback and not any(i.severity == "blocking" for i in issues):
        return None

    parts = [f"Revise the {stage}."]
    if previous is not None:
        parts.append(f"<previous_{stage}>\n{previous.model_dump_json(indent=2)}\n</previous_{stage}>")
    if issues:
        lines = "\n".join(f"- [{i.severity}] {i.check}: {i.message}" for i in issues)
        parts.append(f"<validation_issues>\n{lines}\n</validation_issues>")
    if feedback:
        parts.append(f"<human_feedback>\n{feedback}\n</human_feedback>")
    return "\n\n".join(parts)
