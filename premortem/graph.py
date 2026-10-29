"""Main graph: brief → analyst → strategist ⇄ validator → human approval → creative ⇄ validator → blueprint.

Revision loops are bounded by MAX_REVISIONS. When the limit is reached, the stage goes on
with its blocking issues unresolved: they stay in `validations`, are shown to the human
at the approval step and will be listed in the blueprint.

Human feedback stays in the state from a rejection until the next approval, so the
Strategist and the strategy judge see it in every revision that follows the rejection.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from premortem import config, schemas
from premortem.agents.analyst import build_analyst
from premortem.agents.creative import creative
from premortem.agents.revision import blocking_issues, latest_validation
from premortem.agents.strategist import strategist
from premortem.agents.validator import make_validator
from premortem.ingestion.brief_extractor import extract_brief
from premortem.schemas import Stage
from premortem.state import LaunchState

# Used when the human rejects without writing anything, so the Strategist still revises
DEFAULT_FEEDBACK = "The company rejected this strategy without comments. Propose a different approach."
# The checkpointer restores the state at the interrupt: allow our Pydantic models explicitly
STATE_TYPES = [("premortem.schemas", name) for name, obj in vars(schemas).items()
               if isinstance(obj, type) and obj.__module__ == schemas.__name__]


def initial_state(document_text: str) -> LaunchState:
    return {
        "document_text": document_text,
        "brief": None,
        "analysis": None,
        "strategy": None,
        "campaign": None,
        "validations": [],
        "strategy_revisions": 0,
        "campaign_revisions": 0,
        "human_feedback": None,
    }


def extract_brief_node(state: LaunchState) -> dict:
    return {"brief": extract_brief(state["document_text"])}


def _route_revision(state: LaunchState, stage: Stage, revisions: int) -> str:
    return "revise" if blocking_issues(state, stage) and revisions < config.MAX_REVISIONS else "ok"


def route_strategy(state: LaunchState) -> str:
    return _route_revision(state, "strategy", state.get("strategy_revisions", 0))


def route_campaign(state: LaunchState) -> str:
    return _route_revision(state, "campaign", state.get("campaign_revisions", 0))


def human_approval(state: LaunchState) -> dict:
    """Pause the graph until the human answers with Command(resume={"approved": bool, "feedback": str})."""
    validation = latest_validation(state, "strategy")
    answer = interrupt(
        {
            "strategy": state["strategy"].model_dump(),
            "issues": [i.model_dump() for i in validation.issues] if validation else [],
            "unresolved": bool(blocking_issues(state, "strategy")),
            "strategy_revisions": state.get("strategy_revisions", 0),
        }
    )
    if answer.get("approved"):
        return {"human_feedback": None}
    # A rejection starts a new budget for the validation loop
    return {"human_feedback": (answer.get("feedback") or "").strip() or DEFAULT_FEEDBACK, "strategy_revisions": 0}


def route_human(state: LaunchState) -> str:
    return "rejected" if state.get("human_feedback") else "approved"


def build_blueprint_node(state: LaunchState) -> dict:
    """Placeholder until Phase 9 (render_blueprint)."""
    return {}


def build_graph(checkpointer=None):
    g = StateGraph(LaunchState)
    g.add_node("extract_brief", extract_brief_node)
    g.add_node("analyst", build_analyst())
    g.add_node("validate_analysis", make_validator("analysis"))
    g.add_node("strategist", strategist)
    g.add_node("validate_strategy", make_validator("strategy"))
    g.add_node("human_approval", human_approval)
    g.add_node("creative", creative)
    g.add_node("validate_campaign", make_validator("campaign"))
    g.add_node("blueprint", build_blueprint_node)

    g.set_entry_point("extract_brief")
    g.add_edge("extract_brief", "analyst")
    g.add_edge("analyst", "validate_analysis")
    g.add_edge("validate_analysis", "strategist")  # analysis issues are warnings only
    g.add_edge("strategist", "validate_strategy")
    g.add_conditional_edges("validate_strategy", route_strategy, {"revise": "strategist", "ok": "human_approval"})
    g.add_conditional_edges("human_approval", route_human, {"approved": "creative", "rejected": "strategist"})
    g.add_edge("creative", "validate_campaign")
    g.add_conditional_edges("validate_campaign", route_campaign, {"revise": "creative", "ok": "blueprint"})
    g.add_edge("blueprint", END)
    return g.compile(checkpointer=checkpointer or MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)))
