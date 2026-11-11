"""Strategist: Analysis → Strategy (segmentation, targeting, positioning)."""

from langchain_core.messages import HumanMessage, SystemMessage

from premortem.agents.revision import blocking_issues, revision_request
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
    llm = get_llm("strategist").with_structured_output(Strategy)
    strategy = invoke_structured(llm, [SystemMessage(load_prompt("strategist")), HumanMessage(content)])
    # Only revisions that answer blocking issues count toward MAX_REVISIONS. The feedback
    # stays in the state (human_approval resets the counter and clears it on approval),
    # so it is not a reason to count a revision.
    revisions = state.get("strategy_revisions", 0)
    if state.get("strategy") is not None and blocking_issues(state, "strategy"):
        revisions += 1
    return {"strategy": strategy, "strategy_revisions": revisions}
