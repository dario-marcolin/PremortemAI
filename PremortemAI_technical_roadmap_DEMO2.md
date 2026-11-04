#uni/doubledegreeAixMarseille/Marketing 

> Multi-agent adviser for product launch planning.
> Target: technical draft by **8 November 2026**.
> Version 2 (21 Oct): customer data injection moved to the Bonus section.

---

## 1. Scope of the first version (v1)

**In scope**

- The company uploads **one document** (PDF, Word, PowerPoint, Markdown or TXT) describing the company and the product.
- The full document text is placed **directly into the LLM context**. No chunking, no embeddings, no vector store.
- Three specialized agents (**Analyst, Strategist, Creative**) plus a **Validator** and a **human approval** step, orchestrated with **LangGraph**.
- The Analyst uses a **web search tool** for competitors, market context and segment evidence, always with sources.
- The output is a **Launch Blueprint** (Markdown, optionally PDF) with evidence, segments, strategy, campaign, sources and validation notes.
- An **evaluation** comparing the multi-agent system against a single-prompt baseline.
- A **Streamlit UI** as the last step.

**Out of scope for v1 (see Section 6, Bonus)**

- Customer data upload and quantitative segmentation (clustering).
- RAG over company documents, launch memory across launches, multiple documents, image generation, deployment.

**Why customer data is out of v1:** our target users are companies launching a new product, often without an existing customer base, and we have no realistic test database. The architecture keeps the hooks so it can be added later without rewriting the graph (Section 6.1).

---

## 2. Architecture overview

```
               ┌──────────────────────┐
  document ──► │ Ingestion            │  parser.py → brief_extractor.py
               │ text + CompanyBrief  │
               └──────────┬───────────┘
                          ▼
               ┌──────────────────────┐      ┌──────────────────────────┐
               │ Analyst (subgraph)   │ ◄──► │ Tools                    │
               │ ReAct loop           │      │ web_search               │
               └──────────┬───────────┘      │ (bonus: customer tools)  │
                          ▼                  └──────────────────────────┘
               ┌──────────────────────┐
               │ Validator (analysis) │
               └──────────┬───────────┘
                          ▼
               ┌──────────────────────┐
               │ Strategist           │ ◄──┐ revise (max 2 loops)
               └──────────┬───────────┘    │
                          ▼                │
               ┌──────────────────────┐    │
               │ Validator (strategy) │ ───┘
               └──────────┬───────────┘
                          ▼
               ┌──────────────────────┐
               │ Human approval       │  LangGraph interrupt()
               └──────────┬───────────┘
                          ▼
               ┌──────────────────────┐
               │ Creative             │ ◄──┐ revise (max 2 loops)
               └──────────┬───────────┘    │
                          ▼                │
               ┌──────────────────────┐    │
               │ Validator (campaign) │ ───┘
               └──────────┬───────────┘
                          ▼
               ┌──────────────────────┐
               │ Launch Blueprint     │  Markdown / PDF
               └──────────────────────┘
```

### Core design principles

1. **Shared state.** All agents read from and write to one typed object (`LaunchState`). No agent works in isolation.
2. **Structured outputs.** Every agent returns a Pydantic model, never free text. This is what makes validation possible.
3. **Every claim has a source.** Facts come from the uploaded document or from web search, and carry a source id. The LLM must not present invented figures as facts.
4. **Technical decisions in code, domain decisions in the LLM.** Rules, limits and routing are Python; interpretation and strategy are the LLM's job.
5. **Bounded loops.** Every revision loop has a maximum number of iterations.
6. **Extensible tool list.** The Analyst's tools are built by a function, so new tools (customer data, market sizing) can be added later without touching the graph.

### Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Data and LLM ecosystem |
| LLM | Frontier model via API (provider-agnostic, via `init_chat_model`) | Easy to swap model |
| Orchestration | LangGraph | Loops, conditional edges, `interrupt()` for human-in-the-loop, checkpointing |
| Schemas | Pydantic v2 | Structured outputs and validation |
| Document parsing | MarkItDown | One call for PDF, DOCX, PPTX |
| Web search | Tavily (`langchain-tavily`) | Returns sources and URLs |
| Output | Jinja2 | Blueprint template rendered from the state |
| Tracing (optional) | LangSmith or Langfuse | Traceability of every call |
| Tests | pytest | Deterministic parts (parser, rules, routing) |
| UI | Streamlit | Fast to build, supports file upload and buttons |

