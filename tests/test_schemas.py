import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from premortem.schemas import Source, ValidationResult
from premortem.state import AnalystState, LaunchState

FIXTURE = Path(__file__).parent / "fixtures" / "dummy_state.json"


@pytest.fixture
def state() -> dict:
    return TypeAdapter(LaunchState).validate_python(json.loads(FIXTURE.read_text()))


def test_dummy_state_builds_every_model(state):
    assert state["brief"].company_name == "Acme Coffee"
    assert state["analysis"].competitors[0].price_level == "high"
    assert state["strategy"].target_segment_id == "SEG1"
    assert state["campaign"].key_messages[0].channel in state["strategy"].channels
    assert all(isinstance(v, ValidationResult) for v in state["validations"])


def test_dummy_state_references_are_consistent(state):
    analysis, strategy = state["analysis"], state["strategy"]
    source_ids = {s.id for s in analysis.sources}
    cited = set(strategy.supporting_source_ids)
    cited |= {sid for c in analysis.competitors for sid in c.source_ids}
    cited |= {sid for s in analysis.segments for sid in s.source_ids}
    assert cited <= source_ids
    assert strategy.target_segment_id in {s.segment_id for s in analysis.segments}


def test_blocking_issues(state):
    failed = state["validations"][0]
    assert not failed.passed
    assert len(failed.blocking_issues) == 1


def test_analyst_state_builds(state):
    analyst = TypeAdapter(AnalystState).validate_python(
        {"messages": [], "brief": state["brief"], "document_text": state["document_text"]}
    )
    assert analyst["brief"].product_name == "BrewBox"


@pytest.mark.parametrize("bad_id", ["s1", "S0", "SEG1", "Source1", ""])
def test_source_id_format(bad_id):
    with pytest.raises(ValidationError):
        Source(id=bad_id, kind="web", reference="https://example.com")
