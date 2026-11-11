"""Tavily web search, exposed as a LangChain tool for the Analyst.

The Tavily key comes from the settings of the current run (config["configurable"]["settings"]),
and the client is built per call: no cached global, so two runs never share a client.
"""

from langchain_core.tools import tool
from langchain_tavily import TavilySearch

from premortem import config
from premortem.llm import current_settings

SNIPPET_CHARS = 500  # compact results: the LLM never sees full pages
NO_KEY = "No Tavily key: web search is unavailable, the analysis uses the document only."


def _client(api_key: str) -> TavilySearch:
    return TavilySearch(max_results=config.MAX_SEARCH_RESULTS, tavily_api_key=api_key)


def _tavily_key() -> str | None:
    try:
        return current_settings().tavily_api_key
    except RuntimeError:  # called outside a run
        return None


@tool
def web_search(query: str) -> list[dict]:
    """Search the web for market, competitor or consumer information.
    Use it for facts the company document does not give: competitor brands
    and prices, market size and growth, consumer trends in the target country.
    Use precise queries that include the product category and the
    target country, e.g. "protein crisps brands France".
    Returns up to 5 results with title, url and snippet; cite the url as the source.
    Returns [{"error": ...}] if the search fails or finds nothing: rephrase and retry."""
    api_key = _tavily_key()
    if not api_key:
        return [{"error": NO_KEY}]
    try:
        response = _client(api_key).invoke({"query": query})
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
