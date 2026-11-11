#uni/doubledegreeAixMarseille/Marketing

> Multi-agent adviser for product launch planning.
> Final roadmap, from the v1 pipeline to the delivered project.
> Delivery: **week of 16 November 2026** (exact date to confirm). Version 2, 10 Nov 2026.
> Follows `PremortemAI_technical_roadmap_DEMO2.md` (phases 0 to 11) and the notes in `Professor notes.md`.

---

## 1. Where we start

Phases 0 to 11 are done (PR #3):

- **Pipeline.** Document → `extract_brief` → Analyst (Tavily web search) → Strategist ⇄ Validator → human approval → Creative ⇄ Validator → Launch Blueprint.
- **Interfaces.** CLI, Streamlit UI and the architecture map.
- **Evaluation harness.** Compares the pipeline with a single-prompt baseline.
- **Tests.** 139 offline tests pass.

What is still open:

| Gap | Detail |
|---|---|
| One model, one provider | `LLM_MODEL` is used by every agent, and only Anthropic is installed. `JUDGE_MODEL` is shared by the in-pipeline Validator and the evaluation metrics. |
| Not reproducible by someone else | The app needs an Anthropic key and a Tavily key in `.env`. `outputs/` is git-ignored, so no run is visible without spending credits. The README assumes `uv` is installed. |
| UI | A working control panel, not a product. Citations are numbered `[n]` with no detail on hover. Only the strategy can be reviewed. |
| Evaluation incomplete | Only 1 case of 5 has results for both systems. The others failed with error 400 when the Anthropic credits ran out (`eval/report.md`). |

---

## 2. Priorities

| Priority | Work | Phases |
|---|---|---|
| **1. Reproducibility and models** | One model per role, any provider, keys per visitor, a repo that runs from the README, saved runs | 12, 13 (and 14, the final evaluation run with the new models) |
| **2. A good UI** | A full rework: setup with your own key, a timeline of agents with a page per step, **hover citations**, saved runs, local and public modes | 15 (last phase) |
| **Bonus** | Pricing agent and a better web search tool | B1, B2: only after the Must items of Phase 15 |

Not in scope: the RAG system. Understanding the code is not a phase: the team does it anyway.

### Professor notes → plan

| Professor note | Where | Decision |
|---|---|---|
| Evaluation with cheaper models (Haiku), agents with a better model (Sonnet) | 12 | One model per role |
| Big model for the final blueprint | 12 | Opus for the executive summary |
| UI rework: precise references, hover as in Obsidian | 15 | Full UI rework, with citation cards on hover |
| Each step clickable: **we want to revise each agent result** | 15 | A page per agent, open during the run and at the end, with rounds and "What changed"; the strategy is approved or sent back (15.2, decided 11 Nov) |
| Pricing agent? | B1 (bonus) | A Pricing agent between the Analyst and the Strategist |
| Web search (Gemini, LangGraph agent tool) | B2 (bonus) | Already a LangChain tool inside the Analyst's ReAct loop (Tavily). B2 makes it better. |
| RAG system (to evaluate) | — | Not in scope |

---

## 3. Keys and providers: who pays for a run

**Two ways to run the same app:**

| Mode | Used for | LLM key | Tavily key |
|---|---|---|---|
| `local` (`PREMORTEM_MODE=local`) | **Our live demo** at the presentation, development, the evaluation | From `.env`. Ours, Anthropic, so the demo uses Claude with the best profile. The setup screen shows "Using the key from .env" and asks for nothing. | From `.env` |
| `public` (Streamlit Community Cloud) | **The professor**, after the presentation | **The visitor pastes their own key**, from any supported provider. The professor will likely use a free Gemini key and knows that free models perform worse. The key lives only in `st.session_state`: never on disk, in logs, `state.json` or `run.json`. | Ours, in Streamlit Secrets. Capped per session. |

**Where the mode is set:**

| Where | How |
|---|---|
| Local (our demo) | One line in `.env` at the repo root, next to the keys: `PREMORTEM_MODE=local` |
| Streamlit Cloud | The app's *Settings → Secrets*: `PREMORTEM_MODE = "public"` and `TAVILY_API_KEY = "tvly-..."` |
| Not set | **`public` by default.** If we forget it on Streamlit Cloud, the app still never looks for an LLM key on the server and asks the visitor for one. Locally, the only cost of forgetting it is that the setup screen asks for a key. |

**Rule:** never put an LLM key in the Streamlit Secrets. The app would use it for anyone who has the link. In `public` mode the code never reads `LLM_API_KEY` from the environment, and a test checks it.

### Any provider

The visitor can use any provider that LangChain can reach, as long as its model supports **tool calling** (the Analyst's search loop) and **structured output** (every agent returns a Pydantic model). There are two routes:

| Route | Providers | What the visitor enters |
|---|---|---|
| **Preset** | Anthropic, Google Gemini, OpenAI, Mistral, Groq, OpenRouter (one LangChain package each, all through `init_chat_model`) | The key only. The app **detects the provider from the key prefix**: `sk-ant-` → Anthropic, `AIza` → Gemini, `gsk_` → Groq, `sk-or-` → OpenRouter, any other `sk-` → OpenAI. The visitor can change it if the guess is wrong. The preset gives the model of each role. |
| **Custom (OpenAI-compatible)** | Any other service with an OpenAI-compatible API (Together, DeepSeek, a university server, a local Ollama…) | Base URL, key and model name. One model for every role, plus an optional bigger model for the blueprint summary. |

OpenRouter gives access to many vendors, including some free models, with a single key.

**Presets** (exact model names to verify in Phase 12):

| Preset | Agents and Validator | Blueprint summary | Notes |
|---|---|---|---|
| `anthropic` | Sonnet 5.5 | Opus 5.5 | Our demo, the evaluation and the saved runs |
| `gemini` | A Gemini Flash model of the free tier | The best Gemini model of the free tier | Slower because of the rate limits |
| `openai`, `mistral`, `groq`, `openrouter` | The provider's mid-size model with tool calling | The provider's largest model | Checked with `check_model` only |

**Check before running.** "Check key" sends three tiny requests: a plain call, a tool call and a structured output. If one fails, the UI says which one, in plain language (e.g. "This model cannot use tools, so the Analyst cannot search the web: choose another model"), and the run button stays disabled. Without this, a bad model would fail only after five minutes of running.

We test Anthropic and Gemini end to end. The README and the setup screen say that the other providers are supported but less tested, and that small or free models give weaker plans.

Facts to verify before Phase 12 (free tiers change often):

- **The Gemini free tier:** which models it includes and its limits per minute and per day. One run makes dozens of LLM calls, so the per-minute limit sets how long a run takes and the daily limit sets how many runs fit in a day.
- **Tool calling and structured output with Gemini**, through `langchain-google-genai`. Our prompts were tuned on Claude.
- **Free-tier data may be used by the provider.** Our demo documents are fictional, so this is fine. The setup screen says it.
- **Tavily's free plan:** about 1,000 searches per month at the time of writing. One run uses a few dozen.
- A key pasted into the public app passes through the Streamlit server and our code (over HTTPS). The README says so. Anyone who prefers not to paste a key can run the app locally.

With no LLM key, the visitor can still open the saved runs. If the Tavily quota is used up, the pipeline still runs: the Analyst works from the document only, and the UI shows a warning.

---

## 4. Roadmap, phase by phase

Branch per phase, as before: `phase-<n>/<name>`. Notes for the team go in `docs/devlog/<date>.md`.

### Phase 12: Models per role, any provider, keys per run
**Dates:** 11 to 12 Nov · **Branch:** `phase-12/models-and-keys`

Settings are module constants read from `.env` at import. That cannot support a different key and provider for each visitor, so the settings move to a per-run object.

| # | File | Content |
|---|---|---|
| 12.1 | `premortem/config.py` | `RunSettings` dataclass: `provider`, `llm_api_key`, optional `base_url`, `tavily_api_key`, and one model per role (`brief`, `analyst`, `strategist`, `creative`, `validator`, `blueprint`). `RunSettings.from_env()` serves the CLI, the evaluation and `local` mode. `RunSettings.preset(name, key)` and `RunSettings.custom(base_url, key, model, big_model=None)` serve the UI. `PREMORTEM_MODE` chooses `local` or `public`, and is `public` when not set. |
| 12.2 | `premortem/providers.py` | The preset table (provider → `init_chat_model` prefix, models per role, rate limits) and `detect_provider(key)`. A new provider is one new row. |
| 12.3 | `premortem/llm.py` | `get_llm(role, settings)` picks the model, key and base URL. It adds `max_retries` and a LangChain `InMemoryRateLimiter` for providers with free-tier limits, so an error 429 waits and retries instead of failing the run. `check_model(settings)` runs the three checks of section 3. |
| 12.4 | graph nodes, `tools/web_search.py` | The settings travel in `config["configurable"]["settings"]`, next to the `thread_id` already there. Nodes read them with `get_config()`. The web search tool builds its client from the settings, not from a cached global. The checkpointer saves only the state, so keys are never stored. |
| 12.5 | `premortem/runner.py` | `Run(doc, settings=...)`. `run.json` records the provider and model of each role, and **never the keys**. |
| 12.6 | `pyproject.toml`, `.env.example` | Add `langchain-google-genai`, `langchain-openai` (OpenAI, OpenRouter, the custom route), `langchain-mistralai`, `langchain-groq`. Document the models per role. Add `PREMORTEM_MODE=local` to `.env.example` with a comment: "local = keys from this file (our demo); public or unset = the visitor pastes a key". |
| 12.7 | `tests/` | Each role gets its own model. Provider detection works for every key prefix. The custom route passes the base URL. A missing Tavily key gives a warning, not a crash. Keys never appear in `run.json` or `state.json`. `public` mode ignores `LLM_API_KEY`. An unset `PREMORTEM_MODE` behaves as `public`. |
| 12.8 | manual check | One full run of the demo document with the `gemini` preset: time, number of calls, any prompt or schema that failed and its fix, in the devlog. `check_model` on every other preset for which someone in the team has a key. |

Default models of the `anthropic` preset:

| Role | Model | Why |
|---|---|---|
| Brief, Analyst, Strategist, Creative | `claude-sonnet-5-5` | Professor: agents on a better model |
| Validator (in the pipeline) | `claude-sonnet-5-5` | It decides the revisions, so it is part of the system and not of the evaluation |
| Blueprint executive summary | `claude-opus-5-5` | Professor: big model for the final blueprint (one call per run) |
| Evaluation judge (`eval/metrics.py`) | `claude-haiku-5-5` | Professor: cheaper model for the evaluation |
| Baseline | same as the agents | A fair comparison |

Risk: on 25 Oct Haiku was unstable as a judge (`docs/devlog/2026-10-25.md`). Mitigation: run the Haiku judge 3 times on the demo pair and report the spread. Then keep Haiku, or document why we switch back.

**Done when:** the CLI runs with models per role on the `anthropic` and `gemini` presets, the demo document completes on `gemini`, and a test proves that two runs with different keys do not share a client.

---

### Phase 13: Reproducibility
**Dates:** 12 Nov · **Branch:** `phase-13/reproducibility`

| # | File | Content |
|---|---|---|
| 13.1 | `app.py` | A missing Tavily key no longer disables the run button (warning only). |
| 13.2 | `scripts/check_setup.py` | Checks the Python version, the keys, `check_model` on the chosen provider and one Tavily search. Prints what works and what is missing. |
| 13.3 | `examples/` | Complete saved runs **committed to the repo** (`blueprint.md`, `state.json`, `run.json`, `log.txt`): the demo document with `anthropic`, and with `gemini`. Their `metrics.json` (scored by the same judge, Haiku, with the baseline) is added in 14.2, so the Evaluation tab works on a saved run. Phase 14 adds the evaluation runs under `eval/runs/`. |
| 13.4 | `README.md` | Install `uv` (one command). Clone → `uv sync` → `.env` → `check_setup` → run. How to get a free Gemini key. Supported providers and the custom route. The two modes: where to set `PREMORTEM_MODE` (`.env` locally, *Settings → Secrets* on Streamlit Cloud) and that unset means `public`. Cost of one run and of a full evaluation, in tokens. Why the outputs change between runs: Claude 5 rejects the temperature, so the procedure is reproducible but the exact text is not. Link to this roadmap. |
| 13.5 | `requirements.txt` | Generated with `uv export`, for anyone who uses `pip`. |
| 13.6 | repo | Remove the `.archify/` build folders from git and add them to `.gitignore`. |

**Done when:** a team member clones the repo into a new folder, follows only the README, and gets a blueprint with a Gemini key.

---

### Phase 14: Final evaluation run
**Dates:** 13 Nov (it runs in the background while the UI design starts) · **Branch:** `phase-14/eval-final` · **Needs:** Anthropic credits topped up

This is the short version of the evaluation. The report covers only 1 case of 5 today, which is not enough to present.

| # | Task |
|---|---|
| 14.1 | Re-run all 5 cases with the Phase 12 models: `uv run python -m eval.run_eval`. Run the cases one by one with `--cases` so that a failure costs only one case. Commit the runs to `eval/runs/`. |
| 14.2 | **Free preset run**: the demo document with `gemini`, scored with the same metrics. It shows the quality gap of free models with numbers. Score `examples/demo_anthropic` and `examples/demo_gemini` with the Haiku judge (anthropic preset) and the baseline, and commit their `metrics.json` and `baseline/`. |
| 14.3 | Blind rating of all pairs (`eval/rating/`), then `eval/findings.md` (5 to 10 lines, including where the baseline wins), then `--report-only`. |
| 14.4 | `eval/results.json` holds everything the evaluation page of the UI (15.3 D2) shows: the models of both systems and the judge, the 3 judge runs per plan (mean and spread), the `gemini` run of 14.2, and the blind ratings. The UI reads this file only; it never re-runs the evaluation. |

Rule from the devlog: every claim of an advantage needs a case and a metric that can show it. Report ties and losses as they are.

**Done when:** `eval/report.md` has results for every case, and `eval/findings.md` exists.

---

### Phase 15: User interface rework
**Dates:** design 13 Nov · build 14 to 18 Nov · **Branch:** `phase-15/ui`

The last phase, and the one the professor sees first. Today's UI is a working control panel: a run log, one approval panel and four result tabs. The rework turns it into a product: someone who has never seen the project understands what each agent did, can check every claim and can steer every step.

#### 15.1 Who it is for and what "good" means

**Primary user:** the professor, a marketing expert, not a developer. They open a link, use their own key and want to judge the quality of the reasoning.

| Principle | What it means in the UI |
|---|---|
| **Show the work, not only the result** | Each agent has its own page: what it read, what it searched and what it decided. |
| **Every claim can be checked in one gesture** | Hover over a citation to see the source; click it to open the source. |
| **The human is in control** | Every reviewed step can be approved or sent back with feedback, and the next round shows what changed. |
| **Never a silent wait** | While a step runs, the UI says what is happening now (e.g. "Analyst · searching 'protein crisps brands France'"), the time elapsed and the step's progress. |
| **Zero setup** | Open the link, paste a key, choose a sample document, run. Or open a saved run with no key at all. |
| **Honest about limits** | Free models are slower and weaker. A step that hit its revision limit is marked. A missing figure says "not found", never a guess. |

#### 15.2 Graph change: a review of every agent result

**Decision, 11 Nov: not built.** The team's reading of the professor's note is that each agent's result
must be open to inspection during the run and at the end. The page per agent (15.4) covers it: the
timeline opens any step at any time, with its rounds, "What changed" and the Validator's issues, on
live and saved runs alike. The strategy, the key decision, keeps its review (approve, or send back
with feedback). The plan below is kept for reference.

The professor's main request. The clickable timeline is built on it.

| # | File | Content |
|---|---|---|
| 15.2a | `premortem/graph.py` | Generalize `human_approval` into `make_review(step)` for `analysis`, `strategy` and `campaign`. Each review calls `interrupt({step, output, issues})` and resumes with `{"approved": bool, "feedback": str}`. A rejection routes back to the agent that made the output. |
| 15.2b | `premortem/state.py`, agents | Feedback per step, which replaces the single `human_feedback`, and a review history (step, round, decision, feedback) that the blueprint's validation log shows. The Analyst and the Creative read their feedback, as the Strategist already does (`agents/revision.py`). |
| 15.2c | `premortem/runner.py`, `scripts/run_cli.py` | Pause and resume at any review. `--review` chooses which steps pause (default: all). `--auto-approve` still approves everything, so the evaluation does not change. |
| 15.2d | `tests/` | Reject each step once: only that agent and the ones after it run again, and the earlier outputs stay the same. |

Design rule: a rejected step re-runs that agent **and everything after it**. A new analysis makes the strategy out of date, and a new strategy makes the campaign out of date.

If this slips, keep the single strategy review: the timeline still shows a page per agent, and review of every step is presented as designed.

#### 15.3 Screens

```
┌──────────────────────────────────────────────────────────────────────┐
│ PremortemAI        New run · Saved runs · How it works   ● Anthropic │  top bar
├──────────────┬───────────────────────────────────────────────────────┤
│ Timeline     │  Step view                                            │
│              │                                                       │
│ ✓ Brief      │  Strategy · round 2 · approved by you                 │
│ ✓ Analysis   │  ┌─────────────────────────────────────────────────┐  │
│ ● Strategy ◄ │  │ Target: Weekly sport practitioners [3]          │  │
│ ○ Campaign   │  │ Positioning …                                   │  │
│ ○ Blueprint  │  │ Channels …                                      │  │
│              │  └─────────────────────────────────────────────────┘  │
│              │  Validator: 1 warning · What changed since round 1    │
│ 2:14 elapsed │  ┌ Review ─────────────────────────────────────────┐  │
│ 41k tokens   │  │ [Approve]  [Send back with feedback ▾]          │  │
│              │  └─────────────────────────────────────────────────┘  │
└──────────────┴───────────────────────────────────────────────────────┘
```

| Screen | Content |
|---|---|
| **A. Setup** (first screen) | **Key field:** paste a key and the provider is detected and shown (e.g. "Google Gemini · free tier"). A menu to change the provider, including "Custom (OpenAI-compatible)" with base URL and model fields. One line on what the choice means (e.g. Gemini free: slower, lower quality, data may be used by Google). "Check key" shows the result of each of the three checks. Under it, the model used by each role. **In `local` mode:** "Using the key from .env (Anthropic)", nothing to enter. **Tavily status:** "Web search provided by the team · 25 searches left in this session". **Document:** upload, or one of the sample documents with a one-line description each. **Review setting:** which steps pause for review. A strip shows the steps the run will take. |
| **B. Run workspace** | Left: the timeline. Centre: the view of the selected step. The review panel appears under the step that waits for review, and the timeline jumps to it. At the bottom of the timeline: time, tokens, current action, and a **Stop** button. |
| **C. Blueprint reader** | The final document in a reading layout: table of contents on the side, hover citations, a Sources list with anchors, downloads (Markdown, PDF). |
| **D. Evaluation** | Two views, both read from files, so they need no key and no API call. **D1, this run** (a tab of the run): today's tab, redesigned: metric tiles compared with the baseline, and expandable lists of claims, figures and sources. A saved run shows its committed `metrics.json`. **D2, evaluation results** (a page in the top bar): the Phase 14 results, read from `eval/results.json` and `eval/findings.md`: the research question, the averages of both systems, a table per case with a link to each case's saved run, the free preset (`gemini`) against `anthropic` on the demo, the blind ratings, the findings with the cases where the baseline wins, and the judge's spread (mean of 3 Haiku runs, shown next to traceability). |
| **E. Saved runs** | Cards of the committed runs (demo with `anthropic`, demo with `gemini`, the eval cases), each with document, provider, date and chosen target. A card opens screens B to D read-only, with no API call. |
| **F. How it works** | The architecture map (`docs/architecture.html`, updated) and one paragraph per agent. |

#### 15.4 Step views (one per agent)

| Step | Main content | Visual |
|---|---|---|
| Brief | Company, product, country, price hint, and the **missing information** in a highlighted list | Fact card |
| Analysis | Segments with size, intent and evidence. Competitors. **The searches the Analyst made**: query, results and the ones it cited | Bubble chart of the segments (size × intent), with the trap segment visibly small. Competitor table. |
| Strategy | Target and why, positioning, channels, pricing direction, each with citations | Short reasoning list linked to the analysis items it relies on |
| Campaign | One card per channel: message, content ideas, call to action | Message cards |
| Validator (on each step) | Issues with severity, round number, "revision limit reached" when it applies | Badges on the timeline and in the step view |
| Blueprint | Opens screen C | |

**Rounds.** When a step ran more than once (a validator revision or a human rejection), a selector shows each version. A **"What changed"** view lists the fields that differ from the previous round. This is how the professor sees the effect of their feedback.

#### 15.5 Review interaction

- **Approve**: one click, and the run continues.
- **Send back with feedback**: a text area, plus suggestion chips for common requests (e.g. "Target a bigger segment", "Cheaper positioning", "Use fewer channels"). A chip fills the text area, it does not send it.
- A note under the button says what a rejection re-runs, e.g. "Sending back the analysis re-runs the strategy and the campaign."

#### 15.6 Citations with hover

- Every `[n]` in the step views and in the blueprint is a citation chip.
- **On hover** (or keyboard focus) it shows a card: source title, domain, the passage or snippet used, and whether it comes from the document or the web.
- **On click** it opens the URL, or scrolls to the passage in the document.
- Built with HTML and CSS tooltips in `st.html` / `st.markdown(unsafe_allow_html=True)`, from the data already in `Source`. No custom JavaScript component.
- An unknown source id shows as a red `?` chip, so a broken citation is visible and not hidden.

#### 15.7 Visual design

- **Base:** the current achromatic theme in `.streamlit/config.toml` (ink on off-white, one blue for the active step, Geist fonts). It becomes a small set of tokens in one CSS file: colours, status colours (running, review, approved, warning, failed), spacing, radius and type scale.
- **One visual language for status:** the same icon and colour for a status in the timeline, the step view and the badges.
- **States:** each screen has an empty, a loading and an error state. Errors are in plain language and give the next action, for example:
  - invalid key → "This key was rejected by Google. Check it and try again.";
  - rate limit → "Free tier limit reached, waiting 30 s…" with a countdown, not a stack trace;
  - Tavily quota used up → "Web search unavailable, the agents are working from the document only."
- **Charts:** Streamlit's Altair / Vega-Lite charts in the theme colours, labelled on the chart and not only in a legend.
- **Responsive and accessible:** works on a laptop screen and does not break on a tablet. Contrast AA, every action reachable with the keyboard, status shown with text as well as colour.

#### 15.8 Technical approach

- **Stay on Streamlit.** A separate frontend (React and an API) would take more days than we have. Streamlit with custom CSS, `st.html` and `st.fragment` is enough for this design.
- Split `app.py` (about 450 lines today) into `ui/` modules: `setup.py`, `timeline.py`, `steps/<agent>.py`, `review.py`, `citations.py`, `blueprint_reader.py`, `saved_runs.py`, `theme.css`. `app.py` becomes routing only.
- The live part (timeline and current step) refreshes in an `st.fragment`, so the page does not rerun completely while the pipeline streams.
- Live and saved runs share the same views. The views read a `RunView` built from `state.json` and `run.json`, so saved runs need no special code.
- PDF export: the blueprint HTML with a print stylesheet. A PDF library only if the browser's "Save as PDF" is not good enough.

#### 15.9 Deployment

- Streamlit Community Cloud from the GitHub repo. *Settings → Secrets*: `PREMORTEM_MODE = "public"` and `TAVILY_API_KEY` only (see the rule in section 3). `public` is also the default, so the first line is a safeguard that documents the intent.
- The searches per session are counted in `st.session_state`. The cap is in `config.py`.
- Smoke test on the public URL with:
  - (a) a free Gemini key, (b) an Anthropic key, (c) an OpenRouter key or another preset;
  - (d) no key, saved runs only, (e) an invalid key, (f) a model without tool calling;
  - (g) the Tavily quota simulated as used up.

#### 15.10 Usability check

Before delivery, someone outside the team (a classmate, a friend) gets only the link and these tasks:

1. Run the demo document with a free key.
2. Find which source supports the chosen target.
3. Send the strategy back with feedback, and tell what changed.
4. Download the blueprint.

Watch without helping, note where they hesitate, and fix the top three problems.

#### 15.11 Priorities, if time runs short

| Must | Should | Could |
|---|---|---|
| Setup screen: any key, detection, "Check key", `local` and `public` modes | ~~Review of every step (15.2)~~ (decided not needed, see 15.2); rounds and "What changed" | Suggestion chips |
| Timeline with a page per agent | Bubble chart of the segments | PDF export with a print stylesheet |
| Hover citations | Blueprint reader with a table of contents | Tablet layout |
| Saved runs | "How it works" screen | |
| Evaluation of this run (D1), also on saved runs | Evaluation results page (D2) | |
| Error states for key, rate limit and quota | Usability check | |
| Deployment | | |

**Done when:** the professor opens the link and can:

1. browse a saved run with no key;
2. run the demo document with their own key, from any supported provider, and our Tavily key;
3. open each agent's result, send a reviewed step back and see what changed;
4. hover over any citation and see its source;
5. read the evaluation of a run and the Phase 14 results, with no key.

One person outside the team has done the four tasks of 15.10 without help.

---

### Buffer and delivery
**Dates:** day before delivery

- Update `docs/architecture.html` with the review steps and the models per role.
- Freeze `main` and tag `v1.0`.
- Record a short demo video as a backup, in case the app or the API is down during the presentation.
- Final README: link to the app, how to use your own key, results, link to this roadmap.
- Rotate the Tavily key after the course.

**Live demo checklist** (we run the app **locally**, with Claude, during the presentation):

| When | Task |
|---|---|
| Before Phase 14 | Top up the Anthropic credits of our usual development key (they ran out on 30 Oct), with a margin for the rehearsal and the demo. |
| Day before | Our usual development key in `.env` on the presentation laptop, with `PREMORTEM_MODE=local`. Check the credit balance in the console. |
| Day before | One full rehearsal run on the demo document, timed. Note the time and tokens for the talk. Keep the run in "Saved runs" as a fallback. |
| Day before | `uv run python scripts/check_setup.py` on the presentation laptop, on the room's network if possible. |
| Before the talk | Start the app, open the setup screen ("Using the key from .env") and load the demo document. Close any window that shows `.env`. |
| During | If the API or the network fails, open the rehearsal run from "Saved runs", or play the video. Do not open `.env` or print the environment while sharing the screen. |

The key is not revoked after the demo, because we keep using it for development. It must never go into the Streamlit Secrets (section 3).

---

## 5. Bonus (only after the Must items of Phase 15)

These come after the core work. Each one can be built in parallel by a team member who is not on the UI.

### B1. Pricing agent
**Branch:** `bonus/pricing-agent` · about 1 day, faster after B2.2

Today the price is the weakest part of the plan:
- the brief keeps only the `price_hint` from the document;
- competitors have a vague `price_level`;
- the Strategist writes a `pricing_direction` with no figures, and on the demo it says that pricing is "not yet decidable".

New graph order: `analyst → validate_analysis → pricing → strategist → ...`

| # | File | Content |
|---|---|---|
| B1.1 | `premortem/schemas.py` | `PricePoint` (competitor, product, price, currency, unit, source_id). `PricingAnalysis` holds: the price points; a price per unit (e.g. per 100 g) computed **in code**; a recommended price range; the positioning against the competitors; the reason. Every figure has a source id. |
| B1.2 | `premortem/agents/pricing.py` | A small ReAct loop with `price_search` (B2.2) and `web_search`, with its own recursion limit. Inputs: the brief, the competitors of the analysis, the target segment. Model role `pricing`, added to `RunSettings`. |
| B1.3 | `premortem/validation/rules.py` | Every price point has a source. The recommended range is inside the observed prices, or explained against them. The per-unit figures match the computation. |
| B1.4 | Strategist, blueprint, UI | The Strategist uses the pricing analysis for `pricing_direction`. The blueprint gets a "Pricing" section with the table of price points and their citations. The UI gets a Pricing step: a price table, and a strip chart of competitor prices per unit with the recommended range as a band. The step also gets a review (`make_review("pricing")`). |
| B1.5 | `tests/`, `eval/metrics.py` | Prices are parsed, the per-unit computation is correct, a missing figure gives a null price. New metric: every price in the plan appears on the cited page. The baseline can only guess prices. |

**Done when:** on the demo document, the blueprint has a pricing table with at least 3 sourced competitor prices and a recommended range.

### B2. Better web search
**Branch:** `bonus/web-search` · half a day to 1 day

Today the tool returns up to 5 results with a 500-character snippet each (`tools/web_search.py`). Figures are often cut off, and the Analyst cannot read a page in full.

| # | Improvement | Content |
|---|---|---|
| B2.1 | Read a page | A `read_page(url)` tool with Tavily Extract. It returns the passage that matches the Analyst's question, not the whole page. The source keeps the passage, so the hover card (15.6) shows the exact text. |
| B2.2 | `price_search` | Searches aimed at retailers and price pages. It returns price, currency and pack size only when they appear in the text, and null otherwise. Used by B1, and useful to the Analyst without B1. |
| B2.3 | Search options | Tavily `search_depth="advanced"` for market figures. Queries in the language of the target country as well as in English (e.g. French for France). Optional domain filters (statistics offices, retailers). |
| B2.4 | Search plan | Before searching, the Analyst writes the list of questions that the document leaves open (e.g. from `missing_info`). It searches for those, and the UI shows the plan in the Analysis step. |
| B2.5 | Duplicates and cache | Drop duplicate URLs across searches. Cache the results by query within a run, so a validator round does not pay for the same search twice. |

Eval case: the **"gap" case** of the devlog (30 Oct, priority 3), a document with no market size and no competitor list. Metrics: traceability and valid URLs, before and after B2. This is where the multi-agent pipeline can beat one prompt.

---

## 6. Timeline summary

| Date | Phase | Deliverable |
|---|---|---|
| 11 to 12 Nov | 12 | Models per role, any provider, keys per run |
| 12 Nov | 13 | Reproducible repo, saved example runs |
| 13 Nov | 14 | Final evaluation run (in the background), findings |
| 13 Nov | 15 (design) | Screens, step views and tokens decided |
| 14 to 18 Nov | 15 (build) | Review of every step, final UI, deployment, usability check |
| From 14 Nov, in parallel | B1, B2 | Bonus, only if a team member is free from the UI |
| Before delivery | Buffer | Live demo checklist, `v1.0`, video, README |

**If time runs short:**
- 12, 13 and the Must column of 15.11 are the minimum.
- If 14 cannot run (no credits), present the demo case and the `gemini` run and say that the other cases are missing.
- Bonuses are presented as designed, with this document as the plan.

---

## 7. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| Credits run out during the evaluation (as on 30 Oct) | Top up first. Run the cases one by one with `--cases`. Results are cached in `results.json`. |
| Haiku is unstable as a judge | Measure the spread over 3 runs (Phase 12). Switch back to Sonnet and explain why if it is too large. |
| The free tier is too slow or too limited for a full run | Rate limiter and retries (Phase 12), Flash models. The test run of 12.8 measures it early. Fallback: another provider, or saved runs. |
| Prompts tuned on Claude fail on Gemini or other providers | The test run of 12.8 finds them early for Gemini. `check_model` blocks models without tool calling or structured output. Fix the prompt or the schema for every provider, not for one. |
| Our LLM key ends up on the public app | `public` mode never reads `LLM_API_KEY`. Nothing but `TAVILY_API_KEY` in the Secrets. A test checks it. |
| A visitor's key leaks | The key lives only in `st.session_state`. It is never logged or written to files. A test checks `run.json` and `state.json`. |
| Our Tavily quota is used up by visitors | Cap of searches per session. Without searches the pipeline still runs from the document. |
| The UI rework takes longer than planned | Must / Should / Could table (15.11). Saved runs and hover citations come first, because they work even when nothing else does. |
| The network or the API fails during the live demo | Live demo checklist: rehearsal run in "Saved runs", video. |
| Reviews of every step make a run long | Review setting in the setup screen and `--review` in the CLI. Approving is one click. |
