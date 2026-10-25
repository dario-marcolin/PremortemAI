"""Strategist: Analysis → Strategy (segmentation, targeting, positioning)."""

from langchain_core.messages import HumanMessage, SystemMessage

from premortem.agents.revision import revision_request
from premortem.llm import get_llm
from premortem.prompts import load_prompt
from premortem.schemas import Strategy
from premortem.state import LaunchState


def strategist(state: LaunchState) -> dict:
    revision = revision_request(state, "strategy", state.get("strategy"), state.get("human_feedback"))
    content = (
        f"<brief>\n{state['brief'].model_dump_json(indent=2)}\n</brief>\n\n"
        f"<analysis>\n{state['analysis'].model_dump_json(indent=2)}\n</analysis>\n\n"
        + (revision or "Write the launch strategy.")
    )
    llm = get_llm().with_structured_output(Strategy)
    strategy = llm.invoke([SystemMessage(load_prompt("strategist")), HumanMessage(content)])
    revisions = state.get("strategy_revisions", 0)
    return {"strategy": strategy, "strategy_revisions": revisions + 1 if revision else revisions}
