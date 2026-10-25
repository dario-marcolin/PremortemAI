import os

from dotenv import load_dotenv

load_dotenv()

LLM_MODEL = os.getenv("LLM_MODEL", "anthropic:claude-sonnet-5-5")
# The judge needs a stronger model than the agents: Haiku was unstable as a judge (dev log 25 Oct)
JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL") or LLM_MODEL
LLM_API_KEY = os.getenv("LLM_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Unset by default: recent Claude models reject the temperature parameter
DEFAULT_TEMPERATURE = float(os.environ["LLM_TEMPERATURE"]) if os.getenv("LLM_TEMPERATURE") else None
# The roadmap wants a low judge temperature (e.g. 0), but Claude 5 models reject it: set it only for other models
JUDGE_TEMPERATURE = float(os.environ["LLM_JUDGE_TEMPERATURE"]) if os.getenv("LLM_JUDGE_TEMPERATURE") else None

MAX_REVISIONS = 2
MAX_SEARCH_RESULTS = 5
ANALYST_RECURSION_LIMIT = 15
DOC_TOKEN_BUDGET = 60_000
