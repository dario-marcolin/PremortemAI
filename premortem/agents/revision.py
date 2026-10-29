"""Revision input shared by the Strategist and the Creative.

A node revises when the last validation of its stage has blocking issues, or when the
human left feedback. The previous output, every issue of that validation and the
feedback are then added to the prompt. The Strategist clears the feedback once used.
"""

from pydantic import BaseModel

from premortem.schemas import Stage, ValidationResult
from premortem.state import LaunchState


def latest_validation(state: LaunchState, stage: Stage) -> ValidationResult | None:
    return next((v for v in reversed(state.get("validations") or []) if v.stage == stage), None)


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
