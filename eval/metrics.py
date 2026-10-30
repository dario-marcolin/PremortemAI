"""Evaluation metrics (Phase 10) for one launch plan: the multi-agent blueprint or the baseline.

Both systems are read the same way, from their output folder (blueprint.md, run.json), so
no metric depends on the internals of the pipeline. The validation log and the sources list
are not part of the plan that is scored; the sources list resolves the [n] references.

| Metric        | How                                                                         |
|---------------|-----------------------------------------------------------------------------|
| Traceability  | an LLM extracts the factual claims (with their [n] references), the code    |
|               | checks the quote and the references: % of claims with a valid source        |
| Faithfulness  | each figure of those claims is searched, in code, in the document and in    |
|               | the pages of the sources the claim cites                                    |
| Coherence     | LLM judge, fixed rubric (eval/prompts/coherence.md), 1 to 5, twice          |
| Trap          | same judge call: is the primary target the trap segment of the case?        |
| Cost, latency | tokens and seconds from run.json                                            |

A source is valid when it is the company document or a URL that exists (the page answers,
even if it refuses to be read). A reference with neither (e.g. "Nielsen 2024") is not valid:
nobody can check it.

    evaluate(out_dir, document_text, trap)   # writes out_dir/metrics.json
"""

import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from socket import gaierror

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from premortem import config
from premortem.llm import get_llm, invoke_structured

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
CASES_FILE = EVAL_DIR / "cases" / "cases.json"
PROMPTS = EVAL_DIR / "prompts"

FETCH_TIMEOUT = 10
ROUNDING = 0.03  # largest relative gap accepted as rounding between a figure and a source
FETCH_MAX_BYTES = 3_000_000
NOT_PLAN = re.compile(r"validation log|sources|references", re.I)
SOURCE_LINE = re.compile(r"^\s*(?:[-*]\s*)?\[?(\d+)[\].]\s+(.+?)\s*$", re.M)
URL = re.compile(r"https?://[^\s<>)\]]+")
MARKERS = re.compile(r"\[([\d,;\s\-–]+)\]")
NUMBER = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[,.   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s*(k|thousand|millions?|mio|mn|m|billions?|bn|mrd|milliards?)\b)?",
    re.I,
)
SCALES = {"k": 1e3, "thousand": 1e3, "million": 1e6, "millions": 1e6, "mio": 1e6, "mn": 1e6, "m": 1e6,
          "billion": 1e9, "billions": 1e9, "bn": 1e9, "mrd": 1e9, "milliard": 1e9, "milliards": 1e9}
SPACES = "   "


# ── cases ───────────────────────────────────────────────────────────────────────────────

def load_cases() -> list[dict]:
    return json.loads(CASES_FILE.read_text())


def find_case(document: str | Path) -> dict | None:
    """The eval case of a document, by file name (an upload keeps the original name)."""
    name = Path(document).name
    return next((c for c in load_cases() if Path(c["document"]).name == name), None)


# ── the plan: sections, sources, references ─────────────────────────────────────────────

def split_sections(markdown: str) -> list[tuple[str, str]]:
    """(heading, text) for each "## " section; the text before the first one has heading ""."""
    parts = re.split(r"^##\s+(.*)$", markdown, flags=re.M)
    return [("", parts[0])] + list(zip(parts[1::2], parts[2::2]))


def plan_text(markdown: str) -> str:
    """The plan without its validation log and sources list."""
    return "".join(f"## {h}\n{t}" if h else t for h, t in split_sections(markdown) if not NOT_PLAN.search(h))


def parse_sources(markdown: str) -> dict[str, dict]:
    """{"1": {"reference", "kind", "url"}} from the Sources section. kind: document, web or other."""
    body = "\n".join(t for h, t in split_sections(markdown) if re.search(r"sources|references", h, re.I))
    sources = {}
    for number, reference in SOURCE_LINE.findall(body):
        url = URL.search(reference)
        kind = "web" if url else "document" if re.search(r"\bdocument\b", reference, re.I) else "other"
        sources[number] = {"reference": reference.strip("<> "), "kind": kind,
                           "url": url.group().rstrip(".,;") if url else None}
    return sources


