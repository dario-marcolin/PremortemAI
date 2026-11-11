"""Phase 10 evaluation, offline: cases, figure matching, claims, source pages, baseline, rating, report."""

import csv
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from eval import metrics, rating
from eval.baseline import run_baseline
from eval.metrics import (Claim, Page, check_claims, evaluate, fetch_page, figure_in, find_case, load_cases,
                          locate, markers, parse_sources, plan_text, scores, text_values)
from eval.run_eval import ROOT, render_report, run_case
from premortem.runner import Run
from tests.graph_fakes import SETTINGS, BASELINE_CLAIM, STATE, FakeModel, install

PLAN = """# Launch Blueprint: Crisps

## 1. Executive summary

Target sport practitioners.

## 3. Market and competitors

The category was worth 480 million euros in 2024 [1]. Plant-based products make up 18% [2].
- 27% of adults bought a protein snack [3].
| Barebells | sport image, 2.49 euros a bar | unknown | [4] |
Growth was 11% a year, says a blog.

## 7. Validation log

- **warning** · `judge.source_quality`: 99% of claims rest on one panel [1].

## 8. Sources

1. Document: company.pdf, section 4
2. <https://example.com/ok>
3. <https://example.com/gone>
4. Nielsen 2024 snack report
"""


# ── cases ───────────────────────────────────────────────────────────────────────────────

def test_cases_are_complete_and_one_is_a_trap():
    cases = load_cases()
    assert 3 <= len(cases) <= 5
    assert len({c["id"] for c in cases}) == len(cases)
    assert len({c["country"] for c in cases}) == len(cases)  # different countries
    assert any(c["trap"] for c in cases)
    for c in cases:
        assert (ROOT / c["document"]).exists(), c["document"]


def test_find_case_by_file_name(tmp_path):
    assert find_case(tmp_path / "upload" / "demo_company.pdf")["id"] == "demo_fr"
    assert find_case(tmp_path / "other.pdf") is None


# ── the plan ────────────────────────────────────────────────────────────────────────────

def test_plan_text_leaves_out_the_validation_log_and_the_sources():
    plan = plan_text(PLAN)
    assert "480 million" in plan and "Executive summary" in plan
    assert "99% of claims" not in plan and "Nielsen" not in plan


def test_parse_sources_kinds():
    sources = parse_sources(PLAN)
    assert {n: s["kind"] for n, s in sources.items()} == {"1": "document", "2": "web", "3": "web", "4": "other"}
    assert sources["2"]["url"] == "https://example.com/ok"
    assert parse_sources("## Sources\n\n[1] Document: a.md\n[2] https://x.org/a.\n")["2"]["url"] == "https://x.org/a"


def test_markers_and_locate():
    assert markers("a [1, 3] b [4-6] c [S2] [2025]") == {"1", "3", "4", "5", "6", "2025"}
    plan = plan_text(PLAN)
    assert locate("**Barebells** sport image", plan).startswith("| Barebells")  # markdown ignored
    assert locate("not in the plan", plan) is None


# ── figures ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("figure, source, found", [
    ("1.3 million", "1,276,000 adults", True),  # rounding of the figure as written
    ("1.3 million", "1,3 million d'adultes", True),  # European decimal comma
    ("17.5M", "17.5 million", True),
    ("2,300 points of sale", "about 2,300 shops", True),
    ("2.5%", "2,5 %", True),
    ("41%", "42% of them", False),
    ("1.3 million", "1.3% of adults", False),  # a scaled figure needs a scaled value
    ("18-64", "aged 18 to 64", True),  # every number of the figure
    ("18-65", "aged 18 to 64", False),
    ("1 300 000", "1.3 million", True),
    ("10 million units", "9.6 million euros", False),  # rounding is capped at 3%
    ("38%", "38", True),
])
def test_figure_matching(figure, source, found):
    assert figure_in(figure, text_values(source)) is found


def test_figure_without_a_number():
    assert figure_in("one in four", text_values("25%")) is None


# ── claims: traceability and faithfulness ───────────────────────────────────────────────

