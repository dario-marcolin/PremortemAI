"""get_llm per role, provider detection, rate limits, check_model, and keys that never leak or mix."""

import json

import pytest
from langchain_core.messages import AIMessage

from premortem import llm as llm_module
from premortem.config import ROLES, RunSettings
from premortem.llm import Check, check_model, current_settings, explain_error, get_llm, using_settings
from premortem.providers import PRESETS, detect_provider
from premortem.runner import Run
from tests.graph_fakes import SETTINGS, STATE, FakeModel, install


@pytest.fixture
def built(monkeypatch):
    """Replace init_chat_model: record what each model would be built with."""
    calls = []

    def fake_init(model, **kwargs):
        calls.append({"model": model, **kwargs})
        return object()

    monkeypatch.setattr(llm_module, "init_chat_model", fake_init)
    return calls


# --- One model per role ---

def test_each_role_gets_its_own_model(built):
    settings = RunSettings(provider="anthropic", models={r: f"anthropic:model-{r}" for r in ROLES}, llm_api_key="k")
    for role in ROLES:
        get_llm(role, settings)
    assert [c["model"] for c in built] == [f"anthropic:model-{r}" for r in ROLES]
    get_llm("eval_judge", settings)
    assert built[-1]["model"] == settings.eval_judge


def test_anthropic_preset_profile(built):
    for role in ("brief", "analyst", "strategist", "creative", "validator", "blueprint", "eval_judge"):
        get_llm(role, SETTINGS)
    assert [c["model"].removeprefix("anthropic:claude-") for c in built] == [
        "sonnet-5-5", "sonnet-5-5", "sonnet-5-5", "sonnet-5-5", "sonnet-5-5", "opus-5-5", "haiku-5-5"]


def test_retries_and_no_temperature_by_default(built):
    get_llm("analyst", SETTINGS)
    assert built[0]["max_retries"] == llm_module.MAX_RETRIES and "temperature" not in built[0]
    assert built[0]["api_key"] == "sk-ant-test"


def test_judge_temperature_only_for_judges(built):
    settings = RunSettings.preset("anthropic", "k")
    settings = RunSettings(**{**settings.__dict__, "temperature": 0.7, "judge_temperature": 0.0})
    get_llm("strategist", settings)
    get_llm("validator", settings)
    get_llm("eval_judge", settings)
    assert [c["temperature"] for c in built] == [0.7, 0.0, 0.0]


def test_custom_route_passes_the_base_url(built):
    get_llm("analyst", RunSettings.custom("https://llm.example.edu/v1", "k", "small"))
    assert built[0]["base_url"] == "https://llm.example.edu/v1" and built[0]["model"] == "openai:small"


def test_no_key_raises_a_clear_error():
    with pytest.raises(RuntimeError, match="No LLM key"):
        get_llm("analyst", RunSettings.preset("anthropic", ""))


# --- Settings come from the run ---

def test_outside_a_run_there_are_no_settings():
    with pytest.raises(RuntimeError, match="No run settings"):
        current_settings()


def test_inside_a_run_the_settings_are_found(built):
    with using_settings(SETTINGS):
        get_llm("creative")
    assert built[0]["api_key"] == "sk-ant-test"


# --- Rate limits ---

def test_gemini_has_a_rate_limiter_anthropic_does_not(built):
    get_llm("analyst", RunSettings.preset("gemini", "AIza-1"))
    get_llm("analyst", SETTINGS)
    assert built[0]["rate_limiter"] is not None and "rate_limiter" not in built[1]


def test_rate_limiter_is_shared_per_key_and_model(built):
    a1, a2, b = (RunSettings.preset("gemini", k) for k in ("AIza-A", "AIza-A", "AIza-B"))
    for s in (a1, a2, b):
        get_llm("analyst", s)
    assert built[0]["rate_limiter"] is built[1]["rate_limiter"]  # same key: same free-tier quota
    assert built[0]["rate_limiter"] is not built[2]["rate_limiter"]
    assert not any("AIza" in str(k) for k in llm_module._limiters)  # keys are hashed


# --- Provider detection ---

@pytest.mark.parametrize("key,provider", [
    ("sk-ant-api03-x", "anthropic"), ("AIzaSyX", "gemini"), ("AQ.Ab8x", "gemini"), ("gsk_x", "groq"), ("sk-or-v1-x", "openrouter"),
    ("sk-proj-x", "openai"), ("sk-x", "openai"), ("  sk-ant-x\n", "anthropic"), ("mistral-like-key", None), ("", None),
    (None, None)])
def test_detect_provider(key, provider):
    assert detect_provider(key) == provider


def test_every_preset_covers_every_role():
    for name, preset in PRESETS.items():
        assert set(preset.models) == set(ROLES), name
        prefixes = {m.split(":", 1)[0] for m in [*preset.models.values(), preset.eval_judge]}
        assert len(prefixes) == 1, name  # one key per run


# --- check_model ---

