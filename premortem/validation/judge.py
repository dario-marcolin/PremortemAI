"""LLM-as-judge: challenges a stage with an explicit rubric (prompts/judge.md).

The judge must quote the input field each objection relies on. The quote is checked in
code: a blocking issue whose quote is not in the input is downgraded to a warning, so an
objection the judge cannot trace never sends a stage back for revision.
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from premortem import config
from premortem.llm import get_llm
from premortem.prompts import load_prompt
from premortem.schemas import Severity, Stage, ValidationIssue
from premortem.state import LaunchState


class JudgeIssue(BaseModel):
    severity: Severity = Field(description="'blocking' if the stage must be revised, otherwise 'warning'.")
    check: str = Field(description="Rubric item id, e.g. 'segment_size_and_access'.")
    field: str = Field(description="Input field the objection relies on, e.g. 'analysis.segments[SEG1].estimated_size'.")
    quote: str = Field(description="Exact words copied from that field of the input.")
    message: str = Field(description="What is wrong, with the figures involved, and how to fix it.")


class JudgeVerdict(BaseModel):
    issues: list[JudgeIssue] = Field(default_factory=list, description="Problems found; empty if the stage is fine.")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def judge_input(stage: Stage, state: LaunchState) -> str:
    parts = [f"<brief>\n{state['brief'].model_dump_json(indent=2)}\n</brief>"]
    if state.get("document_text"):
        parts.append(f"<document>\n{state['document_text']}\n</document>")
    if stage in ("analysis", "strategy"):
        parts.append(f"<analysis>\n{state['analysis'].model_dump_json(indent=2)}\n</analysis>")
    if stage in ("strategy", "campaign"):
        parts.append(f"<strategy>\n{state['strategy'].model_dump_json(indent=2)}\n</strategy>")
    if stage == "strategy" and state.get("human_feedback"):
        parts.append(f"<human_feedback>\n{state['human_feedback']}\n</human_feedback>")
    if stage == "campaign":
        strategy = state["strategy"]
        segment = next((s for s in state["analysis"].segments if s.segment_id == strategy.target_segment_id), None)
        if segment:
            parts.append(f"<target_segment>\n{segment.model_dump_json(indent=2)}\n</target_segment>")
        parts.append(f"<campaign>\n{state['campaign'].model_dump_json(indent=2)}\n</campaign>")
    return "\n\n".join(parts)


def to_validation_issues(stage: Stage, verdict: JudgeVerdict, context: str) -> list[ValidationIssue]:
    haystack = _normalize(context)
    issues = []
    for i in verdict.issues:
        severity, message = i.severity, f'{i.message} Evidence: {i.field} = "{i.quote}"'
        if stage == "analysis":
            severity = "warning"  # the graph never sends the analysis back
        elif severity == "blocking" and _normalize(i.quote) not in haystack:
            severity = "warning"
            message += " (quote not found in the input: downgraded to warning)"
        issues.append(ValidationIssue(severity=severity, check=f"judge.{i.check}", message=message))
    return issues


def judge(stage: Stage, state: LaunchState) -> list[ValidationIssue]:
    context = judge_input(stage, state)
    llm = get_llm(temperature=config.JUDGE_TEMPERATURE, model=config.JUDGE_MODEL).with_structured_output(JudgeVerdict)
    verdict = llm.invoke(
        [
            SystemMessage(load_prompt("judge")),
            HumanMessage(f"{context}\n\nValidate the {stage} with the {stage} rubric."),
        ]
    )
    return to_validation_issues(stage, verdict, context)
