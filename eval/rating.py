"""Blind human rating (Phase 10): the two plans of each case, labelled X and Y at random.

    eval/rating/README.md          rubric and instructions for the raters
    eval/rating/<case>_X.md        one plan of the pair (the other is <case>_Y.md)
    eval/rating/rating_sheet.csv   empty sheet: each rater copies it to ratings/<name>.csv
    eval/rating/key.json           which label is which system: raters must not open it

The multi-agent blueprint loses its validation log and the approval line before rating,
so the format alone does not give it away.
"""

import csv
import json
import random
import re
from pathlib import Path
from statistics import mean

from eval.metrics import split_sections

RATING_DIR = Path(__file__).resolve().parent / "rating"
RUBRIC = [
    ("usefulness", "Could the company act on this plan as it is, without redoing the work?"),
    ("evidence", "Are the important figures and claims supported by sources you could check?"),
    ("target", "Is the target segment a sensible choice, given the document's figures and goals?"),
    ("coherence", "Do the strategy and the campaign follow from the analysis?"),
    ("clarity", "Is the plan clear, well organised and easy to read?"),
]
SYSTEMS = ("multi_agent", "baseline")


def blind_copy(markdown: str, case_id: str) -> str:
    """The plan without the parts only the multi-agent system writes."""
    kept = "".join(f"## {h}\n{t}" if h else t for h, t in split_sections(markdown) if "validation log" not in h.lower())
    kept = re.sub(r"^\*Approved by the company.*\n?", "", kept, flags=re.M)
    kept = re.sub(r"^## \d+\. Sources", "## Sources", kept, flags=re.M)
    return re.sub(r"\A\s*# .*", f"# Launch plan: {case_id}", kept, count=1)


def write_sheet(plans: dict[str, dict[str, Path]], out_dir: Path = RATING_DIR, seed: int | None = None) -> dict:
    """plans: {case_id: {"multi_agent": blueprint path, "baseline": blueprint path}}. Returns the key."""
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ratings").mkdir(exist_ok=True)
    key = {}
    for case_id, paths in plans.items():
        labels = ["X", "Y"]
        rng.shuffle(labels)
        key[case_id] = dict(zip(labels, SYSTEMS))
        for label, system in key[case_id].items():
            (out_dir / f"{case_id}_{label}.md").write_text(blind_copy(paths[system].read_text(), case_id))
    (out_dir / "key.json").write_text(json.dumps(key, indent=2))
    with (out_dir / "rating_sheet.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rater", "case", "plan", *(name for name, _ in RUBRIC), "comment"])
        for case_id in plans:
            for label in ("X", "Y"):
                writer.writerow(["", case_id, label, *([""] * len(RUBRIC)), ""])
    questions = "\n".join(f"{i}. **{name}**: {text}" for i, (name, text) in enumerate(RUBRIC, 1))
    (out_dir / "README.md").write_text(
        "# Blind rating of the launch plans\n\n"
        "Each case has two plans, `<case>_X.md` and `<case>_Y.md`, written by two different systems. "
        "Do not open `key.json`, and do not compare notes before everyone has rated.\n\n"
        "1. Copy `rating_sheet.csv` to `ratings/<your name>.csv` and write your name in the `rater` column.\n"
        "2. For each case, read the company document (`eval/cases/cases.json` gives its path), then both plans.\n"
        "3. Score each plan from 1 (poor) to 5 (excellent) on every question. A short comment helps the findings.\n\n"
        f"## Questions\n\n{questions}\n\n"
        "When all raters are done: `uv run python -m eval.run_eval --report-only` adds the scores to "
        "`eval/report.md`.\n"
    )
    return key


def read_ratings(out_dir: Path = RATING_DIR) -> dict | None:
    """Averages per system and question, and the plans where raters disagree by 2 points or more."""
    key_path = out_dir / "key.json"
    files = sorted((out_dir / "ratings").glob("*.csv")) if (out_dir / "ratings").is_dir() else []
    if not key_path.exists() or not files:
        return None
    key = json.loads(key_path.read_text())
    scores: dict[tuple[str, str, str], list[tuple[str, int]]] = {}  # (case, system, question) -> [(rater, score)]
    raters = set()
    for path in files:
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                system = key.get(row.get("case", ""), {}).get(row.get("plan", ""))
                rater = row.get("rater") or path.stem
                for name, _ in RUBRIC:
                    if system and (row.get(name) or "").strip().isdigit():
                        scores.setdefault((row["case"], system, name), []).append((rater, int(row[name])))
                        raters.add(rater)
    if not scores:
        return None
    pooled: dict[str, dict[str, list[int]]] = {}
    for (_, system, question), vals in scores.items():
        pooled.setdefault(system, {}).setdefault(question, []).extend(v for _, v in vals)
    averages = {system: {q: mean(v) for q, v in questions.items()} for system, questions in pooled.items()}
    disagreements = [{"case": c, "system": s, "question": q, "scores": dict(vals)}
                     for (c, s, q), vals in sorted(scores.items())
                     if max(v for _, v in vals) - min(v for _, v in vals) >= 2]
    return {"raters": sorted(raters), "averages": averages, "disagreements": disagreements}
