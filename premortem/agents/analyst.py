"""Analyst: ReAct subgraph that researches the market and returns an Analysis.

    analyst_llm ──(tool call)──► tools ──► analyst_llm
         │
         └──(no tool call, or MAX_TOOL_ROUNDS reached)──► analyst_report ──► END
"""

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from premortem import config
from premortem.llm import get_llm, invoke_structured
from premortem.prompts import load_prompt
from premortem.schemas import Analysis, Source
from premortem.state import AnalystState
from premortem.tools.web_search import web_search

# Each round is one analyst_llm step and one tools step; the final report takes one more.
MAX_TOOL_ROUNDS = (config.ANALYST_RECURSION_LIMIT - 2) // 2
SOURCE_ID = re.compile(r"\bS[1-9]\d*\b")
# A bracket group ("[S2]", "[S1, S3]") or a bare id ("1.3M adults, S3")
CITATION = re.compile(r"\[[^\]]*\]|\bS[1-9]\d*\b")


def get_analyst_tools() -> list:
    """The single place where Analyst tools are registered (bonus tools go here)."""
    return [web_search]


def _context(state: AnalystState) -> HumanMessage:
    return HumanMessage(
        f"<brief>\n{state['brief'].model_dump_json(indent=2)}\n</brief>\n\n"
        f"<document>\n{state['document_text']}\n</document>"
    )


def _tool_rounds(messages: list[BaseMessage]) -> int:
    return sum(1 for m in messages if isinstance(m, AIMessage) and m.tool_calls)


def analyst_llm(state: AnalystState) -> dict:
    llm = get_llm().bind_tools(get_analyst_tools())
    messages = state.get("messages", [])
    response = llm.invoke([SystemMessage(load_prompt("analyst")), _context(state), *messages])
    return {"messages": [response]}


def route_analyst(state: AnalystState) -> str:
    if tools_condition(state) == "tools" and _tool_rounds(state["messages"]) <= MAX_TOOL_ROUNDS:
        return "tools"
    return "analyst_report"


