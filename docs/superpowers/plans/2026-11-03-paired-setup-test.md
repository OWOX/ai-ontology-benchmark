# Paired setup test

Spec: this plan, plus the owner's decisions of 2026-11-03 below. Specs to update: `docs/specs/evaluate.md`, `docs/specs/report.md`. Term to define first: `docs/definitions.md`.

## Owner decisions (binding)

1. Paired unit is the input. For one input and one setup, its share is hits ÷ attempts that are not `infrastructure_failure`. Two setups are compared on the inputs that have at least one such attempt under both.
2. Test: exact two-sided sign test on the inputs whose shares differ (ties dropped). With 1 attempt per input it equals the exact McNemar test.
3. Metrics tested: success rate (valid and invalid inputs, separately), hallucination rate (valid and invalid, separately), mismatch detection rate (invalid only).
4. Holm correction over the 3 setup pairs, within one AI model × puzzle × validity × metric.
5. Pooled over scramble depths. Valid and invalid are never pooled.
6. No new dependency: use `math.comb`.
7. Releasing 1.3.2 is a separate PR after this merges. Not in this plan.

## Global constraints

1. AGENTS.md invariants hold. Nothing is stored in raw records. Metric computed only by `evaluate`.
2. `compute()` keeps its signature and return value (the UI in `ui/expdata.py` uses `group_metrics`, and evaluate unpacks 3 values). The new test is a separate function.
3. Oxford English, British -ize spelling, Oxford comma, numbered lists in docs.
4. Every script starts with its spec link comment (already there).
5. No AI model names in code. No Claude attribution anywhere.
6. Tests: `.venv/bin/python -m pytest -q tests/test_evaluate.py tests/test_report.py` (pytest is single-process here; do not add xdist).
7. One change per commit.

## Task 1: Define the paired setup test in docs

Files: `docs/definitions.md`, `docs/methodology.md`, `docs/specs/evaluate.md`, `docs/specs/report.md`. Docs only, no code.

1. `docs/definitions.md`, section `## Metrics`: append item 12, **Paired setup test.** Write it from owner decisions 1–5: for one AI model, puzzle, validity label, and metric, compares two setups on the same inputs; per-input share; exact two-sided sign test on inputs whose shares differ; reports inputs paired, inputs where each setup is higher, mean share difference (second setup minus first), p-value, and Holm-adjusted p-value over the three setup pairs; significant when the Holm-adjusted p-value is below 0.05. State why: every setup sees the same inputs (invariant 6), so pairing removes input difficulty from the comparison, and using the input as the unit keeps repeated attempts on one input from counting as independent. p-value is `n/a` when no input is paired; with no discordant inputs it is 1.0.
2. `docs/methodology.md`, section `## Measurement`: add one sentence after the numbered list: setups are compared with the [paired setup test](definitions.md#metrics) on the same inputs.
3. `docs/specs/evaluate.md`:
   1. In Outputs, add item: `paired_tests(attempt_rows) -> paired_rows` in `metrics.py`, one row per AI model, puzzle, validity, metric, and setup pair, with columns `model, puzzle, validity, metric, setup_a, setup_b, inputs_paired, a_higher, b_higher, mean_difference, p_value, p_holm, significant`. `metric` is one of `success_rate`, `hallucination_rate`, `mismatch_detection_rate` (invalid only). Setup pairs in `SETUPS` order: (no_model, descriptive), (no_model, prescriptive), (descriptive, prescriptive). `mean_difference` is the mean over paired inputs of share_b − share_a. Rows sorted by AI model (config order), puzzle, validity (valid first), metric (the order above), pair. `significant` is `p_holm < 0.05`; `n/a` cells when `inputs_paired` is 0, and such rows are left out of the Holm family.
   2. Add output `results/<ID>/<VERSION>.paired.csv` with `paired_rows`, same CSV conventions as the metrics CSV.
   3. Holm: sort the family's p-values ascending; adjusted p_(i) = max over j ≤ i of min(1, (m − j + 1) × p_(j)), with m the family size.
   4. How to test, add:
      1. Sign test: 8 vs 2 discordant gives p = 0.109375 (exact); 0 vs 0 gives 1.0; 10 vs 0 gives 0.001953125.
      2. Holm on (0.01, 0.04, 0.03) gives (0.03, 0.06, 0.06).
      3. An input with attempts only under one setup, or only infrastructure failures under one, is not paired.
      4. Two attempts on one input count as one paired input (share 0.5 vs 1.0 is one discordant input).
      5. Valid inputs get no `mismatch_detection_rate` rows.
4. `docs/specs/report.md`: add a section **Setup comparison** between Summary and Metrics: for each AI model, one table per puzzle with columns Validity, Metric, Setups (`a vs b`), Inputs paired, A higher, B higher, Mean difference (2 places), p (3 places), Holm p (3 places), Significant (`yes`/`no`/`n/a`). One sentence above the tables linking the definition. `write_report` gains a keyword argument `paired_rows=()`; with none, the section is absent. Add a How-to-test item for it.

Commit: `Define the paired setup test`.

## Task 2: Compute the paired setup test in evaluate

Files: `src/evaluate/metrics.py`, `src/evaluate/evaluate.py`, `tests/test_evaluate.py`.

1. In `metrics.py` add `sign_test(a: int, b: int) -> float`, `holm(p_values: list[float]) -> list[float]`, and `paired_tests(attempt_rows: list[dict], models: list[str] | None = None) -> list[dict]` exactly as the evaluate spec (Task 1 item 3) says. Hit per metric: success_rate → `outcome == "success"`; hallucination_rate → `outcome == "hallucination"`; mismatch_detection_rate → `mismatch` true. Skip `infrastructure_failure` attempts. Use `SETUPS` from `src.run.prompts` for pair order and `NA` for n/a cells.
2. In `evaluate.py`, call `paired_tests(attempt_rows, names)` after `compute`, write `<VERSION>.paired.csv` beside the metrics CSV with the same CSV helper style (do not pass it to `write_report` yet; Task 3 adds that argument). Update the module docstring's list of written files.
3. Tests in `tests/test_evaluate.py` for every How-to-test item added in Task 1 item 3.4, plus that evaluate writes the paired CSV and two runs are byte-identical (extend the existing determinism test if there is one).

Commit: `Compute the paired setup test in evaluate`.

## Task 3: Show the setup comparison in the report

Files: `src/evaluate/report.py`, `tests/test_report.py`, and the stored expected report fixture the test compares against.

1. Add `comparison_section(config, paired_rows)` per the report spec (Task 1 item 4) and call it from `write_report` between summary and metrics, only when `paired_rows` is non-empty. `write_report` gains `paired_rows=()` as its last keyword argument, and `evaluate.py` now passes `paired_rows=paired_rows` to it (add `src/evaluate/evaluate.py` to this task's files).
2. Tests: the section is absent with no paired rows; with rows it renders the columns above; update the stored expected file only by regenerating it from the fixture and checking the diff is just the new section.

Commit: `Show the setup comparison in the report`.