---

## 3. Repository structure (v1)

```
premortem-ai/
├── README.md
├── pyproject.toml                  # or requirements.txt
├── .env.example
├── .gitignore
│
├── premortem/
│   ├── __init__.py
│   ├── config.py                   # settings, model names, thresholds
│   ├── llm.py                      # LLM factory
│   ├── schemas.py                  # all Pydantic models
│   ├── state.py                    # LaunchState, AnalystState
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── parser.py               # file → text
│   │   └── brief_extractor.py      # text → CompanyBrief
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   └── web_search.py           # Tavily wrapper
│   │
│   ├── prompts/
│   │   ├── brief_extractor.md
│   │   ├── analyst.md
│   │   ├── strategist.md
│   │   ├── creative.md
│   │   └── judge.md
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── analyst.py              # ReAct subgraph
│   │   ├── strategist.py
│   │   ├── creative.py
│   │   └── validator.py            # node wrapper: rules + judge
│   │
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── rules.py                # deterministic checks
│   │   └── judge.py                # LLM-as-judge with rubric
│   │
│   ├── graph.py                    # main LangGraph
│   │
│   └── output/
│       ├── __init__.py
│       ├── blueprint.py            # state → LaunchBlueprint → Markdown
│       └── templates/
│           └── blueprint.md.j2
│
├── data/
│   └── demo/
│       └── demo_company.pdf        # sample company/product document
│
├── scripts/
│   └── run_cli.py                  # run the full pipeline from terminal
│
├── eval/
│   ├── __init__.py
│   ├── cases/                      # 3 to 5 test product documents
│   ├── baseline.py                 # single-prompt baseline
│   ├── metrics.py                  # evaluation metrics
│   └── run_eval.py                 # runs both systems, writes report
│
├── tests/
│   ├── test_parser.py
│   ├── test_rules.py
│   └── test_graph_smoke.py
│
├── outputs/                        # generated blueprints (gitignored)
│
└── app.py                          # Streamlit UI (last step)
```

---

## 4. Roadmap, phase by phase

Every phase lists the files to create **in order**, what each file contains, and a **definition of done**. Each phase ends with something that runs.

### ✅Phase 0: Project setup
**Dates:** 21 to 22 Oct

| #   | File                  | Content                                                                                                                                                                                                                                |
| --- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0.1 | `pyproject.toml`      | Dependencies: `langgraph`, `langchain`, `langchain-core`, the provider package (e.g. `langchain-anthropic` or `langchain-openai`), `langchain-tavily`, `pydantic`, `markitdown[all]`, `jinja2`, `python-dotenv`, `pytest`, `streamlit` |
| 0.2 | `.env.example`        | `LLM_MODEL=`, `LLM_API_KEY=`, `TAVILY_API_KEY=`, optional `LANGSMITH_API_KEY=`                                                                                                                                                         |
| 0.3 | `.gitignore`          | `.env`, `outputs/`, `__pycache__/`                                                                                                                                                                                                     |
| 0.4 | `premortem/config.py` | Loads `.env`. Constants: model name, temperature, `MAX_REVISIONS = 2`, `MAX_SEARCH_RESULTS = 5`, `ANALYST_RECURSION_LIMIT = 15`, `DOC_TOKEN_BUDGET = 60_000`                                                                           |
| 0.5 | `premortem/llm.py`    | `get_llm(temperature=...)` built with `init_chat_model`, so the provider can change from config only                                                                                                                                   |
| 0.6 | `README.md`           | Project goal, setup instructions, how to run                                                                                                                                                                                           |

**Done when:** `python -c "from premortem.llm import get_llm; print(get_llm().invoke('hello'))"` returns a response.

---

### ✅Phase 1: Schemas and state
**Dates:** 22 Oct

This is the most important design phase. Every later file depends on it.

**1.1 `premortem/schemas.py`**

