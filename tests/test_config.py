import pytest

from premortem.config import ROLES, RunSettings, current_mode

ENV_VARS = ["PREMORTEM_MODE", "LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_JUDGE_MODEL", "TAVILY_API_KEY",
            "LLM_TEMPERATURE", "LLM_JUDGE_TEMPERATURE", *[f"LLM_MODEL_{r.upper()}" for r in ROLES]]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """load_dotenv() runs at import: drop the developer's .env values so each test sets its own."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# --- Mode ---

def test_unset_mode_is_public():
    assert current_mode() == "public"


@pytest.mark.parametrize("value,expected", [("local", "local"), (" LOCAL ", "local"), ("public", "public")])
def test_mode_values(monkeypatch, value, expected):
    monkeypatch.setenv("PREMORTEM_MODE", value)
    assert current_mode() == expected


def test_invalid_mode_raises(monkeypatch):
    monkeypatch.setenv("PREMORTEM_MODE", "demo")
    with pytest.raises(ValueError, match="PREMORTEM_MODE"):
        current_mode()


# --- from_env ---

def test_from_env_defaults_to_anthropic_preset(monkeypatch):
    monkeypatch.setenv("PREMORTEM_MODE", "local")
    s = RunSettings.from_env()
    assert s.provider == "anthropic"
    assert s.model("analyst") == "anthropic:claude-sonnet-5-5"
    assert s.model("validator") == "anthropic:claude-sonnet-5-5"
    assert s.model("blueprint") == "anthropic:claude-opus-5-5"
    assert s.eval_judge == "anthropic:claude-haiku-5-5"


def test_local_mode_reads_llm_key(monkeypatch):
    monkeypatch.setenv("PREMORTEM_MODE", "local")
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-local")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    s = RunSettings.from_env()
    assert s.llm_api_key == "sk-ant-local" and s.tavily_api_key == "tvly-x"


@pytest.mark.parametrize("mode", [None, "public"])
def test_public_mode_ignores_llm_key(monkeypatch, mode):
    if mode:
        monkeypatch.setenv("PREMORTEM_MODE", mode)
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-ours")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-ours")
    s = RunSettings.from_env()
    assert s.llm_api_key is None
    assert s.tavily_api_key == "tvly-ours"  # Tavily is ours in both modes


def test_explicit_mode_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-local")
    assert RunSettings.from_env(mode="local").llm_api_key == "sk-ant-local"


def test_llm_model_replaces_every_role_and_role_override_wins(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "anthropic:claude-haiku-5-5")
    monkeypatch.setenv("LLM_MODEL_BLUEPRINT", "anthropic:claude-opus-5-5")
    s = RunSettings.from_env()
    assert {s.model(r) for r in ROLES if r != "blueprint"} == {"anthropic:claude-haiku-5-5"}
    assert s.model("blueprint") == "anthropic:claude-opus-5-5"


def test_preset_found_from_llm_model_prefix(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "google_genai:gemini-x")
    s = RunSettings.from_env()
    assert s.provider == "gemini" and s.model("blueprint") == "google_genai:gemini-x"
    assert s.eval_judge == "google_genai:gemini-3.5-flash-lite"


def test_llm_provider_picks_a_preset(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    s = RunSettings.from_env()
    assert s.model("analyst").startswith("google_genai:") and s.model("blueprint").startswith("google_genai:")


def test_provider_without_preset(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "ollama:llama-x")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
    s = RunSettings.from_env()
    assert s.provider == "ollama" and s.base_url == "http://localhost:11434"
    assert s.eval_judge == "ollama:llama-x"  # no preset: falls back to the validator model


def test_unknown_llm_provider_without_model_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="No preset named"):
        RunSettings.from_env()


def test_openrouter_preset_has_its_base_url():
    assert RunSettings.preset("openrouter", "sk-or-x").base_url == "https://openrouter.ai/api/v1"


def test_mixed_providers_rejected(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_CREATIVE", "openai:gpt-x")
    with pytest.raises(ValueError, match="LLM_MODEL_CREATIVE=openai:gpt-x"):
        RunSettings.from_env()


def test_temperatures_and_judge_model_from_env(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.3")
    monkeypatch.setenv("LLM_JUDGE_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_JUDGE_MODEL", "anthropic:claude-sonnet-5-5")
    s = RunSettings.from_env()
    assert (s.temperature, s.judge_temperature) == (0.3, 0.0)
    assert s.eval_judge == "anthropic:claude-sonnet-5-5"


def test_env_is_read_at_call_time(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_ANALYST", "anthropic:claude-haiku-5-5")
    assert RunSettings.from_env().model("analyst") == "anthropic:claude-haiku-5-5"
    monkeypatch.delenv("LLM_MODEL_ANALYST")
    assert RunSettings.from_env().model("analyst") == "anthropic:claude-sonnet-5-5"


# --- preset and custom ---

def test_preset_gives_every_role_a_model():
    s = RunSettings.preset("anthropic", "  sk-ant-visitor\n", tavily_api_key="tvly-x")
    assert set(s.models) == set(ROLES)
    assert s.llm_api_key == "sk-ant-visitor"  # pasted whitespace stripped


def test_unknown_preset_raises():
    with pytest.raises(ValueError, match="Unknown preset"):
        RunSettings.preset("nope", "key")


def test_custom_route():
    s = RunSettings.custom(" https://llm.example.edu/v1 ", "key", "small-model", big_model="big-model")
    assert s.provider == "custom" and s.base_url == "https://llm.example.edu/v1"
    assert s.model("analyst") == "openai:small-model"
    assert s.model("blueprint") == "openai:big-model"
    assert RunSettings.custom("https://x/v1", "key", "m").model("blueprint") == "openai:m"


@pytest.mark.parametrize("base_url,model", [("", "m"), ("https://x/v1", " ")])
def test_custom_route_needs_url_and_model(base_url, model):
    with pytest.raises(ValueError, match="base URL and a model"):
        RunSettings.custom(base_url, "key", model)


def test_missing_role_rejected():
    with pytest.raises(ValueError, match="No model for the role"):
        RunSettings(provider="anthropic", models={"brief": "anthropic:x"})


# --- Keys never leak ---

def test_keys_not_in_repr_or_record():
    s = RunSettings.preset("anthropic", "sk-ant-SECRET", tavily_api_key="tvly-SECRET")
    assert "SECRET" not in repr(s)
    assert "SECRET" not in str(s.to_record())
    assert s.to_record()["models"]["blueprint"] == "anthropic:claude-opus-5-5"


def test_two_runs_keep_their_own_keys():
    a = RunSettings.preset("anthropic", "sk-ant-A")
    b = RunSettings.preset("anthropic", "sk-ant-B")
    assert (a.llm_api_key, b.llm_api_key) == ("sk-ant-A", "sk-ant-B")
    a.models["analyst"] = "changed"
    assert b.model("analyst") == "anthropic:claude-sonnet-5-5"  # no shared dict between runs


def test_provider_and_leftover_model_of_another_provider_raise(monkeypatch):
    """LLM_PROVIDER=gemini with LLM_MODEL=anthropic:... in .env would send the Gemini key to Anthropic."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "anthropic:claude-haiku-5-5")
    with pytest.raises(ValueError, match="LLM_MODEL=anthropic:claude-haiku-5-5"):
        RunSettings.from_env()


def test_provider_and_leftover_role_model_raise(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL_BLUEPRINT", "anthropic:claude-opus-5-5")
    with pytest.raises(ValueError, match="LLM_MODEL_BLUEPRINT"):
        RunSettings.from_env()


def test_empty_leftovers_keep_the_preset(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "")
    assert RunSettings.from_env().model("blueprint") == "google_genai:gemini-3.6-flash"


def test_one_env_holds_the_keys_of_several_providers(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_JUDGE_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-a")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-g")
    assert RunSettings.from_env(mode="local").llm_api_key == "sk-ant-a"
    gemini = RunSettings.from_env(mode="local", provider="gemini")
    assert gemini.provider == "gemini" and gemini.llm_api_key == "AIza-g"
    assert RunSettings.from_env(mode="public", provider="gemini").llm_api_key is None


def test_a_key_of_another_provider_is_refused(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_JUDGE_MODEL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "AQ.gemini-key")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        RunSettings.from_env(mode="local", provider="anthropic")
    assert RunSettings.from_env(mode="local", provider="gemini").llm_api_key == "AQ.gemini-key"
