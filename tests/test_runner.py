"""The shared runner (CLI, UI, evaluation) with fake LLMs: log lines, pause and resume, files, failures."""

import json

import pytest

from premortem import graph
from premortem.ingestion.parser import DocumentParseError
from premortem.runner import PIPELINE, Run
from tests.graph_fakes import SETTINGS, STATE, FakeModel, install


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "company.md"
    path.write_text(STATE["document_text"])
    return path


def run_to_end(run: Run, answers: list[dict]) -> list:
    lines = list(run.advance())
    for answer in answers:
        assert run.status == "waiting"
        run.answer(answer)
        lines += run.advance()
    return lines


def test_run_logs_every_node_pauses_and_writes_its_files(monkeypatch, document, output_dir):
    install(monkeypatch, FakeModel())
    run = Run(document, settings=SETTINGS, run_id="r1")
    assert run.status == "running"

    lines = list(run.advance())
    assert run.status == "waiting"
    assert run.pending["strategy"]["target_segment_id"] == STATE["strategy"].target_segment_id
    assert lines[-1].kind == "pause"
    assert [(l.kind, l.text) for l in lines if l.node == "analyst" and l.kind != "node"] == [
        ("search", "coffee Italy"), ("results", f"{sum(s.kind == 'web' for s in STATE['analysis'].sources)} results")]

    run.answer({"approved": True})
    lines += run.advance()
    assert run.status == "done" and run.pending is None
    assert [l.node for l in lines if l.kind == "node"] == PIPELINE
    assert all(b.seconds >= a.seconds for a, b in zip(lines, lines[1:]))

    files = {p.name for p in (output_dir / "r1").iterdir()}
    assert files == {"blueprint.md", "state.json", "run.json", "log.txt"}
    record = json.loads((output_dir / "r1" / "run.json").read_text())
    assert record["status"] == "done" and record["error"] is None
    assert record["decisions"] == [{"approved": True, "target_segment_id": STATE["strategy"].target_segment_id,
                                    "unresolved": False}]
    assert len((output_dir / "r1" / "log.txt").read_text().splitlines()) == len(lines)


def test_rejection_is_logged_with_its_feedback(monkeypatch, document):
    install(monkeypatch, FakeModel())
    run = Run(document, settings=SETTINGS)
    lines = run_to_end(run, [{"approved": False, "feedback": "Target students"}, {"approved": True}])
    assert run.status == "done"
    assert [l.text for l in lines if l.node == "human_approval" and l.kind == "node"] == [
        "rejected: Target students", "approved"]
    assert [d["approved"] for d in run.decisions] == [False, True]


def test_failed_node_is_logged_saved_and_can_be_retried(monkeypatch, document, output_dir):
    install(monkeypatch, FakeModel())
    calls = []
    real = graph.strategist

    def flaky(state):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("rate limited")
        return real(state)

    monkeypatch.setattr(graph, "strategist", flaky)
    run = Run(document, settings=SETTINGS, run_id="r2")
    lines = list(run.advance())

    assert run.status == "failed" and run.error == "RuntimeError: rate limited"
    assert (lines[-1].node, lines[-1].kind) == ("strategist", "error")
    assert json.loads((output_dir / "r2" / "run.json").read_text())["status"] == "failed"
    assert "Traceback" in (output_dir / "r2" / "log.txt").read_text()

    # Retrying continues from the last checkpoint: the brief and the analysis are not redone
    lines = run_to_end(run, [{"approved": True}])
    assert run.status == "done"
    assert [l.node for l in lines if l.kind == "node"] == PIPELINE[3:]


def test_answer_outside_the_pause_is_refused(monkeypatch, document):
    install(monkeypatch, FakeModel())
    with pytest.raises(RuntimeError):
        Run(document, settings=SETTINGS).answer({"approved": True})


def test_unsupported_document_is_refused_before_the_run(tmp_path):
    path = tmp_path / "notes.xlsx"
    path.write_text("x")
    with pytest.raises(DocumentParseError):
        Run(path, settings=SETTINGS)