```python
class CompanyBrief(BaseModel):
    company_name: str
    company_description: str
    product_name: str
    product_description: str
    target_country: str
    price_hint: str | None
    known_competitors: list[str]
    stated_goals: list[str]
    missing_info: list[str]          # what the document does not say

class Source(BaseModel):
    id: str                          # e.g. "S1"
    kind: Literal["document", "web"] # bonus: "customer_data"
    reference: str                   # URL or file name

class Competitor(BaseModel):
    name: str
    positioning: str
    price_level: str | None
    source_ids: list[str]

class MarketSegment(BaseModel):
    segment_id: str                  # e.g. "SEG1"
    label: str                       # e.g. "Young urban professionals"
    description: str
    needs: list[str]
    estimated_size: str | None       # only if a source gives it
    source_ids: list[str]

class Analysis(BaseModel):
    market_overview: str
    competitors: list[Competitor]
    customer_needs: list[str]
    segments: list[MarketSegment]
    data_quality_notes: list[str]    # gaps, weak sources, assumptions
    sources: list[Source]

class Strategy(BaseModel):
    target_segment_id: str
    target_description: str
    positioning_statement: str
    value_proposition: str
    pricing_direction: str
    channels: list[str]
    rationale: str
    supporting_source_ids: list[str]

class CampaignMessage(BaseModel):
    channel: str
    headline: str
    body: str

class Campaign(BaseModel):
    concept: str
    tagline: str
    key_messages: list[CampaignMessage]
    content_ideas: list[str]
    visual_direction: str            # text description only in v1

class ValidationIssue(BaseModel):
    severity: Literal["blocking", "warning"]
    check: str
    message: str

class ValidationResult(BaseModel):
    stage: Literal["analysis", "strategy", "campaign"]
    passed: bool
    issues: list[ValidationIssue]
```

Segments in v1 are **qualitative**: they come from the document and from web sources, not from clustering. `estimated_size` is filled only when a source states it, and is otherwise left empty and flagged in `data_quality_notes`.

**1.2 `premortem/state.py`**

```python
class LaunchState(TypedDict):
    document_text: str
    brief: CompanyBrief | None
    analysis: Analysis | None
    strategy: Strategy | None
    campaign: Campaign | None
    validations: list[ValidationResult]   # full history, for the blueprint
    strategy_revisions: int
    campaign_revisions: int
    human_feedback: str | None
```

Plus `AnalystState(MessagesState)` with `brief`, `document_text`, `analysis`.

**Done when:** all models can be instantiated with dummy data in a Python shell.

---

### ✅Phase 2: Ingestion
**Dates:** 23 Oct

| # | File | Content |
|---|---|---|
| 2.1 | `premortem/ingestion/parser.py` | `parse_document(path) -> str` using MarkItDown. Checks the file extension against an allowed list. Truncates with a warning if the text exceeds `DOC_TOKEN_BUDGET` |
| 2.2 | `premortem/prompts/brief_extractor.md` | Instructions: extract only what is stated, never invent, list missing information |
| 2.3 | `premortem/ingestion/brief_extractor.py` | `extract_brief(text) -> CompanyBrief` with `llm.with_structured_output(CompanyBrief)` |
| 2.4 | `data/demo/demo_company.pdf` | A realistic 3 to 5 page fictional company and product description. Include some market figures (e.g. size of two or three target groups) so the agents have numbers to cite |
| 2.5 | `tests/test_parser.py` | Parses a small PDF and DOCX fixture |

**Done when:** `extract_brief(parse_document("data/demo/demo_company.pdf"))` prints a correct `CompanyBrief`.

---

### 🟡Phase 3: Customer data injection
**Moved to Bonus 6.1.** Not part of v1. The phase number is kept so references in earlier discussions stay valid.

---

### ✅Phase 4: Web search tool
**Dates:** 24 Oct

**4.1 `premortem/tools/web_search.py`**

A `@tool` wrapper around Tavily:

```python
@tool
def web_search(query: str) -> list[dict]:
    """Search the web for market, competitor or consumer information.
    Use precise queries that include the product category and the
    target country. Returns up to 5 results with title, url and snippet."""
```

Rules for writing tools (they also apply to any bonus tool added later):

- The **docstring is the tool's prompt**. It is the only thing the LLM reads to decide when to call it.
- Return **compact results**, never full pages.
- Return errors as data (`{"error": "..."}`) instead of raising, so the LLM can correct itself.

**Done when:** `web_search.invoke({"query": "plant-based snacks market France"})` returns results with URLs.

---

### ✅Phase 5: Analyst agent (ReAct subgraph)
**Dates:** 25 to 27 Oct

**5.1 `premortem/prompts/analyst.md`**

- Role: market and customer analyst.
- Procedure: read the brief and the full document first; then use `web_search` for competitors, market context and evidence about possible segments in the target country.
- Constraints: never invent numbers, cite every claim with a source id, leave `estimated_size` empty when no source gives it, list gaps in `data_quality_notes`.

