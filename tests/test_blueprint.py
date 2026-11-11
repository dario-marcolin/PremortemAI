import re

import pytest
from langchain_core.messages import AIMessage

from premortem.output import blueprint
from premortem.output.blueprint import References, render_blueprint, save_blueprint, validation_log
from premortem.schemas import Source, ValidationIssue, ValidationResult
from tests.graph_fakes import STATE, SUMMARY, FakeModel, install

SECTIONS = ["Executive summary", "Company brief", "Market and competitors", "Segments", "Strategy",
            "Campaign", "Validation log", "Sources"]


@pytest.fixture
def state() -> dict:
    return {**STATE, "analysis": STATE["analysis"].model_copy(deep=True), "validations": list(STATE["validations"])}


def result(stage, *issues):
    issues = [ValidationIssue(severity=s, check=c, message=f"{c} message") for s, c in issues]
    return ValidationResult(stage=stage, passed=all(i.severity == "warning" for i in issues), issues=issues)


def test_sections_in_order(state):
    md = render_blueprint(state, summary="Summary.")
    headings = re.findall(r"^## \d\. (.+)$", md, flags=re.M)
    assert [h for h in headings] == SECTIONS


def test_every_source_id_becomes_a_numbered_reference(state):
    md = render_blueprint(state, summary="Summary.")
    body, sources = md.split("## 8. Sources")
    assert not re.search(r"\bS\d+\b", body)  # no raw source id is left
    cited = {int(n) for group in re.findall(r"\[([\d, ]+)\]", body) for n in group.split(", ")}
    listed = [int(n) for n in re.findall(r"^(\d+)\. ", sources, flags=re.M)]
    assert listed == list(range(1, len(STATE["analysis"].sources) + 1))
    assert cited <= set(listed)
    for s in STATE["analysis"].sources:
        assert s.reference in sources


def test_references_are_numbered_by_first_use():
    refs = References([Source(id=f"S{i}", kind="web", reference=f"https://x/{i}") for i in (1, 2, 3)])
    assert refs.refs("Size 2M, S3, and [S1, S3]") == "Size 2M [1], and [2, 1]"
    assert refs.cite(["S2", "S9"]) == "[3, S9?]"  # an unknown id is kept and marked
    assert refs.refs("Galaxy S24 [sic]") == "Galaxy S24 [sic]"
    assert [n for n, _ in refs.listed()] == [1, 2, 3]


def test_target_segment_is_marked(state):
    md = render_blueprint(state, summary="Summary.")
    assert f"| **→ {state['strategy'].target_segment_id}** |" in md


def test_table_cells_are_escaped(state):
    state["campaign"] = state["campaign"].model_copy(deep=True)
    state["campaign"].key_messages[0].body = "Line one\nline | two"
    md = render_blueprint(state, summary="Summary.")
    assert "Line one line \\| two" in md


def test_validation_log_marks_resolved_and_unresolved(state):
    state["validations"] = [
        result("strategy", ("blocking", "segment_size"), ("warning", "pricing")),
        result("strategy", ("blocking", "claims")),
        result("strategy", ("blocking", "claims")),
    ]
    statuses = [[s for _, s in e["issues"]] for e in validation_log(state)]
    assert statuses == [["blocking, resolved", "warning"], ["blocking, unresolved"], ["blocking, unresolved"]]
    md = render_blueprint(state, summary="Summary.")
    assert "Unresolved blocking issues" in md and "*strategy*, `claims`" in md
    assert "### Strategy, check 3: failed" in md


def test_no_open_issues_callout_when_everything_passed(state):
    state["validations"] = [result("strategy"), result("campaign", ("warning", "tone"))]
    assert "Unresolved blocking issues" not in render_blueprint(state, summary="Summary.")


def test_summary_is_written_by_the_llm(monkeypatch, state):
    model = install(monkeypatch, FakeModel())
    md = render_blueprint(state)
    assert f"## 1. Executive summary\n\n{SUMMARY}\n" in md
    prompt = model.prompts["summary"][0]
    assert "<strategy>" in prompt and "<campaign>" in prompt and "<unresolved_blocking_issues>" in prompt


def test_source_ids_are_stripped_from_the_summary(monkeypatch, state):
    reply = AIMessage(f"{SUMMARY} [S1, S2]")
    monkeypatch.setattr(blueprint, "get_llm", lambda *_a, **_k: type("M", (), {"invoke": lambda _s, _m: reply})())
    assert f"\n{SUMMARY}\n" in render_blueprint(state)


def test_summary_failure_does_not_lose_the_blueprint(monkeypatch, state):
    def fail(*_a, **_k):
        raise RuntimeError("API down")
    monkeypatch.setattr(blueprint, "get_llm", fail)
    md = render_blueprint(state)
    assert "could not be written: API down" in md and "## 8. Sources" in md


def test_save_blueprint_creates_the_folder(tmp_path, state):
    path = save_blueprint(state, tmp_path / "run" / "blueprint.md", summary="Summary.")
    assert path.read_text().startswith("# Launch Blueprint: ")