class FakeChat:
    def __init__(self, tools=True, structured=True, fail=None):
        self.tools, self.structured, self.fail = tools, structured, fail

    def invoke(self, _prompt):
        if self.fail:
            raise self.fail
        return AIMessage("OK")

    def bind_tools(self, _tools):
        calls = [{"name": "ping", "args": {"word": "hello"}, "id": "1"}] if self.tools else []
        return type("B", (), {"invoke": lambda _s, _p: AIMessage("", tool_calls=calls)})()

    def with_structured_output(self, schema):
        value = schema(word="hello") if self.structured else None
        return type("S", (), {"invoke": lambda _s, _p: value})()


def check(monkeypatch, chat) -> list[Check]:
    monkeypatch.setattr(llm_module, "init_chat_model", lambda *_a, **_k: chat)
    return check_model(SETTINGS)


def test_check_model_passes(monkeypatch):
    assert [(c.name, c.ok) for c in check(monkeypatch, FakeChat())] == [
        ("plain call", True), ("tool call", True), ("structured output", True)]


def test_check_model_explains_a_model_without_tools(monkeypatch):
    checks = check(monkeypatch, FakeChat(tools=False))
    assert not checks[1].ok and "cannot search the web" in checks[1].message and checks[2].ok


def test_check_model_stops_at_a_rejected_key(monkeypatch):
    checks = check(monkeypatch, FakeChat(fail=RuntimeError("Error code: 401 - invalid x-api-key")))
    assert len(checks) == 1 and not checks[0].ok and "rejected by Anthropic" in checks[0].message


@pytest.mark.parametrize("error,words", [("429 Too Many Requests", "limit"), ("404 model not found", "model name"),
                                         ("RESOURCE_EXHAUSTED quota", "limit"),
                                         ("504 DEADLINE_EXCEEDED", "did not answer in time")])
def test_explain_error(error, words):
    assert words in explain_error(RuntimeError(error), "gemini")


# --- Keys never leak, and two runs never mix them ---

def test_keys_never_reach_the_run_files_or_checkpoints(monkeypatch, tmp_path):
    install(monkeypatch, FakeModel())
    document = tmp_path / "company.md"
    document.write_text(STATE["document_text"])
    settings = RunSettings.preset("anthropic", "sk-ant-SECRET-1", tavily_api_key="tvly-SECRET-2")
    run = Run(document, run_id="keys", settings=settings)
    while True:
        list(run.advance())
        if run.status != "waiting":
            break
        run.answer({"approved": True})
    assert run.status == "done"
    record = json.loads((run.dir / "run.json").read_text())
    assert record["provider"] == "anthropic" and record["models"]["blueprint"] == "anthropic:claude-opus-5-5"
    for path in run.dir.rglob("*"):
        if path.is_file():
            assert "SECRET" not in path.read_text(errors="ignore"), path.name
    for snapshot in run.app.get_state_history(run.cfg):
        assert "SECRET" not in repr(snapshot.metadata) and "SECRET" not in repr(snapshot.values)


def test_two_runs_with_different_keys_do_not_share_a_client(monkeypatch, tmp_path):
    """Every LLM call and search sees only the key of its own run, even with the runs interleaved."""
    install(monkeypatch, FakeModel())
    seen: dict[str, set] = {"llm": set(), "tavily": set()}
    models: dict[str, FakeModel] = {}  # one fake per key: each one searches once, in its own Analyst loop

    def get_llm_recording(*_a, **_k):
        key = current_settings().llm_api_key
        seen["llm"].add(key)
        return models.setdefault(key, FakeModel())

    from premortem.agents import analyst, creative, strategist
    from premortem.ingestion import brief_extractor
    from premortem.output import blueprint
    from premortem.tools import web_search as ws
    from premortem.validation import judge
    for module in (brief_extractor, analyst, strategist, creative, judge, blueprint):
        monkeypatch.setattr(module, "get_llm", get_llm_recording)
    real_client = ws._client
    monkeypatch.setattr(ws, "_client", lambda key: seen["tavily"].add(key) or real_client(key))

    document = tmp_path / "company.md"
    document.write_text(STATE["document_text"])
    runs = {k: Run(document, run_id=f"run_{k}", settings=RunSettings.preset("anthropic", f"sk-ant-{k}",
                                                                              tavily_api_key=f"tvly-{k}"))
            for k in ("A", "B")}
    for key, run in runs.items():  # A up to the approval, then B up to the approval
        seen["llm"].clear(), seen["tavily"].clear()
        list(run.advance())
        assert run.status == "waiting"
        assert seen == {"llm": {f"sk-ant-{key}"}, "tavily": {f"tvly-{key}"}}
    for key in ("B", "A"):  # then finish them in the other order
        seen["llm"].clear()
        runs[key].answer({"approved": True})
        list(runs[key].advance())
        assert runs[key].status == "done" and seen["llm"] == {f"sk-ant-{key}"}
