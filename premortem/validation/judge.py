"""LLM-as-judge: challenges a stage with an explicit rubric (prompts/judge.md).

The judge must quote the input field each objection relies on. The quote is checked in
code against the values of that field: a blocking issue whose quote is too short or is
not in the field is downgraded to a warning, so an objection the judge cannot trace never
sends a stage back for revision.
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from premortem.llm import get_llm, invoke_structured, is_anthropic
from premortem.prompts import load_prompt
from premortem.schemas import Severity, Stage, ValidationIssue
from premortem.state import LaunchState

# A blocking quote must be a real extract: at least this long, or a whole field value
MIN_QUOTE_CHARS = 12
FIELD_PART = re.compile(r"(\w+)|\[([^\]]+)\]")


class JudgeIssue(BaseModel):
    severity: Severity = Field(description="'blocking' if the stage must be revised, otherwise 'warning'.")
    check: str = Field(description="Rubric item id, e.g. 'segment_size_and_access'.")
    field: str = Field(description="Input field the objection relies on, e.g. 'analysis.segments[SEG1].estimated_size'.")
    quote: str = Field(description="Exact words copied from that field of the input.")
    message: str = Field(description="What is wrong, with the figures involved, and how to fix it.")


class JudgeVerdict(BaseModel):
    issues: list[JudgeIssue] = Field(default_factory=list, description="Problems found; empty if the stage is fine.")


def _normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def judge_sections(stage: Stage, state: LaunchState) -> dict[str, BaseModel | str]:
    """The judge's inputs by tag name. brief and document come first in every stage, so
    the prompt prefix is identical across judge calls and can be cached."""
    sections: dict[str, BaseModel | str] = {"brief": state["brief"]}
    if state.get("document_text"):
        sections["document"] = state["document_text"]
    if stage in ("analysis", "strategy"):
        sections["analysis"] = state["analysis"]
    if stage in ("strategy", "campaign"):
        sections["strategy"] = state["strategy"]
    if stage == "strategy" and state.get("human_feedback"):
        sections["human_feedback"] = state["human_feedback"]
    if stage == "campaign":
        segment = state["analysis"].find_segment(state["strategy"].target_segment_id)
        if segment:
            sections["target_segment"] = segment
        sections["campaign"] = state["campaign"]
    return sections


def _render(sections: dict[str, BaseModel | str]) -> str:
    return "\n\n".join(
        f"<{tag}>\n{value.model_dump_json(indent=2) if isinstance(value, BaseModel) else value}\n</{tag}>"
        for tag, value in sections.items()
    )


def judge_input(stage: Stage, state: LaunchState) -> str:
    return _render(judge_sections(stage, state))


def _leaves(value) -> list[str]:
    """Every text value under a node (JSON keys excluded), so quotes are matched unescaped."""
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if isinstance(value, dict):
        return [t for v in value.values() for t in _leaves(v)]
    if isinstance(value, list):
        return [t for v in value for t in _leaves(v)]
    return [] if value is None else [str(value)]


def _step(node, name: str | None, key: str | None):
    if isinstance(node, BaseModel):
        node = node.model_dump()
    if name and isinstance(node, dict):
        return node.get(name)
    if key and isinstance(node, list):
        if key.isdigit():
            return node[int(key)] if int(key) < len(node) else None
        # segments[SEG1], competitors[Brand], key_messages[Instagram]: match any text value of the item
        key = _normalize(key)
        return next((item for item in node if key in (_normalize(v) for v in _leaves(item))), None)
    return None


def field_values(field: str, sections: dict[str, BaseModel | str]) -> list[str]:
    """Text values of the field the judge names, e.g. 'analysis.segments[SEG1].estimated_size'.

    The path is followed as far as it resolves; an unknown root falls back to all inputs.
    """
    parts = FIELD_PART.findall(field)
    if not parts or parts[0][0] not in sections:
        return _leaves(list(sections.values()))
    node = sections[parts[0][0]]
    for name, key in parts[1:]:
        child = _step(node, name, key)
        if child is None:
            break
        node = child
    return _leaves(node)


def quote_is_traceable(issue: JudgeIssue, sections: dict[str, BaseModel | str]) -> bool:
    quote = _normalize(issue.quote)
    if not quote:
        return False
    values = [_normalize(v) for v in field_values(issue.field, sections)]
    return any(quote == v or (len(quote) >= MIN_QUOTE_CHARS and quote in v) for v in values)


def to_validation_issues(
    stage: Stage, verdict: JudgeVerdict, sections: dict[str, BaseModel | str]
) -> list[ValidationIssue]:
    issues = []
    for i in verdict.issues:
        severity, message = i.severity, f'{i.message} Evidence: {i.field} = "{i.quote}"'
        if stage == "analysis":
            severity = "warning"  # the graph never sends the analysis back
        elif severity == "blocking" and not quote_is_traceable(i, sections):
            severity = "warning"
            message += " (quote not found in that field of the input: downgraded to warning)"
        issues.append(ValidationIssue(severity=severity, check=f"judge.{i.check}", message=message))
    return issues


def _prompt(stage: Stage, sections: dict[str, BaseModel | str]) -> HumanMessage:
    """brief + document form a block shared by every judge call: mark it for prompt
    caching on Anthropic models, so a run does not pay for the full document each time."""
    shared = {tag: sections[tag] for tag in ("brief", "document") if tag in sections}
    rest = {tag: value for tag, value in sections.items() if tag not in shared}
    prefix = {"type": "text", "text": _render(shared)}
    if is_anthropic("validator"):
        prefix["cache_control"] = {"type": "ephemeral"}
    return HumanMessage(
        [prefix, {"type": "text", "text": f"{_render(rest)}\n\nValidate the {stage} with the {stage} rubric."}]
    )


def judge(stage: Stage, state: LaunchState) -> list[ValidationIssue]:
    sections = judge_sections(stage, state)
    llm = get_llm("validator").with_structured_output(JudgeVerdict)
    try:
        verdict = invoke_structured(llm, [SystemMessage(load_prompt("judge")), _prompt(stage, sections)])
    except (RuntimeError, ValidationError) as e:
        # The rules already ran: a missing or malformed verdict is reported, it does not stop the run
        return [ValidationIssue(severity="warning", check="judge.no_verdict",
                                message=f"The judge did not run: {str(e).splitlines()[0]}.")]
    return to_validation_issues(stage, verdict, sections)
