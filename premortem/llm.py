"""The single place where chat models are built: one model per role, from the run's settings.

Inside the graph the settings travel in config["configurable"]["settings"] (see runner.Run), so a node
calls get_llm("strategist") and gets the model, key and base URL of its own run. Outside the graph
(evaluation, scripts) the caller passes the settings explicitly.
"""
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock

from langchain.chat_models import init_chat_model
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tools import tool
from langgraph.config import get_config
from pydantic import BaseModel

from premortem.config import RunSettings
from premortem.providers import requests_per_minute

# A 429 waits and retries (with backoff) instead of failing a run that has been going for minutes
MAX_RETRIES = 6
# Seconds per request. Without it a model that never answers (a free-tier 504) stalls the run for minutes.
TIMEOUT = 180
CHECK_TIMEOUT = 45
ModelRole = str  # one of config.ROLES, or "eval_judge"


def current_settings() -> RunSettings:
    """The settings of the run this code is part of. Raises outside a run, so a node can never
    fall back to someone else's key."""
    try:
        settings = get_config()["configurable"].get("settings")
    except RuntimeError:  # not inside a runnable context
        settings = None
    if not isinstance(settings, RunSettings):
        raise RuntimeError('No run settings: pass config={"configurable": {"settings": RunSettings...}}')
    return settings


@contextmanager
def using_settings(settings: RunSettings):
    """Run nodes outside the graph (scripts, tests) as if they were part of a run with these settings."""
    token = var_child_runnable_config.set({"configurable": {"settings": settings}})
    try:
        yield settings
    finally:
        var_child_runnable_config.reset(token)


# One limiter per (model, key): free-tier limits apply per project, so runs that share a key share
# its quota. The key is hashed, never stored.
_limiters: dict[tuple[str, str], InMemoryRateLimiter] = {}
_limiters_lock = Lock()


def _rate_limiter(settings: RunSettings, model: str) -> InMemoryRateLimiter | None:
    rpm = requests_per_minute(settings.provider, model)
    if not rpm:
        return None
    digest = hashlib.sha256((settings.llm_api_key or "").encode()).hexdigest()
    with _limiters_lock:
        return _limiters.setdefault(
            (model, digest), InMemoryRateLimiter(requests_per_second=rpm / 60, check_every_n_seconds=0.2, max_bucket_size=1))


def model_id(role: ModelRole, settings: RunSettings) -> str:
    return settings.eval_judge if role == "eval_judge" else settings.model(role)


def get_llm(role: ModelRole, settings: RunSettings | None = None, max_retries: int = MAX_RETRIES,
            timeout: float = TIMEOUT):
    """A new chat model for one role of one run: its model, key, base URL, temperature and rate limit."""
    settings = settings or current_settings()
    if not settings.llm_api_key:
        raise RuntimeError("No LLM key for this run: paste one in the app, or set LLM_API_KEY in .env "
                           "with PREMORTEM_MODE=local")
    model = model_id(role, settings)
    judge = role in ("validator", "eval_judge")
    temperature = settings.judge_temperature if judge else settings.temperature
    kwargs = {"api_key": settings.llm_api_key, "max_retries": max_retries, "timeout": timeout}
    if temperature is not None:  # unset by default: Claude 5 models reject it
        kwargs["temperature"] = temperature
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    limiter = _rate_limiter(settings, model)
    if limiter:
        kwargs["rate_limiter"] = limiter
    return init_chat_model(model, **kwargs)


def is_anthropic(role: ModelRole, settings: RunSettings | None = None) -> bool:
    """Prompt caching markers (cache_control) are an Anthropic feature. Outside a run: False."""
    try:
        settings = settings or current_settings()
    except RuntimeError:
        return False
    return model_id(role, settings).startswith("anthropic:")


def invoke_structured(llm, messages, attempts: int = 2):
    """Invoke a with_structured_output model, retrying when it returns None.

    The model returns None when it answers in prose instead of calling the schema tool.
    Retry once, then raise, so no node ever writes None into the state.
    """
    for _ in range(attempts):
        result = llm.invoke(messages)
        if result is not None:
            return result
    raise RuntimeError(f"The model returned no structured output after {attempts} attempts")


# --- Check before running (roadmap, section 3) -----------------------------------------------------

@dataclass
class Check:
    name: str  # "plain call", "tool call", "structured output"
    ok: bool
    message: str


class _Echo(BaseModel):
    word: str


@tool
def ping(word: str) -> str:
    """Return the word unchanged."""
    return word


def explain_error(e: Exception, provider: str) -> str:
    """An API error in plain language, for the setup screen."""
    text = f"{type(e).__name__}: {e}"
    low = text.lower()
    if any(s in low for s in ("401", "403", "unauthorized", "authentication", "invalid api key", "api key not valid",
                              "permission")):
        return f"The key was rejected by {provider}. Check it and try again."
    if "429" in low or "rate limit" in low or "quota" in low or "resource_exhausted" in low:
        return "The provider says the limit is reached (rate limit or daily quota). Wait a minute or use another key."
    if "504" in low or "deadline" in low or "timed out" in low or "timeout" in low:
        return "The model did not answer in time. The provider may be overloaded: retry later or choose another model."
    if "404" in low or "not found" in low or "does not exist" in low:
        return "The provider does not know this model name. Check the model or choose another preset."
    return text[:300]


def check_model(settings: RunSettings, role: ModelRole = "analyst") -> list[Check]:
    """Three tiny requests on the agents' model: a plain call, a tool call and a structured output.
    The Analyst needs tools to search the web, and every agent returns a Pydantic model."""
    from premortem.providers import PRESETS

    preset = PRESETS.get(settings.provider)
    provider = preset.label.split(" (")[0] if preset else "the provider"
    checks: list[Check] = []
    try:
        llm = get_llm(role, settings, max_retries=1, timeout=CHECK_TIMEOUT)
    except Exception as e:
        return [Check("plain call", False, explain_error(e, provider))]

    try:
        llm.invoke("Reply with the single word OK.")
        checks.append(Check("plain call", True, "The model answers."))
    except Exception as e:  # nothing else can work: stop here
        return [Check("plain call", False, explain_error(e, provider))]

    try:
        response = llm.bind_tools([ping]).invoke("Call the ping tool with the word 'hello'.")
        ok = bool(getattr(response, "tool_calls", None))
        checks.append(Check("tool call", ok, "The model can use tools." if ok else
                            "This model did not call the tool, so the Analyst cannot search the web: choose another model."))
    except Exception as e:
        checks.append(Check("tool call", False, f"This model cannot use tools ({explain_error(e, provider)})"))

    try:
        result = llm.with_structured_output(_Echo).invoke("Return the word 'hello' in the field `word`.")
        ok = isinstance(result, _Echo)
        checks.append(Check("structured output", ok, "The model returns structured answers." if ok else
                            "This model did not return the expected fields, so the agents cannot write their outputs."))
    except Exception as e:
        checks.append(Check("structured output", False,
                            f"This model cannot return structured answers ({explain_error(e, provider)})"))
    return checks
