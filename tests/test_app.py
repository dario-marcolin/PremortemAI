"""The Streamlit UI driven by AppTest with fake LLMs: run, approval pause, rejection, result."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from premortem import config
from premortem.runner import Run
from tests.graph_fakes import STATE, FakeModel, install

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TIMEOUT = 30


@pytest.fixture
def app(monkeypatch, tmp_path):
    install(monkeypatch, FakeModel())
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    document = tmp_path / "company.md"
    document.write_text(STATE["document_text"])
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    # The upload widget cannot be driven by AppTest: start the run the way the Run button does
    at.session_state.run = Run(document, run_id="ui")
    return at


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_empty_screen_asks_for_a_document(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    assert at.title[0].value == "New launch run"
    assert button(at, "Run the pipeline").disabled  # no document yet
    assert not at.error


def test_missing_api_key_is_shown_and_blocks_the_run(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", None)
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    assert "LLM_API_KEY" in at.error[0].value
    assert button(at, "Run the pipeline").disabled


def test_run_pauses_for_approval_then_shows_the_blueprint(app):
    app.run()
    run = app.session_state.run
    assert run.status == "waiting"
    assert app.title[0].value == f"{STATE['brief'].product_name} launch"
    assert any(s.value == "Approve the strategy" for s in app.subheader)

    button(app, "Approve strategy").click().run()
    assert run.status == "done"
    assert [t.label for t in app.tabs] == ["Blueprint", "Segments", "Validation log"]
    assert "blueprint.md written" in [l.text for l in run.log]
    assert not app.exception


def test_reject_sends_the_feedback_and_asks_again(app):
    app.run()
    app.text_area(key="feedback").input("Target students instead")
    button(app, "Reject with feedback").click().run()
    run = app.session_state.run
    assert run.status == "waiting"
    assert run.decisions[0] == {"approved": False, "feedback": "Target students instead",
                                "target_segment_id": STATE["strategy"].target_segment_id, "unresolved": False}
    assert app.text_area(key="feedback").value == ""
