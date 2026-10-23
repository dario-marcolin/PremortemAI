"""Shared data contract between the graph nodes.

Frozen after Phase 1: any change goes through a small PR approved by A, B and C.
The Field descriptions are read by the LLM when producing structured output.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

SourceId = Annotated[str, Field(pattern=r"^S[1-9]\d*$", description="Source id: S1, S2, ...")]
SegmentId = Annotated[str, Field(pattern=r"^SEG[1-9]\d*$", description="Segment id: SEG1, SEG2, ...")]

PriceLevel = Literal["low", "mid", "high", "premium", "unknown"]
Severity = Literal["blocking", "warning"]
Stage = Literal["brief", "analysis", "strategy", "campaign"]


class CompanyBrief(BaseModel):
    company: str = Field(description="Name of the company launching the product.")
    product: str = Field(description="Short description of the product being launched.")
    target_country: str = Field(description="Country where the product will be launched.")
    price_hint: str | None = Field(
        default=None,
        description="Intended price or price range, as stated in the document. Null if not stated.",
    )
    known_competitors: list[str] = Field(
        default_factory=list,
        description="Competitors explicitly named in the document. Do not add any that are not named.",
    )
    stated_goals: list[str] = Field(
        default_factory=list,
        description="Launch goals explicitly stated in the document (e.g. sales targets, market share).",
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description="Information needed for the launch plan that the document does not provide.",
    )


class Source(BaseModel):
    id: SourceId
    kind: Literal["document", "web"] = Field(
        description="'document' if from the uploaded document, 'web' if from a web search."
    )
    reference: str = Field(
        description="For 'document': the file name and section. For 'web': the full URL."
    )


class Competitor(BaseModel):
    name: str = Field(description="Competitor company or product name.")
    positioning: str = Field(description="How the competitor presents itself and to whom.")
    price_level: PriceLevel = Field(
        description="Competitor price level relative to the market. Use 'unknown' if no source supports it."
    )
    source_ids: list[SourceId] = Field(
        default_factory=list, description="Ids of the sources supporting this competitor's data."
    )


class MarketSegment(BaseModel):
    segment_id: SegmentId
    label: str = Field(description="Short name of the segment (a few words).")
    description: str = Field(description="Who belongs to this segment.")
    needs: list[str] = Field(description="Main needs of this segment relevant to the product.")
    estimated_size: str = Field(
        description="Estimated size in free text, citing the source id (e.g. '~2M households, S3'). "
        "Write 'unknown' rather than inventing a number."
    )
    source_ids: list[SourceId] = Field(
        default_factory=list, description="Ids of the sources supporting this segment."
    )


class Analysis(BaseModel):
    market_overview: str = Field(description="Summary of the market in the target country.")
    competitors: list[Competitor] = Field(description="Main competitors in the target market.")
    customer_needs: list[str] = Field(description="Customer needs observed across the market.")
    segments: list[MarketSegment] = Field(description="Candidate customer segments for the launch.")
    data_quality_notes: list[str] = Field(
        default_factory=list,
        description="Gaps, conflicting data or weak sources that limit confidence in the analysis.",
    )
    sources: list[Source] = Field(
        description="Every source cited anywhere in the analysis, each with a unique id."
    )


class Strategy(BaseModel):
    target_segment_id: SegmentId = Field(
        description="Id of the chosen segment; must exist in the analysis segments."
    )
    target_description: str = Field(description="Who the launch targets, in plain words.")
    positioning: str = Field(description="How the product should be perceived against competitors.")
    value_proposition: str = Field(description="The main benefit the target customer gets.")
    pricing_direction: str = Field(
        description="Recommended price direction relative to competitors, with the reason."
    )
    channels: list[str] = Field(description="Sales and marketing channels to use.")
    rationale: str = Field(description="Why this strategy fits the analysis.")
    supporting_source_ids: list[SourceId] = Field(
        description="Ids of the analysis sources that support this strategy."
    )


class CampaignMessage(BaseModel):
    message: str = Field(description="One key message of the campaign.")
    audience_need: str = Field(description="The target segment need this message answers.")


class Campaign(BaseModel):
    concept: str = Field(description="Core creative idea of the campaign.")
    tagline: str = Field(description="Short memorable line, in the language of the target country.")
    key_messages: list[CampaignMessage] = Field(description="Key messages consistent with the strategy.")
    content_ideas: list[str] = Field(description="Concrete content pieces for the chosen channels.")
    visual_direction: str = Field(description="Look and feel: style, colors, imagery.")


class ValidationIssue(BaseModel):
    severity: Severity = Field(
        description="'blocking': must be fixed, the stage is revised. 'warning': reported only."
    )
    field: str | None = Field(
        default=None, description="Name of the field the issue refers to, if any."
    )
    message: str = Field(description="What is wrong and how to fix it.")


class ValidationResult(BaseModel):
    stage: Stage = Field(description="Pipeline stage that was validated.")
    passed: bool = Field(description="False if there is at least one blocking issue.")
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def blocking_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "blocking"]
