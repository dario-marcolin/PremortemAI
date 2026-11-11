"""The Streamlit UI (Phase 15) driven by AppTest with fake LLMs: setup in both modes, a live run with
its review, saved runs with no key, the evaluation pages and the citation chips."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from premortem.runner import Run
from tests.graph_fakes import SETTINGS, STATE, FakeModel, install
from ui.citations import Citer
from ui.live import LiveRun
from ui.saved_runs import case_runs, demo_runs
from ui.view import STEPS, RunView, parse_log, searches_from_log

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
TIMEOUT = 30


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Our demo setup by default (local mode, keys in .env); tests of public mode change it."""
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_JUDGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PREMORTEM_MODE", "local")
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-ours")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-ours")


def new_app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def texts(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)


# ── A. setup ────────────────────────────────────────────────────────────────────────────

def test_local_mode_uses_our_key_and_a_sample_is_ready():
    at = new_app().run()
    assert not at.exception
    assert "Using the key from .env" in texts(at)
    assert not button(at, "Run the pipeline").disabled  # the demo document is the default sample


def test_missing_api_key_is_shown_and_blocks_the_run(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY")
    at = new_app().run()
    assert "LLM_API_KEY" in texts(at)
    assert button(at, "Run the pipeline").disabled


@pytest.mark.parametrize("mode", ["public", None])
def test_public_mode_asks_for_a_key_and_ignores_ours(monkeypatch, mode):
    if mode:
        monkeypatch.setenv("PREMORTEM_MODE", mode)
    else:
        monkeypatch.delenv("PREMORTEM_MODE")  # unset = public
    at = new_app().run()
    assert "Paste an Anthropic or Gemini API key" in texts(at)  # LLM_API_KEY in the environment is not used
    assert button(at, "Run the pipeline").disabled


def test_public_mode_detects_the_provider_from_the_key(monkeypatch):
    monkeypatch.setenv("PREMORTEM_MODE", "public")
    at = new_app().run()
    at.text_input(key="llm_key").input("AIza-visitor").run()
    assert at.selectbox[0].value == "gemini"
    assert "google_genai:" in texts(at)  # the model of each agent
    assert not button(at, "Run the pipeline").disabled


def test_public_app_offers_only_the_tested_providers(monkeypatch):
    monkeypatch.setenv("PREMORTEM_MODE", "public")
    at = new_app().run()
    assert at.selectbox[0].options == ["Anthropic (Claude)", "Google Gemini (free tier)"]
    at.text_input(key="llm_key").input("sk-proj-openai").run()  # an OpenAI key: explained, not sent
    assert "looks like it is for OpenAI" in texts(at)
    assert button(at, "Run the pipeline").disabled


def test_the_pasted_key_survives_a_visit_to_another_page(monkeypatch):
    monkeypatch.setenv("PREMORTEM_MODE", "public")
    at = new_app().run()
    at.text_input(key="llm_key").input("AIza-visitor").run()
    at.session_state.goto = "saved"
    at.run()
    assert "llm_key" not in at.session_state  # Streamlit dropped the widget of the hidden page
    at.session_state.goto = "new"
    at.run()
    assert at.text_input(key="llm_key").value == "AIza-visitor"
    assert not button(at, "Run the pipeline").disabled


def test_missing_tavily_key_is_a_warning_and_the_run_stays_possible(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY")
    at = new_app().run()
    assert "Web search unavailable" in texts(at)
    assert not button(at, "Run the pipeline").disabled


# ── B. a live run (the pipeline advances in the test thread) ─────────────────────────────

@pytest.fixture
def live_app(monkeypatch, tmp_path):
    install(monkeypatch, FakeModel())
    document = tmp_path / "company.md"
    document.write_text(STATE["document_text"])
    live = LiveRun(Run(document, run_id="ui", settings=SETTINGS), sync=True)
    live.start()
    at = new_app()
    at.session_state.live = live
    at.session_state.current = {"kind": "live"}
    at.session_state.goto = "run"
    return at.run(), live


def test_run_pauses_for_review_on_the_strategy_page(live_app):
    at, live = live_app
    assert live.status == "waiting"
    assert not at.exception
    assert at.session_state.step == "strategy"
    assert button(at, "Approve and continue")
    assert "Waiting for your review" in texts(at)


def test_approve_finishes_the_run_and_opens_the_blueprint(live_app):
    at, live = live_app
    button(at, "Approve and continue").click().run()
    assert live.status == "done"
    assert (live.run.dir / "searches.json").exists() and (live.run.dir / "rounds.json").exists()
    at.run()
    assert at.session_state.step == "blueprint"
    assert [b.label for b in at.get("download_button")][:2] == ["Download PDF", "Markdown"]
    assert not at.exception


def test_send_back_records_the_feedback_and_asks_again(live_app):
    at, live = live_app
    button(at, "Target a bigger segment").click().run()  # a chip fills the text area, it does not send
    assert at.text_area(key="feedback_strategy").value == "Target a bigger segment."
    assert live.status == "waiting" and not live.run.decisions
    button(at, "Send back").click().run()
    assert live.status == "waiting"
    assert live.run.decisions[0]["approved"] is False
    assert live.run.decisions[0]["feedback"] == "Target a bigger segment."
    assert at.text_area(key="feedback_strategy").value == ""


@pytest.mark.parametrize("step", STEPS)
def test_every_step_of_a_finished_live_run_renders(live_app, step):
    at, live = live_app
    button(at, "Approve and continue").click().run()
    at.session_state.step = step
    at.run()
    assert not at.exception


# ── E. saved runs, with no key ───────────────────────────────────────────────────────────

SAVED = [p for p, _ in demo_runs() + case_runs()]


@pytest.mark.parametrize("path", SAVED, ids=lambda p: str(p.relative_to(ROOT)))
def test_saved_runs_load_and_every_step_is_done(path):
    view = RunView.from_dir(path)
    assert view.status == "done" and view.brief and view.blueprint_md
    assert all(view.step(s).status in ("done", "approved", "limit") for s in STEPS)


@pytest.mark.parametrize("step", [*STEPS, "evaluation"])
def test_a_saved_run_opens_from_a_link_with_no_key(monkeypatch, step):
    monkeypatch.setenv("PREMORTEM_MODE", "public")
    monkeypatch.delenv("LLM_API_KEY")
    at = new_app()
    at.query_params["saved"] = "examples/demo_anthropic"
    at.query_params["step"] = step
    at.run()
    assert not at.exception
    assert at.session_state.step == step


def test_saved_runs_and_evaluation_pages_render():
    for page in ("saved", "evaluation", "how"):
        at = new_app()
        at.session_state.goto = page
        at.run()
        assert not at.exception, page


# ── citations ────────────────────────────────────────────────────────────────────────────

def test_citation_chips_and_the_broken_ones():
    view = RunView.from_dir(ROOT / "examples" / "demo_anthropic")
    citer = Citer(view)
    html = citer.text("Market grew [S3]. Size: 1.3M adults, S4. Unknown [S99].")
    assert html.count('class="pm-cite"') == 2 and html.count('class="pm-cite bad"') == 1
    assert "Company document" in html  # S3 is a document source: its card says so
    assert "Galaxy S24" in citer.text("Galaxy S24 phones")  # a bare unlisted token stays text
    web = next(s for s in view.analysis.sources if s.kind == "web")
    assert f'href="{web.reference}"' in citer.source_chip(web.id)  # a click opens the page


def test_old_logs_give_the_searches():
    log = parse_log((ROOT / "examples" / "demo_anthropic" / "log.txt").read_text())
    searches = searches_from_log(log)
    assert len(searches) == sum(l.kind == "search" for l in log) == 10
    assert all(s["count"] == 5 for s in searches)


def test_local_mode_offers_every_provider_with_a_key_in_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-ours")
    at = new_app().run()
    assert at.selectbox(key="local_provider").options == ["Anthropic (Claude) · key from .env",
                                                          "Google Gemini (free tier) · key from .env"]
    at.selectbox(key="local_provider").select("gemini").run()
    assert "google_genai:" in texts(at)
    assert not button(at, "Run the pipeline").disabled


def test_the_blueprint_pdf_has_every_section():
    from premortem.output.pdf import blueprint_pdf

    pdf = blueprint_pdf((ROOT / "examples" / "demo_anthropic" / "blueprint.md").read_text())
    assert pdf.startswith(b"%PDF") and len(pdf) > 20_000


def test_each_round_names_the_feedback_that_asked_for_it():
    from ui.steps.common import reason_for_round

    view = RunView.from_dir(ROOT / "examples" / "fakturo_anthropic")  # sent back twice, then approved
    assert "Target a bigger segment" in reason_for_round(view, "strategy", 2)
    assert "Cheaper positioning" in reason_for_round(view, "strategy", 3)