def _plain(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", re.sub(r"[*_`|]", " ", text)).strip().lower()


def markers(text: str) -> set[str]:
    """Reference numbers cited in text: "[1]", "[1, 3]", "[2-4]"."""
    found = set()
    for group in MARKERS.findall(text):
        for part in re.split(r"[,;\s]+", group.strip()):
            if m := re.fullmatch(r"(\d+)[-–](\d+)", part):
                found.update(str(n) for n in range(int(m[1]), int(m[2]) + 1))
            elif part.isdigit():
                found.add(part)
    return found


def locate(quote: str, plan: str) -> str | None:
    """The plan line that contains the quote (markdown and spacing ignored), or None.
    A quote may run over two lines (a list item and its continuation): both are returned."""
    target = _plain(quote)
    if not target:
        return None
    lines = plan.splitlines()
    for chunk in (lines, [" ".join(pair) for pair in zip(lines, lines[1:])]):
        if found := next((line for line in chunk if target in _plain(line)), None):
            return found
    return None


# ── figures ─────────────────────────────────────────────────────────────────────────────

def _readings(token: str) -> list[tuple[float, int]]:
    """(value, decimals) readings of a number as written. "2,300" is read both ways:
    2300 (English thousands) and 2.3 (European decimal comma)."""
    seps = [c for c in token if not c.isdigit()]
    digits = re.sub(r"\D", "", token)
    if not seps:
        return [(float(token), 0)]
    last = max(token.rfind(s) for s in set(seps))
    head, tail = re.sub(r"\D", "", token[:last]), token[last + 1:]
    if len(seps) == 1 and seps[0] in SPACES:
        return [(float(digits), 0)]
    if len(seps) == 1:
        decimal = (float(f"{head}.{tail}"), len(tail))
        return [(float(digits), 0), decimal] if len(tail) == 3 else [decimal]
    if len(set(seps)) == 1 or token[last] in SPACES:
        return [(float(digits), 0)]
    return [(float(f"{head}.{tail}"), len(tail))]


def figure_values(text: str) -> list[list[tuple[float, float]]]:
    """For each number in a figure: its readings as (value, tolerance). The tolerance is half
    a unit of the last digit written, so "1.3 million" matches 1,276,000 in a source, but at
    most ROUNDING of the value, so "10 million" does not match 9.6 million."""
    numbers = []
    for m in NUMBER.finditer(text):
        scale = SCALES.get((m[2] or "").lower(), 1)
        numbers.append([(v * scale, min(0.5 * 10 ** -d, ROUNDING * v) * scale) for v, d in _readings(m[1])])
    return numbers


def text_values(text: str) -> list[float]:
    """Every value a source text states, raw and scaled ("1.3 million" gives 1.3 and 1,300,000)."""
    values = []
    for m in NUMBER.finditer(text):
        scale = SCALES.get((m[2] or "").lower(), 1)
        for v, _ in _readings(m[1]):
            values += [v, v * scale] if scale != 1 else [v]
    return sorted(set(values))


def figure_in(figure: str, values: list[float]) -> bool | None:
    """True when every number of the figure is in values; None when the figure has no number."""
    numbers = figure_values(figure)
    if not numbers:
        return None
    return all(any(abs(v - s) <= tol + 1e-9 * abs(v) for v, tol in readings for s in values)
               for readings in numbers)


# ── web pages of the sources ────────────────────────────────────────────────────────────

@dataclass
class Page:
    url: str
    status: str  # ok: read; unreadable: exists but cannot be read; broken: does not exist; unchecked
    text: str = ""
    detail: str = ""

    @property
    def valid(self) -> bool:
        return self.status != "broken"


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("script", "style", "noscript")

    def handle_endtag(self, tag):
        self.skip -= self.skip > 0 and tag in ("script", "style", "noscript")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def fetch_page(url: str) -> Page:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PremortemAI evaluation)",
                                                   "Accept": "text/html,text/plain,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            kind = response.headers.get_content_type()
            body = response.read(FETCH_MAX_BYTES).decode(response.headers.get_content_charset() or "utf-8", "replace")
    except urllib.error.HTTPError as e:
        return Page(url, "broken" if e.code in (404, 410) else "unreadable", detail=f"HTTP {e.code}")
    except urllib.error.URLError as e:
        broken = isinstance(e.reason, gaierror)  # the domain does not exist
        return Page(url, "broken" if broken else "unreadable", detail=str(e.reason))
    except (TimeoutError, OSError, ValueError) as e:
        return Page(url, "unreadable", detail=type(e).__name__)
    if kind == "text/plain":
        return Page(url, "ok", body)
    if "html" not in kind:
        return Page(url, "unreadable", detail=kind)
    parser = _TextOnly()
    parser.feed(body)
    return Page(url, "ok", " ".join(parser.parts))


def fetch_pages(urls: list[str], fetch: bool = True) -> dict[str, Page]:
    urls = list(dict.fromkeys(urls))
    if not fetch:
        return {u: Page(u, "unchecked") for u in urls}
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(urls, pool.map(fetch_page, urls)))


# ── LLM calls: claims, coherence ────────────────────────────────────────────────────────

class Claim(BaseModel):
    quote: str = Field(description="Exact words of the claim, copied from the plan.")
    figures: list[str] = Field(default_factory=list, description="Each figure of the claim as written, with its unit.")
    refs: list[str] = Field(default_factory=list, description="Reference numbers the claim cites, e.g. ['1', '3'].")


class Claims(BaseModel):
    claims: list[Claim] = Field(default_factory=list, description="The factual claims of the plan.")


class CoherenceVerdict(BaseModel):
    # Flat fields: nested objects came back incomplete from the judge
    strategy_vs_analysis: int = Field(ge=1, le=5, description="Strategy vs analysis score, 1 to 5, per the rubric.")
    strategy_reason: str = Field(description="One or two sentences with the evidence from the plan.")
    campaign_vs_strategy: int = Field(ge=1, le=5, description="Campaign vs strategy score, 1 to 5, per the rubric.")
    campaign_reason: str = Field(description="One or two sentences with the evidence from the plan.")
    target: str = Field(description="The primary target segment the plan chooses, copied from the plan.")
    targets_trap: bool | None = Field(
        default=None, description="True if the primary target is the trap segment; null if no trap segment is given.")


def _judge(schema, prompt: str, content: str, usage: UsageMetadataCallbackHandler, attempts: int = 2):
    """One structured judge call, retried once when the answer does not fit the schema."""
    llm = get_llm(temperature=config.JUDGE_TEMPERATURE, model=config.JUDGE_MODEL).with_structured_output(schema)
    messages = [SystemMessage((PROMPTS / f"{prompt}.md").read_text()), HumanMessage(content)]
    for attempt in range(attempts):
        try:
            return invoke_structured(llm.with_config(callbacks=[usage]), messages)
        except ValidationError:
            if attempt == attempts - 1:
                raise


def extract_claims(plan: str, usage: UsageMetadataCallbackHandler) -> list[Claim]:
    return _judge(Claims, "claims", f"<plan>\n{plan}\n</plan>\n\nExtract the factual claims.", usage).claims


def judge_coherence(document_text: str, plan: str, trap: str | None,
                    usage: UsageMetadataCallbackHandler) -> CoherenceVerdict:
    trap_block = f"<trap_segment>\n{trap}\n</trap_segment>\n\n" if trap else ""
    content = (f"<document>\n{document_text}\n</document>\n\n<plan>\n{plan}\n</plan>\n\n{trap_block}"
               "Evaluate the plan with the rubric.")
    return _judge(CoherenceVerdict, "coherence", content, usage)


# ── metrics ─────────────────────────────────────────────────────────────────────────────

def check_claims(claims: list[Claim], plan: str, sources: dict[str, dict], document_text: str,
                 pages: dict[str, Page]) -> tuple[dict, dict]:
    """Traceability and faithfulness of the extracted claims.

    A claim counts only if its quote is in the plan, and a reference only if it is cited on
    the plan line of the quote, so the extractor cannot invent either.
    """
    document_values = text_values(document_text)
    page_values = {url: text_values(p.text) for url, p in pages.items() if p.status == "ok"}
    items, figures, unquoted = [], [], 0
    for claim in claims:
        line = locate(claim.quote, plan)
        if line is None:
            unquoted += 1
            continue
        refs = [r for r in dict.fromkeys(claim.refs) if r in markers(line)]
        cited = [sources[r] for r in refs if r in sources]
        valid = [s for s in cited if s["kind"] == "document" or (s["kind"] == "web" and pages[s["url"]].valid)]
        items.append({"quote": claim.quote, "refs": refs, "valid_refs": len(valid), "traced": bool(valid)})

        web = [s["url"] for s in cited if s["kind"] == "web"]
        for figure in claim.figures:
            if not figure_values(figure):
                status = "no number"
            elif figure_in(figure, document_values):
                status = "document"
            elif any(figure_in(figure, page_values.get(u, [])) for u in web):
                status = "source"
            elif any(pages[u].status in ("unreadable", "unchecked") for u in web):
                status = "unverifiable"  # a cited page exists but could not be read
            else:
                status = "not found"
            figures.append({"figure": figure, "quote": claim.quote, "status": status})

    traced = sum(i["traced"] for i in items)
    traceability = {"score": traced / len(items) if items else None, "claims": len(items), "traced": traced,
                    "unquoted": unquoted, "items": items}
    count = {s: sum(f["status"] == s for f in figures) for s in ("document", "source", "not found", "unverifiable")}
    checked = count["document"] + count["source"] + count["not found"]
    faithfulness = {"score": (checked - count["not found"]) / checked if checked else None, "checked": checked,
                    "matched": checked - count["not found"], "not_found": count["not found"],
                    "unverifiable": count["unverifiable"], "items": figures}
    return traceability, faithfulness


def cost(run: dict) -> dict:
    tokens = {model: {k: u.get(k, 0) for k in ("input_tokens", "output_tokens", "total_tokens")}
              for model, u in (run.get("tokens") or {}).items()}
    return {"tokens": tokens, "total_tokens": sum(t["total_tokens"] for t in tokens.values()),
            "seconds": run.get("seconds")}


def evaluate(out_dir: str | Path, document_text: str, trap: str | None = None, fetch: bool = True) -> dict:
    """Score the plan in out_dir and write out_dir/metrics.json. trap: the case's trap segment, if any."""
    out_dir = Path(out_dir)
    run = json.loads((out_dir / "run.json").read_text())
    path = out_dir / "blueprint.md"
    metrics = {"system": run.get("system", "multi_agent"), "status": run.get("status"),
               "error": run.get("error"), "cost": cost(run), "trap": {"applies": bool(trap), "segment": trap}}
    if run.get("status") != "done" or not path.exists():
        metrics["error"] = metrics["error"] or "No plan to evaluate."
    else:
        markdown = path.read_text()
        plan, sources = plan_text(markdown), parse_sources(markdown)
        usage = UsageMetadataCallbackHandler()
        claims = extract_claims(plan, usage)
        pages = fetch_pages([s["url"] for s in sources.values() if s["kind"] == "web"], fetch)
        metrics["traceability"], metrics["faithfulness"] = check_claims(claims, plan, sources, document_text, pages)
        metrics["sources"] = [{"number": n, **s, "status": pages[s["url"]].status if s["url"] else s["kind"],
                               "detail": pages[s["url"]].detail if s["url"] else "",
                               "valid": s["kind"] == "document" or (s["kind"] == "web" and pages[s["url"]].valid)}
                              for n, s in sources.items()]
        verdict = judge_coherence(document_text, plan, trap, usage)
        metrics["coherence"] = {
            "strategy_vs_analysis": {"score": verdict.strategy_vs_analysis, "reason": verdict.strategy_reason},
            "campaign_vs_strategy": {"score": verdict.campaign_vs_strategy, "reason": verdict.campaign_reason}}
        metrics["trap"].update(target=verdict.target,
                               avoided=None if not trap or verdict.targets_trap is None else not verdict.targets_trap)
        metrics["eval_tokens"] = cost({"tokens": {m: dict(u) for m, u in usage.usage_metadata.items()}})["tokens"]
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    return metrics


def load_metrics(out_dir: str | Path) -> dict | None:
    path = Path(out_dir) / "metrics.json"
    return json.loads(path.read_text()) if path.exists() else None


def scores(metrics: dict | None) -> dict:
    """The headline numbers of one evaluated plan (None when not available)."""
    m = metrics or {}
    coherence = m.get("coherence") or {}
    return {
        "traceability": (m.get("traceability") or {}).get("score"),
        "faithfulness": (m.get("faithfulness") or {}).get("score"),
        "coherence_strategy": (coherence.get("strategy_vs_analysis") or {}).get("score"),
        "coherence_campaign": (coherence.get("campaign_vs_strategy") or {}).get("score"),
        "trap_avoided": (m.get("trap") or {}).get("avoided"),
        "tokens": (m.get("cost") or {}).get("total_tokens"),
        "seconds": (m.get("cost") or {}).get("seconds"),
    }
