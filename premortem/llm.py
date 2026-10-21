from langchain.chat_models import init_chat_model

from premortem import config


def get_llm(temperature: float = config.DEFAULT_TEMPERATURE):
    if not config.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is not set: copy .env.example to .env and fill it in")
    return init_chat_model(
        config.LLM_MODEL,
        temperature=temperature,
        api_key=config.LLM_API_KEY,
    )