def research_log(messages: list[BaseMessage]) -> str:
    """The conversation as plain text, so the report call needs no tool history."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    lines = []
    for m in messages:
        if isinstance(m, AIMessage):
            for call in m.tool_calls:
                query = call["args"].get("query", call["args"])
                # The call that hit MAX_TOOL_ROUNDS is never run: say so, so no figure is attributed to it
                lines.append(f"Search: {query}" if call["id"] in answered else f"Search not run (limit reached): {query}")
            if m.text.strip():
                lines.append(f"Analyst notes:\n{m.text.strip()}")
        elif isinstance(m, ToolMessage):
            lines.append(f"Results:\n{m.text}")
    return "\n\n".join(lines) or "No searches were made."


def searched_urls(messages: list[BaseMessage]) -> set[str]:
    urls = set()
    for m in messages:
        if not isinstance(m, ToolMessage):
            continue
        try:
            results = json.loads(m.text)
        except json.JSONDecodeError:
            continue
        urls.update(r["url"] for r in results if isinstance(r, dict) and r.get("url"))
    return urls


def _url_key(url: str) -> str:
    """Compare URLs without scheme, "www." and trailing slash: LLMs often drop them."""
    url = re.sub(r"^https?://(www\.)?", "", url.strip(), flags=re.IGNORECASE)
    return url.rstrip("/").lower()


def _texts(analysis: Analysis) -> list[str]:
    """Free-text fields that may cite source ids inline, e.g. "480M euros [S2]"."""
    texts = [analysis.market_overview, *analysis.customer_needs, *analysis.data_quality_notes]
    texts += [c.positioning for c in analysis.competitors]
    for s in analysis.segments:
        texts += [s.description, s.estimated_size or "", *s.needs]
    return texts


def rewrite_citations(text: str, listed: set[str], replace) -> str:
    """Apply replace to the source ids of text: every id inside brackets, but a bare id
    only when it is a listed source, so names like "Galaxy S24" are left intact."""

    def sub(match: re.Match) -> str:
        token = match.group()
        if token.startswith("["):
            return SOURCE_ID.sub(lambda m: replace(m.group()), token)
        return replace(token) if token in listed else token

    return CITATION.sub(sub, text)


def normalize_sources(analysis: Analysis, allowed_urls: set[str]) -> Analysis:
    """Renumber sources S1, S2... (document first, then web) and drop what cannot be traced.

    Web sources whose URL was never returned by a search are removed, and so are ids that
    point to no listed source; both removals are recorded in data_quality_notes. Sources
    that nothing cites are dropped silently.
    """
    cited = {i for c in analysis.competitors for i in c.source_ids}
    cited |= {i for s in analysis.segments for i in s.source_ids}
    listed = {s.id for s in analysis.sources}
    for text in _texts(analysis):
        rewrite_citations(text, listed, lambda i: cited.add(i) or i)

    added_notes: list[str] = []
    kept: list[Source] = []
    by_reference: dict[tuple[str, str], str] = {}
    mapping: dict[str, str] = {}
    ordered = [s for s in analysis.sources if s.kind == "document"] + [
        s for s in analysis.sources if s.kind == "web"
    ]
    allowed = {_url_key(u): u for u in allowed_urls}
    for source in ordered:
        if source.id not in cited:
            continue
        reference = source.reference
        if source.kind == "web":
            if _url_key(reference) not in allowed:
                added_notes.append(f"Removed a source ({reference}): URL not found in the search results.")
                continue
            reference = allowed[_url_key(reference)]  # the exact URL the search returned
        key = (source.kind, reference)
        if key not in by_reference:
            by_reference[key] = f"S{len(kept) + 1}"
            kept.append(Source(id=by_reference[key], kind=source.kind, reference=reference))
        mapping[source.id] = by_reference[key]

    def remap_ids(ids: list[str], owner: str) -> list[str]:
        unknown = [i for i in ids if i not in mapping]
        if unknown:
            added_notes.append(f"{owner}: removed {len(unknown)} citation(s) that match no traceable source.")
        return list(dict.fromkeys(mapping[i] for i in ids if i in mapping))

    def remap_text(text: str | None) -> str | None:
        if text is None:
            return None
        return rewrite_citations(text, listed, lambda i: mapping.get(i, "S?"))

    competitors = [
        c.model_copy(
            update={
                "source_ids": remap_ids(c.source_ids, f"Competitor {c.name}"),
                "positioning": remap_text(c.positioning),
            }
        )
        for c in analysis.competitors
    ]
    segments = [
        s.model_copy(
            update={
                "source_ids": remap_ids(s.source_ids, f"Segment {s.segment_id}"),
                "description": remap_text(s.description),
                "estimated_size": remap_text(s.estimated_size),
                "needs": [remap_text(n) for n in s.needs],
            }
        )
        for s in analysis.segments
    ]
    return analysis.model_copy(
        update={
            "market_overview": remap_text(analysis.market_overview),
            "customer_needs": [remap_text(n) for n in analysis.customer_needs],
            "competitors": competitors,
            "segments": segments,
            "sources": kept,
            "data_quality_notes": [remap_text(n) for n in analysis.data_quality_notes] + added_notes,
        }
    )


def analyst_report(state: AnalystState) -> dict:
    llm = get_llm().with_structured_output(Analysis)
    messages = state.get("messages", [])
    analysis = invoke_structured(
        llm,
        [
            SystemMessage(load_prompt("analyst_report")),
            HumanMessage(
                f"{_context(state).content}\n\n"
                f"<research_log>\n{research_log(messages)}\n</research_log>\n\n"
                "Write the structured analysis."
            ),
        ]
    )
    return {"analysis": normalize_sources(analysis, searched_urls(messages))}


def build_analyst():
    tools = get_analyst_tools()
    g = StateGraph(AnalystState)
    g.add_node("analyst_llm", analyst_llm)
    g.add_node("tools", ToolNode(tools))
    g.add_node("analyst_report", analyst_report)
    g.add_edge(START, "analyst_llm")
    g.add_conditional_edges("analyst_llm", route_analyst, ["tools", "analyst_report"])
    g.add_edge("tools", "analyst_llm")
    g.add_edge("analyst_report", END)
    return g.compile().with_config(recursion_limit=config.ANALYST_RECURSION_LIMIT)