**5.2 `premortem/agents/analyst.py`**

```
analyst_llm ──(tool call)──► tools (ToolNode) ──► analyst_llm
     │
     └──(no tool call)──► analyst_report ──► END
```

- `get_analyst_tools()`: returns `[web_search]` in v1. This is the single place where bonus tools will be added later.
- `build_analyst()`: builds and compiles the subgraph.
- `analyst_llm`: invokes `llm.bind_tools(tools)` with the system prompt, the brief, the full document text and the message history.
- `tools`: LangGraph `ToolNode(tools)`.
- Conditional edge with `tools_condition`: tool call goes to `tools`, otherwise to `analyst_report`.
- `analyst_report`: one final call with `with_structured_output(Analysis)` that turns the conversation and tool results into the structured analysis, with sources numbered as `S1`, `S2`, ...
- Safety: `ANALYST_RECURSION_LIMIT` to avoid infinite tool loops.

**Done when:** running the subgraph on the demo document produces an `Analysis` with at least 3 competitors and 2 segments, every one with a valid source id.

---

### ✅Phase 6: Strategist and Creative agents
**Dates:** 28 to 29 Oct

| # | File | Content |
|---|---|---|
| 6.1 | `premortem/prompts/strategist.md` | STP logic (segmentation, targeting, positioning). Must choose a `target_segment_id` that exists in the analysis, justify it with source ids, and take into account any validation issues or human feedback present in the state |
| 6.2 | `premortem/agents/strategist.py` | Node `strategist(state) -> {"strategy": ...}` with `with_structured_output(Strategy)`. If previous validation issues exist, they are injected into the prompt ("Revise the strategy. Issues: ...") and `strategy_revisions` is incremented |
| 6.3 | `premortem/prompts/creative.md` | Turn the approved strategy into a campaign. Every message must reflect the positioning and the chosen channels |
| 6.4 | `premortem/agents/creative.py` | Node `creative(state) -> {"campaign": ...}` with `with_structured_output(Campaign)`. Same revision logic |

**Done when:** a manual chain `analysis → strategist → creative` produces coherent outputs.

---

### ✅Phase 7: Validator
**Dates:** 30 to 31 Oct

**7.1 `premortem/validation/rules.py`**: deterministic checks, pure Python, fully testable.

| Stage | Check | Severity |
|---|---|---|
| analysis | every competitor and segment has at least one source | warning |
| analysis | every `source_ids` entry exists in `sources` | warning |
| strategy | `target_segment_id` exists in the analysis | blocking |
| strategy | every `supporting_source_ids` entry exists | blocking |
| strategy | the target segment has an `estimated_size`; if not, flag it | warning |
| campaign | every message channel is in `strategy.channels` | blocking |
| campaign | at least one key message per channel | warning |

**7.2 `premortem/prompts/judge.md`** and **`premortem/validation/judge.py`**

LLM-as-judge with an explicit rubric per stage. This is where most of the "challenge" happens in v1. For example, for strategy:
- Is the chosen segment large and accessible enough, according to the evidence in the analysis?
- Is the positioning consistent with the needs of the target segment?
- Is the pricing direction consistent with competitor price levels?
- Is the value proposition differentiated from the competitors?

The judge must quote the analysis field it relies on, so its objections are traceable. Returns a list of `ValidationIssue`.

**7.3 `premortem/agents/validator.py`**

`make_validator(stage)` returns a node that runs rules first, then the judge, and appends a `ValidationResult` to `validations`. The decision to loop back uses only **blocking** issues.

**7.4 `tests/test_rules.py`**: one test per rule, with hand-made objects.

**Done when:** a strategy targeting a segment that the analysis describes as very small (from the figures in the demo document) is rejected by the judge with a blocking issue.

---

### ✅Phase 8: Main graph and human-in-the-loop
**Dates:** 1 to 2 Nov

**8.1 `premortem/graph.py`**

