import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

# --- Per-run settings (Phase 12) ---------------------------------------------------------------

# The pipeline roles that call an LLM. Each one gets its own model.
ROLES = ("brief", "analyst", "strategist", "creative", "validator", "blueprint")
Role = Literal["brief", "analyst", "strategist", "creative", "validator", "blueprint"]
Mode = Literal["local", "public"]


def current_mode() -> Mode:
    """PREMORTEM_MODE: `local` = keys from .env (our demo); `public` or unset = the visitor pastes a key."""
    value = (os.getenv("PREMORTEM_MODE") or "public").strip().lower()
    if value not in ("local", "public"):
        raise ValueError(f"PREMORTEM_MODE must be 'local' or 'public', not {value!r}")
    return value


def _clean(value: str | None) -> str | None:
    """Pasted keys often carry spaces or newlines; an empty value means no value."""
    value = (value or "").strip()
    return value or None


def _env_float(name: str) -> float | None:
    value = _clean(os.getenv(name))
    return float(value) if value is not None else None


@dataclass(frozen=True)
class RunSettings:
    """Everything one run needs to reach its models: provider, keys, base URL, one model per role.

    One object per run, so two visitors with different keys never share a client.
    Models are `init_chat_model` ids (`provider:model`). Keys are kept out of repr()
    and out of to_record(), so they never reach logs, run.json or state.json.
    """

    provider: str
    models: dict[str, str]
    llm_api_key: str | None = field(default=None, repr=False)
    tavily_api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    # The evaluation judge (eval/metrics.py) is not part of the pipeline: a cheaper model is fine
    eval_judge: str | None = None
    # Unset by default: recent Claude models reject the temperature parameter
    temperature: float | None = None
    # Used by the Validator's judge and the evaluation judge, for models that accept it (e.g. 0)
    judge_temperature: float | None = None

    def __post_init__(self):
        missing = [role for role in ROLES if not self.models.get(role)]
        if missing:
            raise ValueError(f"No model for the role(s): {', '.join(missing)}")
        unknown = set(self.models) - set(ROLES)
        if unknown:
            raise ValueError(f"Unknown role(s): {', '.join(sorted(unknown))}")
        object.__setattr__(self, "models", dict(self.models))
        object.__setattr__(self, "llm_api_key", _clean(self.llm_api_key))
        object.__setattr__(self, "tavily_api_key", _clean(self.tavily_api_key))
        object.__setattr__(self, "base_url", _clean(self.base_url))
        object.__setattr__(self, "eval_judge", self.eval_judge or self.models["validator"])

    def model(self, role: Role) -> str:
        return self.models[role]

    def to_record(self) -> dict:
        """What run.json may store: provider, base URL and models. Never the keys."""
        return {"provider": self.provider, "base_url": self.base_url,
                "models": dict(self.models), "eval_judge": self.eval_judge}

    # --- Constructors ---------------------------------------------------------------------------

    @classmethod
    def from_env(cls, mode: Mode | None = None, provider: str | None = None) -> "RunSettings":
        """The CLI, the evaluation and `local` mode.

        Starts from a preset: LLM_PROVIDER (a preset name, e.g. `gemini`), else the preset whose models
        use LLM_MODEL's prefix, else `anthropic`. LLM_MODEL, when set, replaces every role;
        LLM_MODEL_<ROLE> (e.g. LLM_MODEL_BLUEPRINT) replaces one role.
        provider= replaces LLM_PROVIDER (the evaluation runs the gemini preset and judges with anthropic).
        The key: <PROVIDER>_API_KEY (e.g. ANTHROPIC_API_KEY, GEMINI_API_KEY), else LLM_API_KEY, so one .env
        can hold the keys of several providers. In `public` mode no LLM key is read: the visitor brings it.
        """
        from premortem.providers import PRESETS

        mode = mode or current_mode()
        base_model = _clean(os.getenv("LLM_MODEL"))
        provider = _clean(provider) or _clean(os.getenv("LLM_PROVIDER"))
        if provider is None and base_model and ":" in base_model:
            prefix = _prefix(base_model)
            provider = next((name for name, p in PRESETS.items() if _prefix(p.models["analyst"]) == prefix), prefix)
        provider = (provider or "anthropic").lower()
        preset = PRESETS.get(provider)
        if preset is None and base_model is None:
            raise ValueError(f"No preset named {provider!r}: choose one of {', '.join(PRESETS)} or set LLM_MODEL")

        models = dict(preset.models) if preset else {}
        if base_model:
            models = {role: base_model for role in ROLES}
        for role in ROLES:
            override = _clean(os.getenv(f"LLM_MODEL_{role.upper()}"))
            if override:
                models[role] = override
        if preset:
            # e.g. LLM_PROVIDER=gemini with an old LLM_MODEL=anthropic:... left in .env: the Gemini key
            # would be sent to Anthropic. Say which variable to change instead.
            expected = _prefix(preset.models["analyst"])
            wrong = [name for name in ["LLM_MODEL", *[f"LLM_MODEL_{r.upper()}" for r in ROLES]]
                     if (value := _clean(os.getenv(name))) and _prefix(value) != expected]
            if wrong:
                raise ValueError(f"The {provider!r} preset uses {expected}: models, but "
                                 f"{', '.join(f'{n}={os.getenv(n)}' for n in wrong)}. "
                                 "Empty these lines in .env, or set them to models of the same provider.")
        _check_same_provider(models)

        return cls(
            provider=provider,
            models=models,
            llm_api_key=_env_key(provider) if mode == "local" else None,
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL") or (preset.base_url if preset else None),
            eval_judge=_clean(os.getenv("LLM_JUDGE_MODEL")) or (preset.eval_judge if preset else None),
            temperature=_env_float("LLM_TEMPERATURE"),
            judge_temperature=_env_float("LLM_JUDGE_TEMPERATURE"),
        )

    @classmethod
    def preset(cls, name: str, llm_api_key: str, tavily_api_key: str | None = None) -> "RunSettings":
        """The UI, preset route: the visitor gives a key, the preset gives the model of each role."""
        from premortem.providers import PRESETS

        if name not in PRESETS:
            raise ValueError(f"Unknown preset {name!r}; choose one of: {', '.join(PRESETS)}")
        preset = PRESETS[name]
        return cls(provider=name, models=dict(preset.models), llm_api_key=llm_api_key,
                   tavily_api_key=tavily_api_key, base_url=preset.base_url, eval_judge=preset.eval_judge)

    @classmethod
    def custom(cls, base_url: str, llm_api_key: str, model: str, big_model: str | None = None,
               tavily_api_key: str | None = None) -> "RunSettings":
        """The UI, custom route: any OpenAI-compatible endpoint, one model for every role
        plus an optional bigger model for the blueprint summary."""
        base_url, model, big_model = _clean(base_url), _clean(model), _clean(big_model)
        if not base_url or not model:
            raise ValueError("The custom route needs a base URL and a model name")
        models = {role: f"openai:{model}" for role in ROLES}
        models["blueprint"] = f"openai:{big_model or model}"
        return cls(provider="custom", models=models, llm_api_key=llm_api_key,
                   tavily_api_key=tavily_api_key, base_url=base_url)


