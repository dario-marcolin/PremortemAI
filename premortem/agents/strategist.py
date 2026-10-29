"""Strategist: Analysis → Strategy (segmentation, targeting, positioning)."""

from langchain_core.messages import HumanMessage, SystemMessage

from premortem.agents.revision import revision_request
from premortem.llm import get_llm, invoke_structured
from premortem.prompts import load_prompt
from premortem.schemas import Strategy
from premortem.state import LaunchState


def strategist(state: LaunchState) -> dict:
    feedback = state.get("human_feedback")
    revision = revision_request(state, "strategy", state.get("strategy"), feedback)
    content = (
        f"<brief>\n{state['brief'].model_dump_json(indent=2)}\n</brief>\n\n"
        f"<analysis>\n{state['analysis'].model_dump_json(indent=2)}\n</analysis>\n\n"
        + (revision or "Write the launch strategy.")
    )
    llm = get_llm().with_structured_output(Strategy)
    strategy = invoke_structured(llm, [SystemMessage(load_prompt("strategist")), HumanMessage(content)])
    # Feedback is used once, then cleared. Only validator-driven revisions count toward
    # MAX_REVISIONS: a human rejection starts a new budget for the validation loop.
    revisions = state.get("strategy_revisions", 0)
    if feedback:
        revisions = 0
    elif revision:
        revisions += 1
    return {"strategy": strategy, "strategy_revisions": revisions, "human_feedback": None}