```python
def build_graph():
    g = StateGraph(LaunchState)
    g.add_node("extract_brief", extract_brief_node)
    g.add_node("analyst", build_analyst())
    g.add_node("validate_analysis", make_validator("analysis"))
    g.add_node("strategist", strategist)
    g.add_node("validate_strategy", make_validator("strategy"))
    g.add_node("human_approval", human_approval)
    g.add_node("creative", creative)
    g.add_node("validate_campaign", make_validator("campaign"))
    g.add_node("blueprint", build_blueprint_node)

    g.set_entry_point("extract_brief")
    g.add_edge("extract_brief", "analyst")
    g.add_edge("analyst", "validate_analysis")
    g.add_edge("validate_analysis", "strategist")       # analysis issues are warnings only
    g.add_edge("strategist", "validate_strategy")
    g.add_conditional_edges("validate_strategy", route_strategy,
                            {"revise": "strategist", "ok": "human_approval"})
    g.add_conditional_edges("human_approval", route_human,
                            {"approved": "creative", "rejected": "strategist"})
    g.add_edge("creative", "validate_campaign")
    g.add_conditional_edges("validate_campaign", route_campaign,
                            {"revise": "creative", "ok": "blueprint"})
    g.add_edge("blueprint", END)
    return g.compile(checkpointer=MemorySaver())
```

- `route_strategy`: `"revise"` if there are blocking issues **and** `strategy_revisions < MAX_REVISIONS`, otherwise `"ok"`. If the maximum is reached, unresolved issues are carried to the human and the blueprint.
- `human_approval`: calls `interrupt({...strategy, validation issues...})`. The graph pauses and saves its state. It resumes with `Command(resume={"approved": bool, "feedback": str})`. Rejection writes `human_feedback` into the state and routes back to the Strategist.
- Each run uses a `thread_id` in the config, so the paused state can be resumed.

**8.2 `scripts/run_cli.py`**

Terminal runner, used before the UI exists:

```
python scripts/run_cli.py --doc data/demo/demo_company.pdf
```

It streams the progress of each node, prints the strategy at the interrupt, asks `Approve? [y/n/feedback]` with `input()`, resumes the graph, and saves the final blueprint.

**8.3 `tests/test_graph_smoke.py`**

End-to-end run on the demo case with a fake LLM or a cheap model, auto-approving at the interrupt. Checks that the run reaches `END` and that all state fields are filled.

**Done when:** the full pipeline runs from the terminal, including one revision loop and the human approval pause.

---

### ✅Phase 9: Launch Blueprint output
**Dates:** 3 Nov

| # | File | Content |
|---|---|---|
| 9.1 | `premortem/output/templates/blueprint.md.j2` | Jinja2 template. Sections: Executive summary, Company brief and missing information, Market and competitors, Segments (table), Strategy, Campaign, Validation log, Sources |
| 9.2 | `premortem/output/blueprint.py` | `render_blueprint(state) -> str` and `save_blueprint(state, path)`. Resolves every source id into a numbered reference list. Optional PDF export (e.g. via `markdown` + `weasyprint`) |

The executive summary is the only part written by an LLM. Everything else is rendered **directly from the state**, so the blueprint cannot drift from what the agents actually decided.

**Done when:** `outputs/<run_id>/blueprint.md` is complete and readable.

---

### Phase 10: Evaluation
**Dates:** 4 to 5 Nov

This phase answers the research question: *can coordinated specialized agents produce a launch plan that is more coherent, traceable and reusable than isolated AI prompts?*

| # | File | Content |
|---|---|---|
| 10.1 | `eval/cases/` | 3 to 5 fictional product documents. Include at least one "trap" case: the document states that the most enthusiastic group is a very small share of the market |
| 10.2 | `eval/baseline.py` | Same model, same document, **one single prompt** asking for a full launch plan (no tools, no validator) |
| 10.3 | `eval/metrics.py` | Metrics (see below) |
| 10.4 | `eval/run_eval.py` | Runs baseline and multi-agent on every case and writes `eval/report.md` with a comparison table |

| Metric | How it is measured |
|---|---|
| Traceability | % of claims with at least one valid source |
| Faithfulness | figures in the output match the document or a cited source (checked per figure) |
| Internal coherence | LLM judge score (1 to 5) on strategy vs analysis and campaign vs strategy, with a fixed rubric |
| Trap detection | the system avoids targeting the tiny segment (yes/no) |
| Human rating | the team blind-rates both outputs on a short rubric |
| Cost and latency | tokens and seconds per run |

**Done when:** `eval/report.md` exists with results for all cases.

---

### Phase 11: User interface (Streamlit)
**Dates:** 6 to 7 Nov

**11.1 `app.py`**

