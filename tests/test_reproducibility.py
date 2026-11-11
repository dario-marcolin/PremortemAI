"""Phase 13: saved example runs, portable run files, the setup check (offline)."""

import json
import re
from pathlib import Path

import pytest

from premortem.runner import REPO_ROOT, portable_path
from scripts import check_setup

EXAMPLES = REPO_ROOT / "examples"
RUN_FILES = {"blueprint.md", "state.json", "run.json", "log.txt"}
SECRET = re.compile(r"sk-ant-|sk-or-|gsk_|AIza|\bAQ\.|tvly-|/Users/|/home/")


def test_document_path_is_relative_inside_the_repo(tmp_path):
    assert portable_path(REPO_ROOT / "data" / "demo" / "demo_company.pdf") == "data/demo/demo_company.pdf"
    outside = tmp_path / "upload.pdf"  # an upload: only the name, never the local folder
    assert portable_path(outside) == "upload.pdf"


@pytest.mark.parametrize("name, provider", [("demo_anthropic", "anthropic"), ("demo_gemini", "gemini")])
def test_example_runs_are_complete_and_portable(name, provider):
    folder = EXAMPLES / name
    assert RUN_FILES <= {p.name for p in folder.iterdir()}
    run = json.loads((folder / "run.json").read_text())
    assert run["provider"] == provider and run["status"] == "done"
    assert (REPO_ROOT / run["document"]).exists()
    state = json.loads((folder / "state.json").read_text())
    assert state["strategy"]["target_segment_id"]


def test_committed_runs_hold_no_keys_and_no_local_paths():
    eval_dir = REPO_ROOT / "eval"
    files = [*EXAMPLES.rglob("*"), *(eval_dir / "runs").rglob("*"), eval_dir / "results.json", eval_dir / "report.md"]
    for path in files:
        if path.is_file():
            assert not SECRET.search(path.read_text()), path


def test_check_setup_offline(monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-secret-value")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_JUDGE_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert check_setup.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "Anthropic" in out and "TAVILY_API_KEY" in out and "Ready" in out
    assert "secret-value" not in out  # never prints a key


def test_check_setup_fails_without_llm_key(monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", "")
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_JUDGE_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert check_setup.main(["--offline"]) == 1
    assert "Not ready" in capsys.readouterr().out