def test_check_claims():
    plan = plan_text(PLAN)
    claims = [
        Claim(quote="The category was worth 480 million euros in 2024", figures=["480 million euros"], refs=["1"]),
        Claim(quote="Plant-based products make up 18%", figures=["18%"], refs=["2"]),
        Claim(quote="27% of adults bought a protein snack", figures=["27%"], refs=["3"]),
        Claim(quote="sport image, 2.49 euros a bar", figures=["2.49 euros"], refs=["4"]),
        Claim(quote="Growth was 11% a year", figures=["11%"], refs=["1"]),  # [1] is not on its line
        Claim(quote="A claim the extractor made up", figures=["5%"], refs=["1"]),
    ]
    pages = {"https://example.com/ok": Page("https://example.com/ok", "ok", "Plant-based share: 18 %."),
             "https://example.com/gone": Page("https://example.com/gone", "broken", detail="HTTP 404")}
    traceability, faithfulness = check_claims(claims, plan, parse_sources(PLAN), "Category: 480 million euros.", pages)

    assert [i["traced"] for i in traceability["items"]] == [True, True, False, False, False]
    assert traceability["items"][4]["refs"] == []
    assert (traceability["claims"], traceability["traced"], traceability["unquoted"]) == (5, 2, 1)
    assert traceability["score"] == pytest.approx(0.4)
    assert [f["status"] for f in faithfulness["items"]] == ["document", "source", "not found", "not found", "not found"]
    assert faithfulness["score"] == pytest.approx(0.4)


def test_unreadable_page_makes_a_figure_unverifiable():
    plan = "Plant-based products make up 18% [2].\n\n## Sources\n\n2. <https://example.com/ok>\n"
    pages = {"https://example.com/ok": Page("https://example.com/ok", "unreadable", detail="HTTP 403")}
    claim = Claim(quote="Plant-based products make up 18%", figures=["18%"], refs=["2"])
    traceability, faithfulness = check_claims([claim], plan, parse_sources(plan), "", pages)
    assert traceability["traced"] == 1  # the page exists: the source is valid
    assert faithfulness["unverifiable"] == 1 and faithfulness["checked"] == 0 and faithfulness["score"] is None


# ── source pages ────────────────────────────────────────────────────────────────────────

class _Pages(BaseHTTPRequestHandler):
    routes = {"/page": (200, "text/html; charset=utf-8",
                        "<html><script>var x = 99;</script><p>Share: 18&nbsp;%</p></html>"),
              "/gone": (404, "text/html", ""), "/blocked": (403, "text/html", ""),
              "/file.pdf": (200, "application/pdf", "%PDF")}

    def do_GET(self):
        code, kind, body = self.routes[self.path]
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *_args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_fetch_page_statuses(server):
    page = fetch_page(f"{server}/page")
    assert page.status == "ok" and "18" in page.text and "99" not in page.text  # scripts are dropped
    assert fetch_page(f"{server}/gone").status == "broken"
    assert fetch_page(f"{server}/blocked").status == "unreadable"
    assert fetch_page(f"{server}/file.pdf").status == "unreadable"
    assert fetch_page("http://no-such-host.invalid/x").status == "broken"


# ── baseline and evaluate() ─────────────────────────────────────────────────────────────

@pytest.fixture
def document(tmp_path):
    path = tmp_path / "company.md"
    path.write_text(STATE["document_text"])
    return path


def test_baseline_writes_a_run_folder(monkeypatch, document, tmp_path):
    model = install(monkeypatch, FakeModel())
    out = run_baseline(document, tmp_path / "baseline")
    record = json.loads((out / "run.json").read_text())
    assert record["system"] == "baseline" and record["status"] == "done" and record["error"] is None
    assert "Launch plan" in (out / "blueprint.md").read_text()
    assert STATE["document_text"][:200] in model.prompts["baseline"][0]  # the whole document, one prompt