| Screen element | Behaviour |
|---|---|
| Upload area | Document uploader (PDF, DOCX, PPTX, MD, TXT). Designed as a "company data" area so more file types can be added later (Bonus 6.1) |
| Run button | Creates a `thread_id`, starts the graph with `app.stream(...)` |
| Progress panel | One status line per node (Analyst, Validator, Strategist...), updated as the stream advances. Expandable view of the searches made by the Analyst |
| Approval panel | Shown when the graph hits `interrupt()`. Displays the strategy and the validation issues. Buttons: **Approve**, **Reject with feedback** (text area). Resumes with `Command(resume=...)` |
| Result panel | Rendered blueprint, segment table, validation log, download buttons (Markdown, PDF) |

Implementation notes:

- Keep the compiled graph and the `thread_id` in `st.session_state`, because Streamlit re-runs the script on every interaction.
- Save uploaded files to a temporary folder and pass their **paths** to the parser.
- Use `st.status` or `st.expander` to show the progress of each node.

**Done when:** a person who has never seen the code can upload the demo document, approve the strategy and download the blueprint.

---

### Buffer and technical draft
**Date:** 8 Nov

- Fix bugs, freeze the demo case, record a short demo video as backup.
- Update `README.md` with the architecture diagram, how to run, and evaluation results.
- Update slide 3 of the project vision deck with the final stack.

---

## 5. Timeline summary

| Dates | Phase | Deliverable |
|---|---|---|
| 21 to 22 Oct | 0, 1 | Repo, config, schemas, state |
| 23 Oct | 2 | Document parsing, brief extraction, demo document |
| 24 Oct | 4 | Web search tool |
| 25 to 27 Oct | 5 | Analyst ReAct subgraph |
| 28 to 29 Oct | 6 | Strategist and Creative |
| 30 to 31 Oct | 7 | Validator (rules + judge) |
| 1 to 2 Nov | 8 | Main graph, human-in-the-loop, CLI |
| 3 Nov | 9 | Launch Blueprint |
| 4 to 5 Nov | 10 | Evaluation vs baseline |
| 6 to 7 Nov | 11 | Streamlit UI |
| 8 Nov | Buffer | Technical draft submitted |

Removing customer data frees about two days, which are given to the Analyst (the hardest agent) and the Strategist/Creative prompts.

**If time runs short:** phases 0 to 9 are the minimum for a credible technical draft (a working pipeline from the terminal). The UI can be presented as a mock-up, and the evaluation can be reduced to one or two cases.

### Suggested split between two people

| Person A (graph and validation) | Person B (agents and prompts) |
|---|---|
| Phase 4: web search tool | Phase 2: parser, brief extraction, demo document |
| Phase 5: Analyst subgraph (code) | Phase 5: Analyst prompt |
| Phase 7.1: deterministic rules | Phase 6: Strategist and Creative |
| Phase 8: routing and CLI | Phase 7.2: LLM judge and rubric |
| Phase 10: metrics and eval runner | Phase 9: blueprint template, eval cases |
| Phase 11: UI (shared) | Phase 11: UI (shared) |

Phases 1 and 8 are designed together, because they define the contracts between all components.

---

## 6. Bonus concepts (after the draft)

These are kept out of v1 on purpose. Each one builds on the v1 architecture without changing it.

### 6.1 Company data layer: documents and customer data

**Goal:** the company can upload any mix of documents and data files from one "company data" area, and the agents use all of it.

**Key design rule: documents and tables follow two different paths.**

```
                      ┌─────────────────────┐
  company uploads ──► │ file router         │
                      └──────┬───────┬──────┘
                 documents   │       │   tables (CSV, XLSX)
                             ▼       ▼
                ┌────────────────┐ ┌──────────────────────┐
                │ RAG            │ │ Analysis tools       │
                │ chunk, embed,  │ │ pandas, scikit-learn │
                │ vector store   │ │ (computed numbers)   │
                └───────┬────────┘ └──────────┬───────────┘
                        └─────────┬───────────┘
                                  ▼
                       tools bound to the Analyst
```

- **Documents → RAG.** Chunk (e.g. 800 tokens with overlap), embed, store in Chroma or pgvector, expose a `search_company_docs(query)` tool. Good for finding *text*.
- **Tables → analysis tools.** RAG is the wrong tool for tables: it retrieves a few similar rows and cannot count, average or cluster the whole dataset. Customer data must be computed with code.

