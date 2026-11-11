"""The Streamlit UI driven by AppTest with fake LLMs: run, approval pause, rejection, result, evaluation."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from premortem.runner import Run
from tests.graph_fakes import SETTINGS, STATE, FakeModel, install

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TIMEOUT = 30


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Our demo setup by default (local mode, keys in .env); tests of public mode change it."""
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_JUDGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PREMORTEM_MODE", "local")
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-ours")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-ours")


@pytest.fixture
def app(monkeypatch, tmp_path):
    install(monkeypatch, FakeModel())
    document = tmp_path / "company.md"
    document.write_text(STATE["document_text"])
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    # The upload widget cannot be driven by AppTest: start the run the way the Run button does
    at.session_state.run = Run(document, run_id="ui", settings=SETTINGS)
    return at


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_empty_screen_asks_for_a_document():
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    assert at.title[0].value == "New launch run"
    assert button(at, "Run the pipeline").disabled  # no document yet
    assert not at.error
    assert any("Using the key from .env" in c.value for c in at.sidebar.caption)


def test_missing_api_key_is_shown_and_blocks_the_run(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY")
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    assert "LLM_API_KEY" in at.error[0].value
    assert button(at, "Run the pipeline").disabled


@pytest.mark.parametrize("mode", ["public", None])
def test_public_mode_asks_for_a_key_and_ignores_ours(monkeypatch, mode):
    if mode:
        monkeypatch.setenv("PREMORTEM_MODE", mode)
    else:
        monkeypatch.delenv("PREMORTEM_MODE")  # unset = public
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    assert "Paste an LLM API key" in at.error[0].value  # LLM_API_KEY in the environment is not used
    assert button(at, "Run the pipeline").disabled


def test_public_mode_detects_the_provider_from_the_key(monkeypatch):
    monkeypatch.setenv("PREMORTEM_MODE", "public")
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    at.text_input(key="llm_key").input("AIza-visitor").run()
    assert at.sidebar.selectbox[1].value == "gemini"
    assert not at.error
    assert any("google_genai:" in c.value for c in at.sidebar.caption)


def test_run_pauses_for_approval_then_shows_the_blueprint(app):
    app.run()
    run = app.session_state.run
    assert run.status == "waiting"
    assert app.title[0].value == f"{STATE['brief'].product_name} launch"
    assert any(s.value == "Approve the strategy" for s in app.subheader)

    button(app, "Approve strategy").click().run()
    assert run.status == "done"
    assert [t.label for t in app.tabs] == ["Blueprint", "Segments", "Validation log", "Evaluation"]
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


def metric(at: AppTest, label: str):
    return next(m for m in at.metric if m.label == label)


def test_result_is_evaluated_at_the_end(app):
    app.run()
    button(app, "Approve strategy").click().run()
    run = app.session_state.run
    assert (run.dir / "metrics.json").exists()
    assert metric(app, "Strategy vs analysis").value == "4 / 5"
    assert metric(app, "Traceability").value == "0%"  # the fake claim (the summary) cites nothing
    assert metric(app, "Traceability").delta == ""  # no baseline yet
    assert not app.exception


def test_baseline_comparison_adds_the_differences(app):
    app.run()
    button(app, "Approve strategy").click().run()
    button(app, "Compare with the single-prompt baseline").click().run()
    run = app.session_state.run
    assert {p.name for p in (run.dir / "baseline").iterdir()} == {"blueprint.md", "run.json", "log.txt", "metrics.json"}
    # Baseline: its one claim cites the document [1] -> 100%; the blueprint's claim cites nothing -> 0%
    assert metric(app, "Traceability").delta == "-100 pts vs single prompt"
    assert metric(app, "Campaign vs strategy").delta == "+0 vs single prompt"
    assert not app.exception


def test_evaluation_can_be_turned_off_and_asked_later(app):
    app.toggle(key="auto_eval").set_value(False).run()
    button(app, "Approve strategy").click().run()
    run = app.session_state.run
    assert not (run.dir / "metrics.json").exists()
    button(app, "Evaluate this run").click().run()
    assert (run.dir / "metrics.json").exists()


def test_evaluation_error_keeps_the_result(app, monkeypatch):
    from eval import metrics

    def broken(*_args, **_kwargs):
        raise RuntimeError("judge unavailable")

    monkeypatch.setattr(metrics, "extract_claims", broken)
    app.run()
    button(app, "Approve strategy").click().run()
    assert any("judge unavailable" in e.value for e in app.error)
    assert "Blueprint" in [t.label for t in app.tabs]
    assert not app.exception
