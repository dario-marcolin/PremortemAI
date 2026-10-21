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

TODO (filled in as the phases land).

## Roadmap

See the project roadmap (link TODO).
