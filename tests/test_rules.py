"""One passing and one failing case per rule, on the dummy_state fixture."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from premortem.schemas import CampaignMessage
from premortem.state import LaunchState
from premortem.validation import rules

FIXTURE = Path(__file__).parent / "fixtures" / "dummy_state.json"


@pytest.fixture
def state() -> dict:
    s = TypeAdapter(LaunchState).validate_python(json.loads(FIXTURE.read_text()))
    # Make the fixture pass every rule: give the gift segment a source, cover the Online shop channel
    s["analysis"].segments[1].source_ids = ["S1"]
    s["campaign"].key_messages.append(CampaignMessage(channel="Online shop", headline="h", body="b"))
    return s


def checks(issues):
    return [(i.check, i.severity) for i in issues]


@pytest.mark.parametrize("stage", ["analysis", "strategy", "campaign"])
def test_valid_state_passes_every_rule(state, stage):
    assert rules.run_rules(stage, state) == []


def test_item_without_source(state):
    state["analysis"].competitors[0].source_ids = []
    assert checks(rules.every_item_has_a_source(state["analysis"])) == [("every_item_has_a_source", "warning")]


def test_analysis_unknown_source_id(state):
    state["analysis"].segments[0].source_ids = ["S3", "S9"]
    issues = rules.analysis_source_ids_exist(state["analysis"])
    assert checks(issues) == [("analysis_source_ids_exist", "warning")]
    assert "S9" in issues[0].message


def test_target_segment_missing(state):
    state["strategy"].target_segment_id = "SEG9"
    issues = rules.target_segment_exists(state["analysis"], state["strategy"])
    assert checks(issues) == [("target_segment_exists", "blocking")]
    assert "SEG1, SEG2" in issues[0].message


def test_unknown_supporting_source(state):
    state["strategy"].supporting_source_ids = ["S2", "S7"]
    issues = rules.supporting_source_ids_exist(state["analysis"], state["strategy"])
    assert checks(issues) == [("supporting_source_ids_exist", "blocking")]
    assert "S7" in issues[0].message and "S2" not in issues[0].message


def test_target_segment_without_size(state):
    state["strategy"].target_segment_id = "SEG2"  # gift buyers: estimated_size is null
    assert checks(rules.target_segment_has_size(state["analysis"], state["strategy"])) == [
        ("target_segment_has_size", "warning")
    ]


def test_missing_target_is_reported_once(state):
    state["strategy"].target_segment_id = "SEG9"
    assert checks(rules.run_rules("strategy", state)) == [("target_segment_exists", "blocking")]


def test_message_outside_strategy_channels(state):
    state["campaign"].key_messages.append(CampaignMessage(channel="TV", headline="h", body="b"))
    issues = rules.message_channels_in_strategy(state["strategy"], state["campaign"])
    assert checks(issues) == [("message_channels_in_strategy", "blocking")]
    assert "TV" in issues[0].message


def test_channel_without_message(state):
    state["campaign"].key_messages.pop()  # removes the Online shop message
    issues = rules.one_message_per_channel(state["strategy"], state["campaign"])
    assert checks(issues) == [("one_message_per_channel", "warning")]
    assert "Online shop" in issues[0].message