def _env_key(provider: str) -> str | None:
    """The LLM key of a provider in .env: <PROVIDER>_API_KEY first, else LLM_API_KEY.
    LLM_API_KEY is refused when its prefix says it belongs to another provider: a Gemini key
    must never be sent to Anthropic."""
    from premortem.providers import detect_provider

    own = _clean(os.getenv(f"{provider.upper()}_API_KEY"))
    if own:
        return own
    key = _clean(os.getenv("LLM_API_KEY"))
    owner = detect_provider(key)
    if key and owner and owner != provider and provider != "custom":
        raise ValueError(f"LLM_API_KEY looks like a {owner} key, but the provider is {provider!r}. "
                         f"Put the {provider} key in {provider.upper()}_API_KEY (or in LLM_API_KEY).")
    return key


def _prefix(model: str) -> str:
    """The init_chat_model provider of a model id: "google_genai:gemini-x" -> "google_genai"."""
    return model.split(":", 1)[0] if ":" in model else ""


def _check_same_provider(models: dict[str, str]) -> None:
    """One run has one key, so every role must use the same provider."""
    prefixes = {_prefix(m) for m in models.values()}
    if len(prefixes) > 1:
        listed = ", ".join(f"{role}={m}" for role, m in models.items())
        raise ValueError(f"Every role must use the same provider (one key per run): {listed}")


# --- Pipeline limits ---------------------------------------------------------------------------

MAX_REVISIONS = 2
# Public app: web searches each visitor may run on our Tavily key per browser session (roadmap 15.9)
SEARCHES_PER_SESSION = 80
MAX_SEARCH_RESULTS = 5
ANALYST_RECURSION_LIMIT = 15
DOC_TOKEN_BUDGET = 60_000

# Each run writes outputs/<run_id>/ (blueprint.md, state.json); run_id is the graph thread_id
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
