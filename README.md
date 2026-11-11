# PremortemAI

A multi-agent adviser for product launch planning. Give it a company or product document:
specialised agents analyse the market (with web search), choose a target and a positioning,
write the campaign, check each other's work, and produce a **Launch Blueprint** where every
claim cites its source. A human approves the strategy before the campaign is written.

## Try it online

**[premortemai.streamlit.app](https://premortemai.streamlit.app)** — nothing to install.

- **To look around, you need nothing.** Open *Saved runs* and pick a run: every agent's page, the
  blueprint and the evaluation open with no key and no cost. Start with
  [the demo run on Claude](https://premortemai.streamlit.app/run?saved=examples/demo_anthropic&step=analysis).
- **To make your own plan, you need an Anthropic or Google Gemini API key.** A
  [free Gemini key](#get-a-free-gemini-key) takes two minutes and works. Web search is provided by
  the app. Your key stays in your browser tab: it is never saved, and it is gone when you close the tab.

If the page shows *"This app has gone to sleep"*, click the button to wake it up and wait about a minute.

### Your first run, step by step

1. **New run:** paste your key. The provider is recognised from the key; *Check key* makes three
   tiny test calls and says if anything is wrong.
2. Keep the sample document **demo_company.pdf** (a fictional food company launching protein crisps
   in France), or upload your own (PDF, Word, PowerPoint, Markdown or text, with selectable text).
3. Click **Run the pipeline**. The timeline on the left shows each agent as it works: Brief,
   Analysis, Strategy, Campaign, Blueprint. Click any step to open its page, during the run or after.
   A run takes about 3 minutes on Claude, a few minutes more on the free Gemini tier.
4. **The run stops at the strategy and waits for you.** Read the target and the reasoning, then
   *Approve and continue*, or write what to change (or click a suggestion) and *Send back*.
   The new round shows **What changed**, word by word.
5. **Blueprint:** the final plan. Hover any number such as `[3]` to see its source; click a web
   source to open it. *Download PDF* saves it.

Small grey chips such as `S3` on the agent pages are the agents' own source ids: hover them too.
A red `?` chip means a citation points to a source that does not exist. Free models write weaker
plans than Claude; the app says so where it matters.

### The pages

| Page | What it does |
|---|---|
| **New run** | Paste an Anthropic or Gemini key, choose a sample document or upload one, run. In `local` mode (below) the keys come from `.env` instead. |
| **Run** | The timeline of the agents and one page per agent: the brief and what the document does not say, the segments by size and purchase intent, the competitors and the web searches, the strategy and what it relies on, the campaign. The Validator's checks and every round of a step are on its page. |
| **Blueprint** (in the timeline) | The Launch Blueprint with a table of contents and hover citations; download it as PDF or Markdown. |
| **Saved runs** | Finished runs kept in the repository (`examples/`, `eval/runs/`), read-only. A link opens one directly, e.g. `?saved=examples/demo_anthropic&step=analysis`. |
| **Evaluation** | The scores of a run against a single-prompt baseline, and the results over all evaluation cases. |
| **How it works** | One paragraph per agent and the project map. |

## Architecture

[![PremortemAI architecture map](docs/architecture.png)](https://dario-marcolin.github.io/PremortemAI/architecture.html)

Document → `extract_brief` → Analyst (Tavily web search) → Strategist ⇄ Validator →
your review → Creative ⇄ Validator → Launch Blueprint. Each role has its own model
(`RunSettings`), on any supported provider. The evaluation harness runs the same pipeline
against a single-prompt baseline.

[Interactive map](https://dario-marcolin.github.io/PremortemAI/architecture.html), updated for
Phase 15 (zoom, search, light/dark theme; source: [docs/architecture.html](docs/architecture.html)).
The same map is in the app, on the *How it works* page.

**See a result without running anything:** [`examples/`](examples/) holds two complete runs on the
demo document, one with Claude ([`demo_anthropic`](examples/demo_anthropic/blueprint.md)) and one with
the free Gemini tier ([`demo_gemini`](examples/demo_gemini/blueprint.md)). Each folder has the
blueprint, the full state, the run record (models, tokens, time) and the log.

## Run it on your computer

You need `git`, an LLM key (a [free Gemini key](#get-a-free-gemini-key) works) and, for web
search, a [Tavily key](https://app.tavily.com) (free plan, about 1,000 searches a month; one run
uses a few dozen at most). Without a Tavily key the pipeline still runs, from the document only.

**1. Install `uv`** (it also installs the right Python, 3.11 or newer):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                                 # macOS, Linux
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
```

**2. Get the code and the packages:**

```bash
git clone https://github.com/dario-marcolin/PremortemAI.git
cd PremortemAI
uv sync
```

**3. Add your keys:**

```bash
cp .env.example .env
```

Open `.env` and fill in:

```bash
PREMORTEM_MODE=local       # keys from this file
LLM_PROVIDER=gemini        # or leave empty for anthropic (Claude)
LLM_API_KEY=AIza...        # your key of that provider
TAVILY_API_KEY=tvly-...
```

To keep the keys of several providers in one `.env`, use `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`
(and so on, `<PROVIDER>_API_KEY`) instead of `LLM_API_KEY`, and switch with `LLM_PROVIDER` only.
A key whose prefix belongs to another provider is refused, so a Gemini key is never sent to Anthropic.

`.env` is git-ignored: never commit real keys.

**4. Check the setup** (three tiny model requests and one search):

```bash
uv run python scripts/check_setup.py
```

It prints one line per check (Python, packages, keys, models per role, tool calling, structured
output, web search) and says what to fix. `--offline` checks everything except the API calls.

**5. Run:**

```bash
uv run streamlit run app.py                                                    # in the browser
uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf --auto-approve   # in the terminal
```

A run takes about 2 to 3 minutes (longer on a free tier when the rate limit is reached). The result is in `outputs/<run_id>/blueprint.md`.

**With `pip` instead of `uv`:** Python 3.11+, then `python -m venv .venv`, activate it,
`pip install -r requirements.txt`, and use `python` / `streamlit` in place of `uv run`.
`requirements.txt` is generated from `uv.lock` (`uv export --no-hashes --no-dev --format requirements-txt -o requirements.txt`).

### Get a free Gemini key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey) and sign in with a Google account.
2. *Create API key*. It starts with `AIza` or `AQ.`.
3. **Online:** paste it in the key field of *New run*. **On your computer:** put it in `.env` as
   `GEMINI_API_KEY` (or `LLM_API_KEY` with `LLM_PROVIDER=gemini`). With several
   keys in `.env` (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`…), the *New run* page in `local` mode lets
   you pick the provider.

The free tier is limited per minute and per day, so a run is slower and the app waits when the
limit is reached (it does not fail). Free models give **weaker plans**: in
[`examples/demo_gemini`](examples/demo_gemini/blueprint.md) the Analyst made 3 searches and cited
7 sources, against 10 and 17 with Claude. Google may use free-tier data: our demo documents are fictional.

## Providers and models

Each role has its own model. The presets (`premortem/providers.py`):

| Preset | Agents and Validator | Blueprint summary | Evaluation judge | Tested |
|---|---|---|---|---|
| `anthropic` (default) | `claude-sonnet-5-5` | `claude-opus-5-5` | `claude-haiku-5-5` | end to end |
| `gemini` | `gemini-3.5-flash-lite` | `gemini-3.6-flash` | `gemini-3.5-flash-lite` | end to end |
| `openai` | `gpt-5-mini` | `gpt-5` | `gpt-5-mini` | `check_model` only |
| `mistral` | `mistral-medium-latest` | `mistral-large-latest` | `mistral-medium-latest` | `check_model` only |
| `groq` | `openai/gpt-oss-120b` | same | same | `check_model` only |
| `openrouter` | `openai/gpt-5-mini` | `anthropic/claude-opus-5-5` | `openai/gpt-5-mini` | `check_model` only |

**The app offers Anthropic and Gemini only**, the presets tested end to end. The others work from
the command line and from `.env`, but are less tested. Small or free models
give weaker plans. A model must support **tool calling** (the Analyst's web search) and
**structured output** (every agent returns a typed object); `check_setup.py` and the app's
*Check key* test both before a run.

- **One role at a time:** `LLM_MODEL_<ROLE>=provider:model` in `.env` (roles: `BRIEF`, `ANALYST`,
  `STRATEGIST`, `CREATIVE`, `VALIDATOR`, `BLUEPRINT`), and `LLM_JUDGE_MODEL` for the evaluation.
- **Every role:** `LLM_MODEL=provider:model`. Leave it empty to keep the preset.
- **Any OpenAI-compatible service** (Together, DeepSeek, a university server, a local Ollama…):
  `LLM_BASE_URL=https://…/v1`, `LLM_MODEL=openai:<model name>`, and its key in `LLM_API_KEY`
  (command line and `local` mode; not offered in the public app).

## Two modes: `local` and `public`

| Mode | Where to set it | LLM key | Tavily key |
|---|---|---|---|
| `local` | `PREMORTEM_MODE=local` in `.env` | read from `.env` | read from `.env` |
| `public` | *Settings → Secrets* of the Streamlit Cloud app: `PREMORTEM_MODE = "public"` | **pasted by each visitor** in the app, kept only in the browser session | the app's, from the Secrets |

**Unset means `public`:** if `PREMORTEM_MODE` is missing, the app never reads an LLM key from the
server and asks the visitor for one. Never put an LLM key in the Streamlit Secrets: the app
would use it for anyone with the link. In both modes the keys never reach the run files
(`run.json`, `state.json`, `log.txt`) or the checkpoints; a test checks it.

A key pasted in the public app passes through the Streamlit server and this code (over HTTPS).
If you prefer not to paste a key, [run the app on your computer](#run-it-on-your-computer).

## Cost of a run

Measured on the demo document (`run.json` of each example):

| | Tokens | Time |
|---|---|---|
| One run, `anthropic` | about 150k (140k Sonnet, 8.5k Opus) | about 2.5 min |
| One run, `gemini` free tier | about 55k (50k Flash-Lite, 5k Flash) | 1.5 to 2.5 min |
| Evaluation of one plan (judge) | about 20k (Haiku) | under 1 min |
| Full evaluation (5 cases, pipeline + baseline + judge) | about 1 million | about 30 min |

## Why the outputs change between runs

The **procedure** is reproducible: same document, same prompts, same models per role
(recorded in `run.json`), same graph. The **exact text** is not. Claude 5 models reject the
temperature parameter, so they cannot be run at temperature 0, and web search results change
over time. Two runs on the same document reach the same decisions on the demo (the same target
segment, the trap segment avoided) with different wording. For this reason the evaluation
reports the judge's spread over repeated runs, and the saved runs in `examples/` show one
concrete outcome.

## More on running

In the browser the steps are the same as [online](#your-first-run-step-by-step). With *Evaluate the
result* switched on, the **Evaluation** step of the timeline scores the blueprint (traceability,
faithfulness, coherence, trap, cost) when the run ends, and can compare it with the single-prompt baseline.

From the terminal, the pipeline pauses for your approval of the strategy:

```bash
uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf
uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf --reject "Target vegans"
```

At `Approve? [y/n/feedback]`, `y` approves and any other text rejects the strategy with that
feedback. Each run writes `outputs/<run_id>/`: `log.txt` (every step, as the run goes),
`blueprint.md`, `state.json` and `run.json`. To re-render the blueprint of a saved run:
`uv run python tests/run_blueprint.py --run outputs/<run_id>`.

Offline tests (fake LLMs, no API credits): `uv run pytest`.

## Evaluation

Runs the pipeline (auto-approve) and a single-prompt baseline (same model, same document,
no tools, no validator) on every case of `eval/cases/`, scores both and writes
`eval/report.md`:

```bash
uv run python -m eval.run_eval                        # all cases, both systems
uv run python -m eval.run_eval --cases nordbrew_de    # some cases
uv run python -m eval.run_eval --report-only          # rebuild the report (e.g. after the human rating)
uv run python -m eval.run_eval --cases demo_fr --provider gemini   # the same case on the free preset
uv run python -m eval.score_examples                  # score the saved runs of examples/
```

Both systems use the `--provider` preset (default `anthropic`); the judge is always the anthropic
preset's (Haiku), so every run is scored by the same judge. It scores each plan 3 times
(`--judge-runs`) and the report gives the mean and the spread. The runs are kept in `eval/runs/`.
The Phase 10 results are archived in `eval/archive/`.

Metrics are defined in `eval/metrics.py`; the blind human rating is in `eval/rating/` (see
its README).

## Roadmap

[`PremortemAI_roadmap_FINAL.md`](PremortemAI_roadmap_FINAL.md): what is done and what comes
next, up to delivery. The earlier phases are in
[`PremortemAI_technical_roadmap_DEMO2.md`](PremortemAI_technical_roadmap_DEMO2.md).