def test_baseline_failure_is_recorded(monkeypatch, document, tmp_path):
    from eval import baseline

    monkeypatch.setattr(baseline, "get_llm", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no key")))
    out = run_baseline(document, tmp_path / "baseline")
    record = json.loads((out / "run.json").read_text())
    assert record["status"] == "failed" and "no key" in record["error"]
    assert "Traceback" in (out / "log.txt").read_text()
    assert evaluate(out, "doc")["error"] == "RuntimeError: no key"


def test_evaluate_scores_both_systems_the_same_way(monkeypatch, document, tmp_path):
    model = install(monkeypatch, FakeModel())
    run = Run(document, settings=SETTINGS, run_id="ma")
    list(run.advance())
    run.answer({"approved": True})
    list(run.advance())
    multi = evaluate(run.dir, run.document_text, trap="Students: 1% of adults")
    base = evaluate(run_baseline(document, tmp_path / "b"), run.document_text)

    assert json.loads((run.dir / "metrics.json").read_text()) == multi
    assert multi["system"] == "multi_agent" and base["system"] == "baseline"
    # Each plan contains only its own fake claim; the other is left out
    assert (multi["traceability"]["claims"], multi["traceability"]["unquoted"]) == (1, 1)
    assert base["traceability"]["items"][0] == {"quote": BASELINE_CLAIM, "refs": ["1"], "valid_refs": 1, "traced": True}
    assert base["faithfulness"]["items"][0]["status"] == "not found"  # 27% is not in the fixture document
    assert [s["status"] for s in base["sources"]] == ["document", "ok"]
    # The judge never sees the validation log, and gets the trap only when the case has one
    coherence_prompts = model.prompts["CoherenceVerdict"]
    assert "Validation log" not in coherence_prompts[0] and "<trap_segment>" in coherence_prompts[0]
    assert "<trap_segment>" not in coherence_prompts[1]
    assert multi["trap"] == {"applies": True, "segment": "Students: 1% of adults", "target": "SEG1", "avoided": True}
    assert base["trap"]["avoided"] is None
    assert scores(multi)["coherence_strategy"] == 4 and scores(multi)["tokens"] == 0


# ── human rating ────────────────────────────────────────────────────────────────────────

def test_rating_sheet_is_blind_and_aggregated(tmp_path):
    plans = {}
    for case in ("c1", "c2"):
        (tmp_path / case).mkdir()
        multi, base = tmp_path / case / "multi.md", tmp_path / case / "base.md"
        multi.write_text(PLAN.replace("## 1. Executive", "*Approved by the company at step*\n\n## 1. Executive"))
        base.write_text("# My plan\n\n## 1. Executive summary\n\nBaseline.\n")
        plans[case] = {"multi_agent": multi, "baseline": base}
    out = tmp_path / "rating"
    key = rating.write_sheet(plans, out, seed=1)

    for case, labels in key.items():
        assert sorted(labels) == ["X", "Y"] and sorted(labels.values()) == ["baseline", "multi_agent"]
        texts = [(out / f"{case}_{label}.md").read_text() for label in "XY"]
        assert all(t.startswith(f"# Launch plan: {case}") for t in texts)
        assert not any("Validation log" in t or "Approved by" in t for t in texts)
    assert rating.read_ratings(out) is None  # nobody has rated yet

    rows = list(csv.DictReader((out / "rating_sheet.csv").open()))
    assert len(rows) == 4
    for rater, score in (("ana", "5"), ("bo", "2")):
        with (out / "ratings" / f"{rater}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            for row in rows:
                system = key[row["case"]][row["plan"]]
                writer.writerow({**row, "rater": rater, **{q: score if system == "multi_agent" else "3"
                                                           for q, _ in rating.RUBRIC}})
    result = rating.read_ratings(out)
    assert result["raters"] == ["ana", "bo"]
    assert result["averages"]["multi_agent"]["usefulness"] == 3.5
    assert result["averages"]["baseline"]["clarity"] == 3
    assert {d["system"] for d in result["disagreements"]} == {"multi_agent"}
    assert len(result["disagreements"]) == 2 * len(rating.RUBRIC)


# ── runner and report ───────────────────────────────────────────────────────────────────

def test_run_case_and_report(monkeypatch, document, output_dir):
    install(monkeypatch, FakeModel())
    case = {"id": "fake", "document": str(document), "category": "Coffee", "country": "Italy",
            "trap": "Students: 1% of adults"}
    entry = run_case(case, output_dir / "eval_test", SETTINGS)
    assert {p.name for p in (output_dir / "eval_test" / "fake" / "multi_agent").iterdir()} == {
        "blueprint.md", "state.json", "run.json", "log.txt", "metrics.json"}
    assert entry["baseline"]["metrics"]["traceability"]["score"] == 1.0

    results = {"updated": "2026-11-04T10:00:00", "model": "m", "judge_model": "j", "cases": {"fake": entry}}
    report = render_report(results)
    assert "| Traceability: claims with a valid source | 0% | 100% |" in report
    assert "| Trap avoided (trap cases) | 1/1 | 1/1 |" in report
    assert "| fake | Single prompt | 100% |" in report
    assert "Pending: the blind pairs" in report

    ratings = {"raters": ["ana"], "averages": {"multi_agent": {"usefulness": 4.0}, "baseline": {"usefulness": 3.0}},
               "disagreements": []}
    report = render_report(results, ratings, "- The pipeline avoided the trap.")
    assert "| usefulness: " in report and "| 4.0 | 3.0 |" in report
    assert "- The pipeline avoided the trap." in report


def test_failed_run_is_reported(monkeypatch, document, output_dir):
    install(monkeypatch, FakeModel())
    from eval import baseline

    monkeypatch.setattr(baseline, "get_llm", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rate limited")))
    case = {"id": "fake", "document": str(document), "category": "Coffee", "country": "Italy", "trap": None}
    entry = run_case(case, output_dir / "eval_test", SETTINGS)
    report = render_report({"updated": "2026-11-04T10:00:00", "model": "m", "judge_model": "j",
                            "cases": {"fake": entry}})
    assert "| fake | Single prompt | failed: RuntimeError: rate limited |" in report
    # A case with a failed system is left out of the averages
    assert "Cases where both systems ran and were evaluated: 0 of 1." in report
    assert "| Tokens per run | — | — |" in report


def test_evaluation_error_does_not_stop_the_case(monkeypatch, document, output_dir):
    install(monkeypatch, FakeModel())
    monkeypatch.setattr(metrics, "extract_claims", lambda *_a: (_ for _ in ()).throw(RuntimeError("judge down")))
    case = {"id": "fake", "document": str(document), "category": "Coffee", "country": "Italy", "trap": None}
    entry = run_case(case, output_dir / "eval_test", SETTINGS)
    assert [entry[s]["metrics"]["error"] for s in ("multi_agent", "baseline")] == [
        "evaluation failed: RuntimeError: judge down"] * 2
    assert "| fake | Multi-agent | failed: evaluation failed" in render_report(
        {"updated": "2026-11-04T10:00:00", "model": "m", "judge_model": "j", "cases": {"fake": entry}})


# ── Phase 14: repeated judge, providers, kept runs ──────────────────────────────────────

def test_repeated_judge_gives_mean_spread_and_majority(monkeypatch, tmp_path):
    runs = iter([(0.8, 4, True), (0.9, 4, True), (0.7, 3, False)])

    def fake_evaluate(out_dir, *_a, **_k):
        trace, coherence, avoided = next(runs)
        return {"traceability": {"score": trace}, "faithfulness": {"score": 1.0},
                "coherence": {"strategy_vs_analysis": {"score": coherence}, "campaign_vs_strategy": {"score": 4}},
                "trap": {"avoided": avoided}, "cost": {"total_tokens": 100, "seconds": 5},
                "eval_tokens": {"haiku": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11}}}

    monkeypatch.setattr(metrics, "evaluate", fake_evaluate)
    m = metrics.evaluate_repeated(tmp_path, "doc", runs=3)
    assert len(m["judge_runs"]) == 3
    s = scores(m)
    assert s["traceability"] == pytest.approx(0.8) and s["coherence_strategy"] == pytest.approx(11 / 3)
    assert s["trap_avoided"] is True and s["tokens"] == 100  # majority verdict; the system's own cost
    assert metrics.spread(m)["traceability"] == (0.7, 0.9) and "faithfulness" not in metrics.spread(m) or \
        metrics.spread(m)["faithfulness"] == (1.0, 1.0)
    assert m["eval_tokens"]["haiku"]["total_tokens"] == 33
    assert json.loads((tmp_path / "metrics.json").read_text())["judge_mean"] == m["judge_mean"]


def test_repeated_judge_fetches_each_page_once(monkeypatch, tmp_path):
    fetched = []
    monkeypatch.setattr(metrics, "fetch_page", lambda url: fetched.append(url) or Page(url, "ok", "x"))
    cache = {}
    metrics.fetch_pages(["https://a.example", "https://b.example"], cache=cache)
    metrics.fetch_pages(["https://a.example"], cache=cache)
    assert fetched == ["https://a.example", "https://b.example"]


def test_main_runs_a_preset_judged_by_anthropic_and_keeps_the_runs(monkeypatch, document, output_dir, tmp_path):
    from eval import run_eval

    install(monkeypatch, FakeModel())
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_JUDGE_MODEL", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-x")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    case = {"id": "fake", "document": str(document), "category": "Coffee", "country": "Italy", "trap": None}
    monkeypatch.setattr(run_eval, "load_cases", lambda: [case])
    for name in ("RESULTS", "REPORT", "FINDINGS"):
        monkeypatch.setattr(run_eval, name, tmp_path / getattr(run_eval, name).name)
    monkeypatch.setattr(run_eval, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(run_eval.rating, "read_ratings", lambda: None)
    sheets = []
    monkeypatch.setattr(run_eval.rating, "write_sheet", lambda plans: sheets.append(plans))

    run_eval.main(["--provider", "gemini", "--judge-runs", "2"])
    results = json.loads((tmp_path / "results.json").read_text())
    entry = results["presets"]["gemini"]["fake"]
    assert results["cases"] == {} or "fake" not in results["cases"]
    assert entry["settings"]["provider"] == "gemini"
    assert entry["judge"] == {"model": "anthropic:claude-haiku-5-5", "runs": 2}
    assert entry["multi_agent"]["metrics"]["judge_model"] == "anthropic:claude-haiku-5-5"
    assert len(entry["multi_agent"]["metrics"]["judge_runs"]) == 2
    assert (tmp_path / "runs" / "gemini" / "fake" / "multi_agent" / "blueprint.md").exists()
    assert sheets == []  # the blind rating is for the reference preset only

    run_eval.main(["--judge-runs", "1"])  # the reference preset: main results, rating sheet, both sections
    results = json.loads((tmp_path / "results.json").read_text())
    assert results["provider"] == "anthropic" and "fake" in results["cases"] and len(sheets) == 1
    report = (tmp_path / "report.md").read_text()
    assert "## Other presets (same judge)" in report and "| fake | gemini | Multi-agent |" in report


def test_score_examples_writes_the_baseline_and_both_metrics(monkeypatch, document, output_dir, tmp_path):
    from eval import score_examples

    install(monkeypatch, FakeModel())
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_JUDGE_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    run = Run(document, settings=SETTINGS, run_id="ex")
    list(run.advance())
    run.answer({"approved": True})
    list(run.advance())
    record = json.loads((run.dir / "run.json").read_text())
    record["document"] = str(document)  # absolute: ROOT / absolute path is the path itself
    (run.dir / "run.json").write_text(json.dumps(record))
    out = score_examples.score(run.dir, SETTINGS, judge_runs=2)
    assert (run.dir / "baseline" / "blueprint.md").exists()
    assert len(out["multi_agent"]["judge_runs"]) == 2 and len(out["baseline"]["judge_runs"]) == 2
    assert json.loads((run.dir / "metrics.json").read_text())["judge_mean"]
