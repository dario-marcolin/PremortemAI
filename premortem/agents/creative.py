"""Creative: approved Strategy → Campaign."""

from langchain_core.messages import HumanMessage, SystemMessage

from premortem.agents.revision import revision_request
from premortem.llm import get_llm, invoke_structured
from premortem.prompts import load_prompt
from premortem.schemas import Campaign
from premortem.state import LaunchState


def creative(state: LaunchState) -> dict:
    strategy = state["strategy"]
    segment = state["analysis"].find_segment(strategy.target_segment_id)
    revision = revision_request(state, "campaign", state.get("campaign"))
    content = (
        f"<brief>\n{state['brief'].model_dump_json(indent=2)}\n</brief>\n\n"
        f"<strategy>\n{strategy.model_dump_json(indent=2)}\n</strategy>\n\n"
        f"<target_segment>\n{segment.model_dump_json(indent=2) if segment else 'Not found in the analysis.'}\n"
        "</target_segment>\n\n"
        + (revision or "Write the launch campaign.")
    )
    llm = get_llm("creative").with_structured_output(Campaign)
    campaign = invoke_structured(llm, [SystemMessage(load_prompt("creative")), HumanMessage(content)])
    revisions = state.get("campaign_revisions", 0)
    return {"campaign": campaign, "campaign_revisions": revisions + 1 if revision else revisions}
