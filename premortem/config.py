import os

from dotenv import load_dotenv

load_dotenv()

LLM_MODEL = os.getenv("LLM_MODEL", "anthropic:claude-sonnet-5-5")
LLM_API_KEY = os.getenv("LLM_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

DEFAULT_TEMPERATURE = 0.2

MAX_REVISIONS = 2
MAX_SEARCH_RESULTS = 5
ANALYST_RECURSION_LIMIT = 15
DOC_TOKEN_BUDGET = 60_000
