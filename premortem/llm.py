from langchain.chat_models import init_chat_model

from premortem import config


def get_llm(temperature: float | None = config.DEFAULT_TEMPERATURE, model: str | None = None):
    if not config.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is not set: copy .env.example to .env and fill it in")
    kwargs = {} if temperature is None else {"temperature": temperature}
    return init_chat_model(model or config.LLM_MODEL, api_key=config.LLM_API_KEY, **kwargs)
