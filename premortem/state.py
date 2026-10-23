"""Graph state. Frozen after Phase 1, like schemas.py."""

import operator
from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import TypedDict

from premortem.schemas import Analysis, Campaign, CompanyBrief, Strategy, ValidationResult


class LaunchState(TypedDict):
    document_text: str
    brief: CompanyBrief | None
    analysis: Analysis | None
    strategy: Strategy | None
    campaign: Campaign | None
    # Appended by every validation node, never overwritten.
    validations: Annotated[list[ValidationResult], operator.add]
    strategy_revisions: int
    campaign_revisions: int
    human_feedback: str | None


class AnalystState(MessagesState, total=False):
    brief: CompanyBrief
    document_text: str
    analysis: Analysis
