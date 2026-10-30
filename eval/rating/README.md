# Blind rating of the launch plans

Each case has two plans, `<case>_X.md` and `<case>_Y.md`, written by two different systems. Do not open `key.json`, and do not compare notes before everyone has rated.

1. Copy `rating_sheet.csv` to `ratings/<your name>.csv` and write your name in the `rater` column.
2. For each case, read the company document (`eval/cases/cases.json` gives its path), then both plans.
3. Score each plan from 1 (poor) to 5 (excellent) on every question. A short comment helps the findings.

## Questions

1. **usefulness**: Could the company act on this plan as it is, without redoing the work?
2. **evidence**: Are the important figures and claims supported by sources you could check?
3. **target**: Is the target segment a sensible choice, given the document's figures and goals?
4. **coherence**: Do the strategy and the campaign follow from the analysis?
5. **clarity**: Is the plan clear, well organised and easy to read?

When all raters are done: `uv run python -m eval.run_eval --report-only` adds the scores to `eval/report.md`.