**Customer analysis tools** (this is the former Phase 3 and the customer part of Phase 4):

| Tool | LLM-visible arguments | Returns |
|---|---|---|
| `profile_customers` | none | number of customers, columns and types, descriptive statistics, missing values |
| `segment_customers` | `features: list[str]` | best `k` by silhouette score, per segment: size, share, mean of every feature |
| `compare_segments` | `metric: str` | segments ranked by a chosen metric, with share and value contribution |

- The tools receive the file path through LangGraph's `InjectedState`, so the path and the raw rows are **hidden from the LLM**.
- The LLM only chooses business-relevant features; the number of clusters is chosen by code.
- New validation rule: target segment share of customers above a threshold (blocking).
- Wording: clustering gives the **share of the customer base**, not the share of the market.
- A data template (`customer_template.csv`, `customer_schema.md`) and a loader that validates columns, with an LLM-assisted column mapping as a later step for arbitrary CSVs.
- A test dataset can be adapted from a public one (e.g. Kaggle "Customer Personality Analysis").

**Hooks already present in v1:** `get_analyst_tools()` is the single place to add these tools, `Source.kind` can take `"customer_data"`, `MarketSegment` can gain a `share_of_customers` field, and the UI upload area is already named "company data".

**New files:** `premortem/ingestion/router.py`, `premortem/ingestion/customer_loader.py`, `premortem/rag/indexer.py`, `premortem/rag/retriever.py`, `premortem/tools/doc_search.py`, `premortem/tools/customer_tools.py`, `data/customer_template.csv`, `data/customer_schema.md`, `tests/test_customer_tools.py`.

### 6.2 Launch memory
- **Why:** the second launch should start from what was learned in the first one.
- **How:** after each launch, store decisions, human feedback and (later) real results in a database (SQLite, then Postgres). At the start of a new launch, retrieve similar past launches (by product category and segment) and inject them into the Strategist's context. Can reuse the vector store from 6.1 for past blueprints.
- **Wording:** the system **retrieves** past knowledge, it does not "learn" in the sense of retraining a model.
- **New files:** `premortem/memory/models.py`, `premortem/memory/store.py`, `premortem/memory/retrieve.py`.

### 6.3 Market sizing
- A tool that estimates segment and market size from public statistics (national statistics offices, Eurostat), so `estimated_size` is computed rather than only quoted. This also adds a quantitative layer that works for companies without customers.

### 6.4 Richer Creative output
- Image generation for moodboards from `visual_direction`.
- Channel-specific content (post drafts, email copy, ad variants).

### 6.5 Parallel analysis
- Split the Analyst into sub-agents (competitor research, segment research, customer analytics) that run in parallel with LangGraph fan-out and fan-in.

### 6.6 Observability and robustness
- Full tracing with LangSmith or Langfuse, cost tracking per run.
- Persistent checkpointer (SQLite or Postgres) so a paused run survives a restart.
- Retry and fallback model on API errors.

### 6.7 Deployment
- Docker image, deployment of the Streamlit app, simple authentication.
### 6.8 Pricing Optimization

### 6.9 Expand [[PremortemAI_technical_roadmap_DEMO2#✅Phase 4 Web search tool|web search tool]] capabilities 
- Voglio cercare meglio i prezzi 

---

## 7. Key risks and mitigations

| Risk                                                        | Mitigation                                                                                                              |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| The LLM invents figures                                     | Every claim needs a source id; faithfulness check in evaluation; `estimated_size` empty unless sourced                  |
| No quantitative layer in v1 (Quantitative Marketing course) | Demo document includes market figures; market sizing (6.3) and customer analytics (6.1) presented as planned extensions |
| Validator too weak without computed numbers                 | Judge rubric with explicit questions, judge must quote the analysis field it relies on                                  |
| Infinite tool or revision loops                             | `ANALYST_RECURSION_LIMIT` on the Analyst, `MAX_REVISIONS` on revision loops                                             |
| Web search returns irrelevant results                       | Limit to 5 results, require sources, warnings from the Validator                                                        |
| API costs during development                                | Cheap model for development and tests, frontier model for demo and evaluation                                           |
| Team members blocked on each other                          | Freeze `schemas.py` and `state.py` in Phase 1; they are the contract                                                    |
|                                                             |                                                                                                                         |
# IDEE MIE
- [ ] Approfondire ricerca analyst
- [ ] Preparazione UI web con formato HTML