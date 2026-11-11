"""Provider presets: the model of each role for every supported provider. A new provider is one new row.

Model ids are `init_chat_model` ids (`<langchain provider>:<model>`). Only `anthropic` and `gemini` are
tested end to end; the other presets are checked with check_model() only (roadmap, section 3).
Free tiers change often: the Gemini row was set from the published limits of November 2026.
"""
from dataclasses import dataclass, field

from premortem.config import ROLES


@dataclass(frozen=True)
class Preset:
    label: str
    models: dict[str, str]  # role -> init_chat_model id
    eval_judge: str
    note: str = ""  # one line for the setup screen: what this choice means
    base_url: str | None = None  # for providers reached through the OpenAI API (OpenRouter)
    # Requests per minute allowed by the free tier, per model; a limiter keeps the run under it
    requests_per_minute: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if set(self.models) != set(ROLES):
            raise ValueError(f"{self.label}: the preset must give a model for every role")


def _roles(agents: str, blueprint: str) -> dict[str, str]:
    """Brief, Analyst, Strategist, Creative and Validator share one model; the blueprint summary gets the big one."""
    return {role: (blueprint if role == "blueprint" else agents) for role in ROLES}


PRESETS: dict[str, Preset] = {
    "anthropic": Preset(
        label="Anthropic (Claude)",
        # Professor's notes: agents on a better model, big model for the final blueprint (one call per run)
        models=_roles(agents="anthropic:claude-sonnet-5-5", blueprint="anthropic:claude-opus-5-5"),
        # Professor's notes: cheaper model for the evaluation; its spread is measured in 12.8 (dev log 25 Oct)
        eval_judge="anthropic:claude-haiku-5-5",
        note="Paid key. The models the system was tuned on.",
    ),
    "gemini": Preset(
        label="Google Gemini (free tier)",
        # One run makes dozens of calls: only Flash-Lite has a daily free quota that fits (about 500 a day).
        # The blueprint summary is one call: Gemini 3.6 Flash. 3.8 Flash timed out (504) on the free tier
        # twice in a row on 11 Nov (dev log), while 3.6 Flash answered in 6 s.
        models=_roles(agents="google_genai:gemini-3.5-flash-lite", blueprint="google_genai:gemini-3.6-flash"),
        eval_judge="google_genai:gemini-3.5-flash-lite",
        note="Free: slower because of the rate limits, weaker plans, and Google may use the data.",
        requests_per_minute={"google_genai:gemini-3.5-flash-lite": 12, "google_genai:gemini-3.6-flash": 4},
    ),
    "openai": Preset(
        label="OpenAI",
        models=_roles(agents="openai:gpt-5-mini", blueprint="openai:gpt-5"),
        eval_judge="openai:gpt-5-mini",
        note="Paid key. Supported, less tested than Anthropic and Gemini.",
    ),
    "mistral": Preset(
        label="Mistral",
        models=_roles(agents="mistralai:mistral-medium-latest", blueprint="mistralai:mistral-large-latest"),
        eval_judge="mistralai:mistral-medium-latest",
        note="Supported, less tested than Anthropic and Gemini.",
    ),
    "groq": Preset(
        label="Groq",
        models=_roles(agents="groq:openai/gpt-oss-120b", blueprint="groq:openai/gpt-oss-120b"),
        eval_judge="groq:openai/gpt-oss-120b",
        note="Free tier with tight limits. Supported, less tested.",
        requests_per_minute={"groq:openai/gpt-oss-120b": 25},
    ),
    "openrouter": Preset(
        label="OpenRouter",
        # OpenRouter speaks the OpenAI API: the vendor is part of the model name
        models=_roles(agents="openai:openai/gpt-5-mini", blueprint="openai:anthropic/claude-opus-5-5"),
        eval_judge="openai:openai/gpt-5-mini",
        base_url="https://openrouter.ai/api/v1",
        note="One key for many vendors. Supported, less tested.",
    ),
}

# Key prefix -> preset. Order matters: the specific "sk-" prefixes come before plain "sk-" (OpenAI).
# Google AI Studio keys: the classic "AIza..." and the newer "AQ." format.
KEY_PREFIXES = [("sk-ant-", "anthropic"), ("sk-or-", "openrouter"), ("gsk_", "groq"), ("AIza", "gemini"),
                ("AQ.", "gemini"), ("sk-", "openai")]


def detect_provider(key: str | None) -> str | None:
    """The preset a key most likely belongs to, from its prefix; None when the prefix says nothing
    (e.g. Mistral keys). The visitor can always change the guess."""
    key = (key or "").strip()
    return next((name for prefix, name in KEY_PREFIXES if key.startswith(prefix)), None)


def requests_per_minute(provider: str, model: str) -> float | None:
    preset = PRESETS.get(provider)
    return preset.requests_per_minute.get(model) if preset else None
