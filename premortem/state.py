"""Graph state. Frozen after Phase 1, like schemas.py."""

import operator
from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import TypedDict

from premortem.schemas import Analysis, Campaign, CompanyBrief, Strategy, ValidationResult


class LaunchState(TypedDict, total=False):
    document_text: str
    brief: CompanyBrief
    analysis: Analysis
    strategy: Strategy
    campaign: Campaign
    # Appended by every validation node, never overwritten.
    validations: Annotated[list[ValidationResult], operator.add]
    strategy_revisions: int
    campaign_revisions: int
    human_feedback: str | None


class AnalystState(MessagesState, total=False):
    brief: CompanyBrief
    document_text: str
    analysis: Analysis
