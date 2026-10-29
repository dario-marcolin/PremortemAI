# PremortemAI

Agent-based premortem analysis: given a project document, the agents imagine
how the project failed and produce a structured report.

## Team and roles

- **A** – project setup, core pipeline
- **B** – review and integration
- **C** – documentation and evaluation

## Setup

```bash
uv sync
cp .env.example .env   # then fill in LLM_API_KEY and TAVILY_API_KEY
```

`.env` is git-ignored: never commit real keys.

Smoke test:

```bash
uv run python -c "from premortem.llm import get_llm; print(get_llm().invoke('hello'))"
```

## Run

Full pipeline from the terminal (pauses for your approval of the strategy):

```bash
uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf
uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf --auto-approve
uv run python scripts/run_cli.py --doc data/demo/demo_company.pdf --reject "Target vegans"
```

At `Approve? [y/n/feedback]`, `y` approves and any other text rejects the strategy with
that feedback. Results go to `outputs/<run_id>/` (`state.json`, `run.json`).

Offline tests (fake LLMs, no API credits): `uv run pytest`.

## Roadmap

See the project roadmap (link TODO).
