# Mismatch reasons, answer classes, and per-puzzle depths

Spec: `docs/definitions.md`, `docs/methodology.md`, `AGENTS.md`, and the specs in `docs/specs/` as of commit `52b5bbbe` on branch `docs/mismatch-reason`. The specs are the authority. This plan only orders the work.

## Global constraints

1. Build to the spec. If code has to differ, change the spec in the same commit and say so in the report.
2. Every script starts with a comment linking its spec. Names in code follow `docs/definitions.md`.
3. Releases without mismatch reasons (every manifest before this work, read as `mismatch_reasons` false) keep their exact behaviour: bare `MISMATCH`, the single `mismatch` decision option, decision hallucination flag `None`. Tests for the old behaviour stay and pass.
4. No AI model names in code. No Claude attribution anywhere, including commit trailers.
5. British spelling with -ize endings, Oxford comma.
6. Small commits, one change each.
7. Run tests with `/Users/flakss/Projects/ai-ontology-hallucination-research/.venv/bin/python -m pytest -q` from the worktree root. Never run more than 4 workers.
8. Never edit anything under `releases/` or `results/`.

## Task 1: Engine reasons and validator

Files: `src/puzzles/engine.py`, `src/puzzles/cube.py`, `src/validator.py`, `tests/test_engine.py`, `tests/test_cube.py`, `tests/test_validator.py`.

1. Add `mismatch_reasons()` and `decoy_reasons()` to `Engine` (AGENTS.md interface items 10 and 11, `docs/specs/engine.md`) and to `CubeEngine` (`docs/specs/cube.md` items 10 and 11). The cube list is the six corruption types in `CORRUPTION_TYPES` order, then `twisted centre`, on every size.
2. Validator (`docs/specs/validator.md`): `offered_reasons(engine)`, the `reasons` argument, the new `Verdict` fields (`mismatch_reason`, `impossible_move`, `decoy`), MISMATCH line and decorated MISMATCH line rules, decoy as hallucination, the decision path with `mismatch_<n>` choices, and `read_decision_call(call, legal, reasons=None)` returning the text-model line.
3. Every row of the spec's test table, run as the table's last paragraph says.

## Task 2: Prompts, templates, and release manifest

Files: `src/run/prompts.py`, `prompts/*/*.txt`, `src/release/release.py`, `tests/test_prompts.py`, `tests/test_release.py`.

1. `docs/specs/prompts.md`: the `{mismatch_reasons}` placeholder, `fill_template`, `uses_mismatch_reasons`, `decision_questions(questions, legal, reasons=None)`, and `decision_prompt_versions` passing reasons.
2. In all twelve LLM templates, replace the closing MISMATCH line with the spec's "After" line exactly. `prompts/decision/questions.txt` keeps its keys and text.
3. `docs/specs/release.md`: write `mismatch_reasons` to the manifest, the patch-bump rule, and test 14.

## Task 3: Per-puzzle depths, generate, and run

Files: `src/config.py`, `src/generate/generate.py`, `src/run/run.py`, `src/run/decision.py`, `src/run/raw.py`, `src/run/progress.py`, `src/run/budget.py` (if it reads depths or max moves), `config/release.toml`, and their tests.

1. `docs/specs/config.md`: `scramble_depths` as a list or a per-puzzle table, `depths_for`, and `max_moves(config, release_config, puzzle)`. Update every caller.
2. `docs/specs/generate.md`: per-puzzle depths.
3. `docs/specs/run.md`: check 9 (manifest `mismatch_reasons` passed to the validator and to `decision_questions`), the decision loop ending on mismatch choices, the `mismatch_reason` record field, and the progress precision in place of the success rate. Precision in progress uses `answer_class` once Task 4 adds it; until then compute it with a small local helper that Task 4 replaces.
4. `config/release.toml`: `scramble_count = 40`, `valid_invalid_split = 0.25`, and the per-puzzle table: 2x2 and 3x3 `[5, 10, 20]`, 4x4 `[10, 20, 40]`, 5x5 `[15, 30, 60]`. Leave `seed` alone; the release step sets it.

## Task 4: Metrics and evaluate

Files: `src/evaluate/metrics.py`, `src/evaluate/evaluate.py`, `tests/test_evaluate.py`, and `src/run/progress.py` if it should now call `answer_class`.

`docs/specs/evaluate.md` in full: `answer_class`, `precision`, `coverage`, `hallucination_rate` on `impossible_move`, `reason_hallucination_rate`, `diagnosis_rate`, `cost_per_attempt` in place of `cost_per_success`, the paired test on precision, the extended `detection_rows` (critical thinking, fixed answer, balanced precision, coverage, cost efficiency), `corruption_rows` diagnosis, `reason_rows`, and `reasons.csv`. Remove `success_rate` and `cost_per_success`. Tests 1 to 27.

## Task 5: Report

Files: `src/evaluate/report.py`, `tests/test_report.py`, and the stored expected report fixture.

`docs/specs/report.md` in full: the headline table, the new Summary rows, the Mismatch detection columns and baseline rows, the Detection by corruption type diagnosis column, the Mismatch reasons section, and the mismatch reason column in Attempts.

## Task 6: UI

Files: `ui/pooling.py`, `ui/benchmarks.py`, `ui/static/expmetrics.js`, `ui/static/pages/experiments.js`, `ui/static/pages/benchmarks.js`, and their tests.

`docs/specs/ui.md`: precision in place of the success rate and cost efficiency in place of cost per success, with the pooling the spec describes. An old report CSV without the new columns shows `n/a`, never an error.
