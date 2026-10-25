"""Deterministic validation rules: pure Python, no LLM.

Each rule returns a list of ValidationIssue (empty when the rule passes). The check names
are stable: the blueprint and the evaluation refer to them.
"""

from premortem.schemas import Analysis, Campaign, Stage, Strategy, ValidationIssue
from premortem.state import LaunchState


def _issue(severity: str, check: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=severity, check=check, message=message)


# Analysis (warnings only: the graph never loops back to the Analyst)


def every_item_has_a_source(analysis: Analysis) -> list[ValidationIssue]:
    items = [(f"Competitor '{c.name}'", c.source_ids) for c in analysis.competitors]
    items += [(f"Segment {s.segment_id} '{s.label}'", s.source_ids) for s in analysis.segments]
    return [
        _issue("warning", "every_item_has_a_source", f"{name} cites no source.")
        for name, source_ids in items
        if not source_ids
    ]


def analysis_source_ids_exist(analysis: Analysis) -> list[ValidationIssue]:
    known = {s.id for s in analysis.sources}
    items = [(f"Competitor '{c.name}'", c.source_ids) for c in analysis.competitors]
    items += [(f"Segment {s.segment_id}", s.source_ids) for s in analysis.segments]
    return [
        _issue("warning", "analysis_source_ids_exist", f"{name} cites {i}, which is not in the sources.")
        for name, source_ids in items
        for i in source_ids
        if i not in known
    ]


# Strategy


def target_segment_exists(analysis: Analysis, strategy: Strategy) -> list[ValidationIssue]:
    ids = [s.segment_id for s in analysis.segments]
    if strategy.target_segment_id in ids:
        return []
    return [
        _issue(
            "blocking",
            "target_segment_exists",
            f"Target segment {strategy.target_segment_id} is not in the analysis. Choose one of: {', '.join(ids)}.",
        )
    ]


def supporting_source_ids_exist(analysis: Analysis, strategy: Strategy) -> list[ValidationIssue]:
    known = {s.id for s in analysis.sources}
    missing = [i for i in strategy.supporting_source_ids if i not in known]
    if not missing:
        return []
    return [
        _issue(
            "blocking",
            "supporting_source_ids_exist",
            f"Supporting source(s) {', '.join(missing)} are not in the analysis sources. Cite only existing ids.",
        )
    ]


def target_segment_has_size(analysis: Analysis, strategy: Strategy) -> list[ValidationIssue]:
    segment = next((s for s in analysis.segments if s.segment_id == strategy.target_segment_id), None)
    if segment is None or segment.estimated_size:
        return []  # a missing segment is reported by target_segment_exists
    return [
        _issue(
            "warning",
            "target_segment_has_size",
            f"Target segment {segment.segment_id} '{segment.label}' has no estimated size: "
            "the choice cannot be checked against market figures.",
        )
    ]


# Campaign


def message_channels_in_strategy(strategy: Strategy, campaign: Campaign) -> list[ValidationIssue]:
    extra = list(dict.fromkeys(m.channel for m in campaign.key_messages if m.channel not in strategy.channels))
    if not extra:
        return []
    return [
        _issue(
            "blocking",
            "message_channels_in_strategy",
            f"Message channel(s) {', '.join(extra)} are not strategy channels. "
            f"Use only: {', '.join(strategy.channels)}.",
        )
    ]


def one_message_per_channel(strategy: Strategy, campaign: Campaign) -> list[ValidationIssue]:
    covered = {m.channel for m in campaign.key_messages}
    return [
        _issue("warning", "one_message_per_channel", f"No key message for the strategy channel '{c}'.")
        for c in strategy.channels
        if c not in covered
    ]


def run_rules(stage: Stage, state: LaunchState) -> list[ValidationIssue]:
    analysis, strategy = state.get("analysis"), state.get("strategy")
    if stage == "analysis":
        return every_item_has_a_source(analysis) + analysis_source_ids_exist(analysis)
    if stage == "strategy":
        return (
            target_segment_exists(analysis, strategy)
            + supporting_source_ids_exist(analysis, strategy)
            + target_segment_has_size(analysis, strategy)
        )
    campaign = state.get("campaign")
    return message_channels_in_strategy(strategy, campaign) + one_message_per_channel(strategy, campaign)
