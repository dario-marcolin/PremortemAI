"""Tavily web search, exposed as a LangChain tool for the Analyst."""

from functools import lru_cache

from langchain_core.tools import tool
from langchain_tavily import TavilySearch

from premortem import config

SNIPPET_CHARS = 500  # compact results: the LLM never sees full pages


@lru_cache(maxsize=1)
def _client() -> TavilySearch:
    return TavilySearch(max_results=config.MAX_SEARCH_RESULTS, tavily_api_key=config.TAVILY_API_KEY)


@tool
def web_search(query: str) -> list[dict]:
    """Search the web for market, competitor or consumer information.
    Use it for facts the company document does not give: competitor brands
    and prices, market size and growth, consumer trends in the target country.
    Use precise queries that include the product category and the
    target country, e.g. "protein crisps brands France".
    Returns up to 5 results with title, url and snippet; cite the url as the source.
    Returns [{"error": ...}] if the search fails or finds nothing: rephrase and retry."""
    if not config.TAVILY_API_KEY:
        return [{"error": "TAVILY_API_KEY is not set: web search is unavailable."}]
    try:
        response = _client().invoke({"query": query})
    except Exception as e:  # errors go back to the LLM as data, so it can retry
        return [{"error": f"Search failed: {e}"}]
    if not isinstance(response, dict):
        return [{"error": f"Search failed: {response}"}]
    if "error" in response:
        return [{"error": str(response["error"])}]
    results = [
        {"title": r.get("title", ""), "url": r["url"], "snippet": (r.get("content") or "")[:SNIPPET_CHARS]}
        for r in response.get("results", [])[: config.MAX_SEARCH_RESULTS]
        if r.get("url")
    ]
    return results or [{"error": f"No results for '{query}'. Try a broader or differently worded query."}]
