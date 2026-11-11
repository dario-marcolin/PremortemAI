"""Check that this machine can run PremortemAI (Phase 13): Python, keys, the model and web search.

    uv run python scripts/check_setup.py              # everything, with the settings of .env
    uv run python scripts/check_setup.py --offline    # no API call: Python, packages, .env only

It reads the same .env as the CLI (local mode). It prints one line per check, what works and what
is missing, and exits with 1 if the pipeline cannot run. It never prints a key.
The model check sends three tiny requests (a plain call, a tool call, a structured output);
the web search check makes one Tavily search. Together they cost a fraction of a cent.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIN_PYTHON = (3, 11)
OK, WARN, FAIL = "ok", "warning", "missing"


def line(status: str, name: str, message: str) -> None:
    mark = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}[status]
    print(f"{mark} {name:<25} {message}")


def check_python() -> bool:
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info < MIN_PYTHON:
        line(FAIL, "Python", f"{version}; PremortemAI needs {'.'.join(map(str, MIN_PYTHON))} or newer "
                             "(`uv sync` installs the right one)")
        return False
    line(OK, "Python", version)
    return True


def check_env_file() -> None:
    if (ROOT / ".env").exists():
        line(OK, ".env", "found at the repo root")
    else:
        line(WARN, ".env", "not found: copy it with `cp .env.example .env` and add your keys")


def check_search(settings) -> None:
    from premortem.llm import using_settings
    from premortem.tools.web_search import web_search

    with using_settings(settings):
        results = web_search.invoke({"query": "protein snacks market France"})
    error = results[0].get("error") if results else "no results"
    if error:
        line(WARN, "Web search", f"{error} (the pipeline still runs, from the document only)")
    else:
        line(OK, "Web search", f"Tavily answered with {len(results)} results")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="skip the model and web search checks (no API call)")
    args = parser.parse_args(argv)

    print("PremortemAI setup check\n")
    if not check_python():
        return 1
    try:
        from premortem.config import RunSettings
        from premortem.llm import check_model
        from premortem.providers import PRESETS
    except ImportError as e:
        line(FAIL, "Packages", f"{e}: run `uv sync` in the repo folder")
        return 1
    line(OK, "Packages", "installed")
    check_env_file()

    try:
        settings = RunSettings.from_env(mode="local")
    except ValueError as e:
        line(FAIL, "Models", str(e))
        return 1
    preset = PRESETS.get(settings.provider)
    line(OK, "Provider", preset.label if preset else f"{settings.provider} (custom, {settings.base_url})")
    for role, model in settings.models.items():
        print(f"{'':7}{role:<11} {model}")
    print(f"{'':7}{'eval judge':<11} {settings.eval_judge}")

    ready = True
    if settings.llm_api_key:
        line(OK, "LLM_API_KEY", "set")
    else:
        line(FAIL, "LLM_API_KEY", "empty in .env: the pipeline needs a key of the provider above")
        ready = False
    if settings.tavily_api_key:
        line(OK, "TAVILY_API_KEY", "set")
    else:
        line(WARN, "TAVILY_API_KEY", "empty: no web search, the agents work from the document only")

    if args.offline:
        print("\nOffline: the model and web search were not called.")
    else:
        if settings.llm_api_key:
            for check in check_model(settings):
                line(OK if check.ok else FAIL, f"Model: {check.name}", check.message)
                ready &= check.ok
        if settings.tavily_api_key:
            check_search(settings)

    print("\nReady: run `uv run streamlit run app.py` or `uv run python scripts/run_cli.py --doc "
          "data/demo/demo_company.pdf`." if ready else "\nNot ready: fix the lines marked FAIL above.")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
