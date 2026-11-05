# Methodology fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the measurement problems found in the 1.3.x results so that hallucination, mismatch detection, truncation, and setup effects are measured fairly before the held-out run on release 2.0.0.

**Architecture:** The validator gains three outcomes (`truncated`, `abstention`, `format_error`) and decides impossible moves by a new engine method `is_move_token()`. Evaluate replaces Wilson intervals with a bootstrap over inputs, adds balanced accuracy for mismatch detection and detection by corruption type, and drops efficiency. Run gains one config parameter, `reasoning_effort`, mapped to each provider's own parameter. The cube engine gains new corruption types.

**Tech Stack:** Python 3.11+, pytest, the provider SDKs already in `pyproject.toml`. No new dependency.

**Spec:** this plan, plus the owner's decisions of 2026-11-04 below. Each task changes the specs and docs it touches in the same commit (AGENTS.md: "If the code needs to differ from the spec, change the spec in the same pull request").

## Owner decisions (binding, 2026-11-04)

1. Item 1: an impossible move is a move-shaped token that is not a legal move. Prose and refusals in text become outcome `abstention`; legal moves in the wrong layout become `format_error`. This changes invariant 9, which the owner approved.
2. Item 1: the move-shape grammar lives in the engine, as a new interface method `is_move_token(token)`.
3. Item 2: mismatch detection is reported as balanced accuracy, with an "always MISMATCH" baseline row. A refusal ("I can't derive a solving sequence") is **not** a mismatch: of 37 such responses in 1.3.x, 35 were on valid inputs.
4. Item 3: `truncated` is its own outcome. Every model runs at reasoning effort `medium`. `max_output_tokens` stays 32000.
5. Item 4: setups stay as they are.
6. Item 5: confidence intervals come from a bootstrap over inputs. The paired setup test (sign test plus Holm) already exists and stays. A power analysis goes in the methodology.
7. Item 6: log why infrastructure failures happen, so the OpenAI failures can be diagnosed. Gaps get filled by running every model on release 2.0.0, which is not in this plan.
8. Item 7: input set 1 becomes the development set; release 2.0.0 gets a fresh, held-out input set. Releasing is separate PRs after this merges.
9. Item 8: add corruption types and report detection by corruption type.
10. Item 9: drop efficiency entirely: no reference solver, no `reference_length()`, no efficiency metric. Optimal or near-optimal solvers don't exist in practice for 5x5 and the other puzzles.
11. Item 10: a decision model's hallucination flag is stored as `null`, not `false`, and its hallucination rate is reported as n/a.

## Global Constraints

1. AGENTS.md invariants hold except where the decisions above change them; Task 1 and Task 2 edit invariant 9, 12, 13 text and the engine interface list accordingly.
2. Nothing new is stored in raw records except the decision-model hallucination value `null`. Metrics are computed only by `evaluate`.
3. Oxford English, British spelling with -ize endings, Oxford comma, numbered lists in docs.
4. Every script starts with its spec link comment (already there; keep it).
5. No AI model names in code. No Claude attribution anywhere (no Co-Authored-By trailer, no "Generated with" line).
6. One change per commit. Commit messages are plain sentences in the repo's style (see `git log --oneline`), no `feat:` prefix.
7. Tests: `.venv/bin/python -m pytest -q` (single process; never add xdist; the machine overheats). JS tests run through `tests/test_ui_js.py`.
8. Define a term in `docs/definitions.md` before using it anywhere else.
9. `compute()` in `src/evaluate/metrics.py` keeps returning `(attempt_rows, metric_rows, summary_rows)`; `ui/expdata.py` and `ui/pooling.py` depend on it.
10. No new dependency (`pyproject.toml` unchanged).

## Review Focus

1. Prose that happens to contain a move-shaped word (for example "R2 would not help here." or "Use an x rotation"): the line is prose, so the attempt is `abstention`, never `hallucination`. Test in Task 2.
2. `MISMATCH` followed by an explanation line: `format_error` with the mismatch flag off, not `abstention` and not `hallucination`. Test in Task 2.
3. Old raw records (1.x) with `hallucination: false` from decision models, and with `stop_reason: truncated`: evaluate re-validates them and must give `truncated` and n/a hallucination with no error. Test in Task 3.
4. A bootstrap group with a single input: low and high are n/a, not a zero-width interval. Test in Task 5.
5. An experiment config written before `reasoning_effort` existed (every config in `results/*/experiment.toml` today): it still parses, and the report says "provider default". Test in Task 7.

---

### Task 1: Drop efficiency and the reference solver; add `is_move_token()` to the engine interface

**Files:**
- Modify: `src/puzzles/engine.py` (replace abstract `reference_length` with abstract `is_move_token`)
- Modify: `src/puzzles/cube.py` (delete `_search_tables`, `_fix_dbl_corner`, `_ida_star_2x2`, `reference_length`, and the `lru_cache` import if unused; add `is_move_token`)
- Modify: `src/evaluate/metrics.py` (delete `efficiency`, `reference_length`, the `cache` argument plumbing, `reference_length` attempt-row field, `out["efficiency"]`)
- Modify: `src/evaluate/report.py` (drop the Efficiency column from `metrics_section` and `metric_line`)
- Modify: `ui/` files that show efficiency, if any (`grep -rn efficiency ui`)
- Modify: `tests/test_engine.py`, `tests/test_cube.py`, `tests/test_evaluate.py`, `tests/test_report.py`, `tests/fixtures/report_expected.md`, `tests/fixtures/pipeline-1.0.0.md`
- Docs: `AGENTS.md` (Puzzle engine interface item 9; Open item 2; invariant 12 drops "including anything that depends on the reference solver"), `docs/definitions.md` (delete Reference solver, Reference length, Efficiency; renumber; Baseline section becomes "Prices"; add **Move token** under Puzzles), `docs/assumptions.md` (delete item 6, renumber), `docs/specs/engine.md`, `docs/specs/cube.md`, `docs/specs/evaluate.md`, `docs/specs/report.md`, `docs/methodology.md` if it mentions efficiency.

**Interfaces:**
- Produces: `Engine.is_move_token(self, token: str) -> bool`. Used by the validator in Task 2.

**Definition text to add to `docs/definitions.md` (Puzzles, after Legal move):**

> **Move token.** A string written in the shape of a move in the puzzle's notation, whether or not the puzzle allows it, as decided by the engine's `is_move_token()`. For the cubes that is an optional layer count, a face or slice letter in upper or lower case or a rotation letter, an optional `w`, and an optional `'` or `2` or both, for example `R`, `r'`, `Rw2`, `3Fw`, `M`, `x2`, and `R2'`. Every legal move is a move token. A move token that isn't a legal move is an impossible move.

Update **Impossible move** to: "A move token an AI model returns that isn't a legal move for that puzzle. A move that exists on another puzzle but not on this one is impossible here. Prose is not an impossible move: see [abstention](#attempts-and-outcomes)."

AGENTS.md interface item 9 becomes: "`is_move_token(token)` returns true when the token has the shape of a move in the puzzle's notation, whether or not it is legal. The validator uses it only to tell impossible moves from prose; legality is still decided by exact match against `legal_moves()`." Open item 2 becomes: "Resolved: no reference solver. Efficiency was dropped on 2026-11-04, because optimal solvers aren't practical for 5x5 and the other puzzles."

- [ ] **Step 1: Write the failing tests** in `tests/test_cube.py`:

```python
import pytest
from src.puzzles.registry import get_engine

@pytest.mark.parametrize("puzzle", ["2x2", "3x3"])
@pytest.mark.parametrize("token", ["R", "U'", "F2", "r", "Rw", "Rw2", "3Fw'", "M", "E2", "S'", "x", "y2", "z'", "R2'", "u"])
def test_move_shaped_tokens(puzzle, token):
    assert get_engine(puzzle).is_move_token(token)

@pytest.mark.parametrize("puzzle", ["2x2", "3x3"])
@pytest.mark.parametrize("token", ["", "I", "can't", "MISMATCH", "2x2", "R,", "(R", "R3", "Q", "RU", "R''", " R", "R ", "R’", "a", "The"])
def test_prose_tokens(puzzle, token):
    assert not get_engine(puzzle).is_move_token(token)

@pytest.mark.parametrize("puzzle", ["2x2", "3x3"])
def test_every_legal_move_is_a_move_token(puzzle):
    engine = get_engine(puzzle)
    assert all(engine.is_move_token(m) for m in engine.legal_moves())

def test_engine_has_no_reference_length():
    assert not hasattr(get_engine("2x2"), "reference_length")
```

Note `R’` (typographic apostrophe) is not a move token: definitions say `′` doesn't match `'`, and a curly apostrophe line is therefore prose. Also delete every existing test of `reference_length` / IDA*.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q tests/test_cube.py` — expect the new tests to FAIL (`AttributeError: is_move_token`).

- [ ] **Step 3: Implement** in `src/puzzles/cube.py`:

```python
# The shape of a cube move in Singmaster and WCA notation, legal or not: a face letter with an
# optional layer count and w, or a lower-case wide, slice, or rotation letter; then ' or 2 or both.
# The layer count goes with face letters only, so the puzzle name 2x2 in prose isn't a move token.
MOVE_TOKEN = re.compile(r"(?:[0-9]*[URFDLB]w?|[urfdlbMESxyz])(?:2'?|'2?)?")
```

and in `CubeEngine`:

```python
    def is_move_token(self, token: str) -> bool:
        return MOVE_TOKEN.fullmatch(token) is not None
```

Check: `R''` fails (one `'` only), `R2'` passes, `3Fw'` passes, `x2` passes, `2x2` fails. Add `import re` if missing. Replace the abstract method in `src/puzzles/engine.py`; update the module docstring ("implements all nine methods" stays nine). Delete the reference-length code and its callers in `metrics.py` (`make_attempt_rows` loses `cache`; `compute` stops passing `{}`), the `efficiency` column in `report.py`, and any UI column.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` — all pass. Regenerate `tests/fixtures/report_expected.md` and `tests/fixtures/pipeline-1.0.0.md` only by running the code that the tests compare against, then check `git diff tests/fixtures` shows only the removed Efficiency column.

- [ ] **Step 5: Update the docs listed above**, then commit: `Drop efficiency and the reference solver, and add is_move_token to the engine`.

---

### Task 2: Validator outcomes `truncated`, `abstention`, `format_error`; impossible moves by move token; decision hallucination null

**Files:**
- Modify: `src/validator.py`
- Modify: `src/run/decision.py` (comment that names `malformed_output` only if the wording becomes wrong)
- Test: `tests/test_validator.py`
- Docs: `AGENTS.md` invariant 9 and 13, `docs/definitions.md` (Malformed output, Hallucination flag, Mismatch flag, Outcome list, Move count, Parsed moves, Stop reason unchanged), `docs/specs/validator.md`, `docs/methodology.md` (decision-model paragraph: "Their hallucination rate is n/a, because …" instead of "always 0 … reports show it as 0").

**Interfaces:**
- Consumes: `Engine.is_move_token(token) -> bool` (Task 1).
- Produces: `OUTCOMES = ("infrastructure_failure", "truncated", "malformed_output", "abstention", "format_error", "hallucination", "success", "failure")` exported from `src/validator.py`, in check order. `Verdict.hallucination: bool | None` (None for decision models and for outcomes without a judgement). Later tasks import `OUTCOMES`.

**Rules (write these into `docs/definitions.md` Outcome list and `docs/specs/validator.md` verbatim):**

Lines: strip one surrounding code fence, drop one trailing `\r` per line, drop empty and whitespace-only lines (unchanged). A line is a **move line** when it splits on whitespace into one or more tokens and every token is a move token. Every other line is a **prose line**. Parsed moves are the tokens of the move lines, in order.

Outcomes, checked in this order:
1. `infrastructure_failure`: stop reason `infrastructure_failure`.
2. `truncated`: stop reason `truncated` (cut off at the token limit).
3. `malformed_output`: stop reason `refused` (a refusal by the API or a content filter), no line left, or, for a decision model, a raw response that doesn't parse as the array of answers.
4. `abstention`: there is no move line, and the response is not the single line `MISMATCH`. The AI model answered in prose, for example to say it can't solve the puzzle.
5. `hallucination`: a parsed move is not a legal move.
6. `format_error`: every parsed move is legal, but the response isn't in the required layout: it has a prose line, a move line with more than one token or with whitespace around its token, or the line `MISMATCH` together with any other line.
7. `success` and `failure`: as before.

Mismatch flag: on only when the whole response is the single line `MISMATCH` (decision model: unchanged). Off for every other outcome, including `format_error`.

Hallucination flag: `True` for `hallucination`, `False` for `abstention`, `format_error`, `success`, `failure`; `False` for `infrastructure_failure`, `truncated`, `malformed_output` of a text model; **`None` for every outcome of a decision model** (stored as JSON `null`).

Move count: number of parsed moves for `hallucination`, `format_error`, `success`, `failure`; `None` otherwise. For `abstention` it is `None` and parsed moves are `[]`.

Invariant 9 new text: "AI model output is either the moves, one per line in the order applied, or the single line `MISMATCH`. Output cut off at the token limit gets outcome `truncated`. Output that is empty after the validator's line rules, or a refusal by the API or a content filter, including one returned as an API error, gets outcome `malformed_output`. Output with no move token gets outcome `abstention`, and legal moves in any other layout get `format_error`. All three are counted apart from failures and hallucinations. Only a move token that isn't a legal move is a hallucination. A decision model's raw response is instead …" (keep the rest). Invariant 13: append "The hallucination flag of a decision-model attempt is null."

- [ ] **Step 1: Write the failing tests** in `tests/test_validator.py` (reuse the file's existing input fixtures for a valid and an invalid 2x2 input; name them `VALID` and `INVALID` below):

```python
from src.validator import OUTCOMES, validate

def test_outcome_order():
    assert OUTCOMES == ("infrastructure_failure", "truncated", "malformed_output", "abstention",
                        "format_error", "hallucination", "success", "failure")

def test_truncated_is_its_own_outcome():
    v = validate(VALID, "R\nU", "truncated")
    assert (v.outcome, v.hallucination, v.mismatch, v.move_count) == ("truncated", False, False, None)

def test_refusal_text_is_abstention():
    v = validate(VALID, "I can’t reliably derive a solving sequence for this state.", "ok")
    assert (v.outcome, v.hallucination, v.parsed_moves, v.move_count) == ("abstention", False, [], None)

def test_prose_with_move_shaped_word_is_abstention():
    assert validate(VALID, "R2 would not help here.\nUse an x rotation first.", "ok").outcome == "abstention"

def test_api_refusal_is_malformed():
    assert validate(VALID, "", "refused").outcome == "malformed_output"

def test_moves_on_one_line_are_format_error():
    v = validate(VALID, "R U' F2", "ok")
    assert (v.outcome, v.parsed_moves, v.move_count, v.hallucination) == ("format_error", ["R", "U'", "F2"], 3, False)

def test_prose_header_before_legal_moves_is_format_error():
    assert validate(VALID, "An optimal sequence is:\n\nR'\nF", "ok").outcome == "format_error"

def test_padded_move_is_format_error():
    assert validate(VALID, " R\nU", "ok").outcome == "format_error"

def test_mismatch_with_explanation_is_format_error():
    v = validate(INVALID, "MISMATCH\nThe UFL corner is twisted.", "ok")
    assert (v.outcome, v.mismatch) == ("format_error", False)

def test_impossible_move_token_is_hallucination():
    v = validate(VALID, "R\nM\nU", "ok")  # M is a slice move, not in the 2x2 move group
    assert (v.outcome, v.hallucination, v.parsed_moves) == ("hallucination", True, ["R", "M", "U"])

def test_impossible_token_beside_prose_is_hallucination():
    assert validate(VALID, "Solution:\nRw U", "ok").outcome == "hallucination"

def test_single_mismatch_line_still_flags():
    v = validate(INVALID, "MISMATCH", "ok")
    assert (v.outcome, v.mismatch) == ("success", True)

def test_decision_hallucination_is_none():
    raw = '[{"answers": {"next_move": {"choice": "mismatch"}}}]'
    assert validate(INVALID, raw, "ok", decision=True).hallucination is None
    assert validate(INVALID, "", "infrastructure_failure", decision=True).hallucination is None
```

Update existing tests that expected the old behaviour (prose lines → `hallucination`, truncated → `malformed_output`, decision `hallucination is False`) to the new rules; do not delete coverage.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q tests/test_validator.py` — new tests FAIL.

- [ ] **Step 3: Implement.** Replace `_parse` and the tail of `validate`:

```python
OUTCOMES = ("infrastructure_failure", "truncated", "malformed_output", "abstention",
            "format_error", "hallucination", "success", "failure")


def _lines(raw_response: str) -> list[str]:
    """One surrounding code fence stripped, one trailing \r per line dropped, blank lines dropped."""
    text = raw_response
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    return [line for line in lines if line.strip()]


def _read_lines(lines: list[str], engine) -> tuple[list[str], bool]:
    """Return (parsed moves, whether the layout is exactly one bare move per line)."""
    moves, layout_ok = [], True
    for line in lines:
        tokens = line.split()
        if tokens and all(engine.is_move_token(t) for t in tokens):
            moves += tokens
            layout_ok = layout_ok and tokens == [line]
        else:
            layout_ok = False
    return moves, layout_ok
```

`_no_moves(outcome, decision)` sets `hallucination=None if decision else False`. In `validate`:

```python
    if stop_reason == "infrastructure_failure":
        return _no_moves("infrastructure_failure", decision)
    if stop_reason == "truncated":
        return _no_moves("truncated", decision)
    if stop_reason == "refused":
        return _no_moves("malformed_output", decision)
    engine = get_engine(input["puzzle"])
    legal = engine.legal_moves()
    if decision:
        parsed = _parse_decision(raw_response, legal)
        if parsed is None:
            return _no_moves("malformed_output", True)
        moves, mismatch = parsed
        return _judge(input, engine, moves, mismatch, None)
    lines = _lines(raw_response)
    if not lines:
        return _no_moves("malformed_output", False)
    if lines == ["MISMATCH"]:
        return _judge(input, engine, [], True, False)
    moves, layout_ok = _read_lines(lines, engine)
    if not moves:
        return _no_moves("abstention", False)
    if any(m not in legal for m in moves):
        return Verdict(moves, True, False, len(moves), "hallucination")
    if not layout_ok:
        return Verdict(moves, False, False, len(moves), "format_error")
    return _judge(input, engine, moves, False, False)
```

`_judge(input, engine, moves, mismatch, hallucination)` holds the existing apply-and-check code and returns `success`/`failure` with the given `hallucination` value. A decision model can never produce an illegal move (its options are the legal moves), so `_judge` is right for it. Update the `Verdict` comments (`hallucination: bool | None`).

- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` — fix other tests that assert old outcomes (`tests/test_run.py`, `tests/test_decision.py`, `tests/test_pipeline.py`). Keep their intent.

- [ ] **Step 5: Docs** as listed, then commit: `Split truncated, abstention, and format_error from hallucination in the validator`.

---

### Task 3: Count the new outcomes in evaluate, report, run progress, and the UI

**Files:**
- Modify: `src/evaluate/metrics.py` (`rates`, `PAIRED_METRICS` handling, `is_hit`, `make_attempt_row` gets `"decision": bool`)
- Modify: `src/evaluate/report.py` (rate labels; outcome colours/text if any)
- Modify: `src/run/progress.py` (live table and plain line show truncated, abstention, format error)
- Modify: `ui/pooling.py` (`RATES`), `ui/static/expmetrics.js`, `ui/static/pages/experiments.js`, `ui/static/progress.js` (`OUTCOMES` and a colour each: truncated `#d68910`, abstention `#7f8c8d`, format_error `#c0392b`)
- Test: `tests/test_evaluate.py`, `tests/test_report.py`, `tests/test_run.py` (progress), `tests/test_ui.py`, `tests/test_ui_bundle.py`, `tests/js/progress.test.mjs`
- Docs: `docs/definitions.md` Metrics (add **Truncation rate**, **Abstention rate**, **Format error rate**, each "the share of attempts with outcome …"; Hallucination rate: "n/a for decision models, which can't return an impossible move"; Mismatch detection and False mismatch: "Truncated output, malformed output, abstention, and format errors count as not flagged"), `docs/specs/evaluate.md`, `docs/specs/report.md`, `docs/specs/run.md`, `docs/specs/ui.md`.

**Interfaces:**
- Consumes: `OUTCOMES` and `Verdict.hallucination: bool | None` (Task 2).
- Produces: metric and summary rows gain `truncated_rate`, `abstention_rate`, `format_error_rate` (each with `_low`, `_high`, `_n`). `hallucination_rate` is `NA` (with `_n` = 0) for a group whose rows are all decision-model rows. Attempt rows gain `"decision": bool`. The paired test skips `hallucination_rate` for decision models.

- [ ] **Step 1: Failing tests** in `tests/test_evaluate.py`:

```python
def test_new_outcome_rates(tmp_path):
    # build 4 raw records for one valid input under one setup: truncated, abstention,
    # format_error, success, with the module's existing record helper
    ...
    row = metric_rows[0]
    assert row["truncated_rate"] == 0.25 and row["abstention_rate"] == 0.25
    assert row["format_error_rate"] == 0.25 and row["malformed_output_rate"] == 0.0

def test_decision_model_hallucination_rate_is_na(tmp_path):
    # raw records from a decision model (decision: true), one success, one failure
    ...
    assert metric_rows[0]["hallucination_rate"] == "n/a"
    assert not any(r["metric"] == "hallucination_rate" for r in paired_tests(attempt_rows) if r["model"] == "jev")

def test_old_records_rescore_without_error(tmp_path):
    # a 1.x-shaped record: stop_reason truncated, outcome malformed_output, hallucination false;
    # and a decision record with hallucination false
    ...
    assert [r["outcome"] for r in attempt_rows] == ["truncated", "success"]
```

Write the `...` parts with the helpers already in `tests/test_evaluate.py` (look for how existing tests build raw records and a release folder; copy that pattern exactly).

- [ ] **Step 2: Run** them — FAIL.

- [ ] **Step 3: Implement.** In `rates()` add `rate_columns` for `truncated`, `abstention`, `format_error` after `malformed_output_rate`. For hallucination: `if rows and all(r["decision"] for r in rows): rate_columns(out, "hallucination_rate", 0, 0)` (gives n/a), else as before. In `paired_tests`, skip `hallucination_rate` when every row of the group is a decision row. Report: add the three rates to the Summary tables (valid and invalid) and Metrics tables, labels "Truncation rate"/"Truncated", "Abstention rate"/"Abstention", "Format error rate"/"Format error". Progress and UI: add the three outcomes everywhere `malformed_output` is listed.

- [ ] **Step 4: Run** the whole suite, regenerate report fixtures by running the code, check the fixture diff shows only the new columns.

- [ ] **Step 5: Commit**: `Count truncated, abstention, and format_error outcomes in reports, progress, and the UI`.

---

### Task 4: Mismatch detection as balanced accuracy, with an always-MISMATCH baseline

**Files:**
- Modify: `src/evaluate/metrics.py` (new `detection_rows(attempt_rows, models) -> list[dict]`)
- Modify: `src/evaluate/evaluate.py` (write `<VERSION>.detection.csv`; pass rows to the report)
- Modify: `src/evaluate/report.py` (new section **Mismatch detection** after Summary)
- Test: `tests/test_evaluate.py`, `tests/test_report.py`
- Docs: `docs/definitions.md` Metrics: add **Balanced accuracy** ("For one AI model, setup, and puzzle, the mean of the mismatch detection rate and one minus the false mismatch rate. 0.5 is what answering MISMATCH always, or never, scores, so only a value above 0.5 shows detection. It is reported because a model that flags most valid inputs gets a high detection rate for free.") and **Always-MISMATCH baseline** (detection 1.0, false mismatch 1.0, balanced accuracy 0.5, success rate on valid inputs 0, on invalid 1.0). `docs/specs/evaluate.md`, `docs/specs/report.md`. State in Success rate: "Reported separately for valid and invalid inputs, never pooled."

**Interfaces:**
- Consumes: attempt rows (with `mismatch`, `validity`, `outcome`, `input_id`, `model`, `setup`, `puzzle`).
- Produces: `detection_rows()` returns one row per (model, puzzle, setup), sorted model (config order), puzzle (registry order), setup (`SETUPS` order), with columns `model, puzzle, setup, detection_rate, detection_n, false_mismatch_rate, false_mismatch_n, balanced_accuracy, balanced_accuracy_low, balanced_accuracy_high`. Pooled over depths. Infrastructure failures left out. Interval: from the bootstrap in Task 5; in this task use `NA` for low/high and leave a module constant hook (`interval_for_balanced_accuracy`) that Task 5 replaces. Rates are `NA` when their n is 0, and balanced accuracy is `NA` when either is `NA`.

- [ ] **Step 1: Failing tests**:

```python
def test_balanced_accuracy():
    rows = ([_row("v1", "valid", mismatch=True)] + [_row(f"v{i}", "valid", mismatch=False) for i in range(2, 5)]
            + [_row(f"x{i}", "invalid", mismatch=True) for i in range(1, 4)] + [_row("x4", "invalid", mismatch=False)])
    [row] = detection_rows(rows, ["m"])
    assert row["detection_rate"] == 0.75 and row["false_mismatch_rate"] == 0.25
    assert row["balanced_accuracy"] == 0.75

def test_always_mismatch_scores_half():
    rows = [_row("v1", "valid", mismatch=True), _row("x1", "invalid", mismatch=True)]
    assert detection_rows(rows, ["m"])[0]["balanced_accuracy"] == 0.5

def test_no_invalid_inputs_gives_na():
    assert detection_rows([_row("v1", "valid", mismatch=False)], ["m"])[0]["balanced_accuracy"] == "n/a"
```

with `_row(input_id, validity, mismatch, outcome="failure", model="m", setup="no_model", puzzle="2x2")` a local helper returning the attempt-row dict fields above.

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `detection_rows` in `metrics.py`; write the CSV beside the metrics CSV with the same helper `evaluate.py` uses for the paired CSV; the report section has one table per AI model with columns Puzzle, Setup, Detection rate, False mismatch rate, Balanced accuracy, and one extra row per puzzle labelled `always MISMATCH (baseline)` with 1.00, 1.00, 0.50. One sentence above the tables links the definition.
- [ ] **Step 4: Run** the suite; regenerate fixtures from code; check the diff.
- [ ] **Step 5: Commit**: `Report mismatch detection as balanced accuracy with an always-MISMATCH baseline`.

---

### Task 5: Bootstrap confidence intervals over inputs

**Files:**
- Modify: `src/evaluate/metrics.py` (replace `wilson` use in `rate_columns` with `bootstrap_interval`; fill balanced-accuracy intervals)
- Modify: `src/evaluate/report.py` (rate cells show `n=<attempts>, <k> inputs`)
- Modify: `ui/pooling.py` if it recomputes intervals (it pools CSV rows for display: keep Wilson there only if it is display-only and marked `*`; otherwise call the same function)
- Test: `tests/test_evaluate.py`, `tests/test_report.py`, fixtures
- Docs: `docs/definitions.md` Metrics preamble: replace the Wilson sentence with: "Every rate is reported with its denominator `n`, the number of inputs behind it, and a 95% bootstrap interval over inputs: inputs are drawn with replacement 2000 times, each draw keeps all attempts of the inputs drawn, and the interval is the 2.5th and 97.5th percentile of the rate over the draws. Attempts on one input aren't independent, so resampling attempts would make the interval too narrow. The draws come from a fixed seed, so the same raw records always give the same interval. The interval is n/a when fewer than 2 inputs are behind the rate." `docs/specs/evaluate.md` (algorithm and test values), `docs/specs/report.md`.

**Interfaces:**
- Produces: `bootstrap_interval(cells: list[tuple[int, int]], key: str) -> tuple` returning `(rate, low, high)`; `cells` is one `(hits, attempts)` pair per input; `key` is a stable text naming the group and the metric, hashed with sha256 to seed `random.Random`, so results don't depend on group order. `rate` is total hits / total attempts. `NA` triple when total attempts is 0; `(rate, NA, NA)` when fewer than 2 inputs. Constants `BOOTSTRAP_DRAWS = 2000`, `BOOTSTRAP_SEED = "bootstrap-v1"` (key text is `f"{BOOTSTRAP_SEED}|{key}"`). Percentiles by the nearest-rank rule on the sorted draw rates: low = sorted[int(0.025 * B)], high = sorted[int(0.975 * B) - 1]. Each rate column gains `<name>_inputs`.
- For balanced accuracy: draw valid and invalid inputs separately within each draw (stratified), compute BA per draw.

- [ ] **Step 1: Failing tests**:

```python
def test_bootstrap_is_deterministic():
    cells = [(1, 3), (0, 3), (3, 3), (2, 3)]
    a = bootstrap_interval(cells, "g|success_rate")
    assert a == bootstrap_interval(cells, "g|success_rate")
    assert a[0] == 0.5 and 0.0 <= a[1] <= 0.5 <= a[2] <= 1.0

def test_bootstrap_one_input_has_no_interval():
    assert bootstrap_interval([(2, 3)], "k") == (2 / 3, "n/a", "n/a")

def test_bootstrap_empty():
    assert bootstrap_interval([], "k") == ("n/a", "n/a", "n/a")

def test_bootstrap_all_hits():
    assert bootstrap_interval([(3, 3)] * 10, "k") == (1.0, 1.0, 1.0)

def test_clustered_interval_is_wider_than_independent():
    # 10 inputs, all-or-nothing per input: clustering must widen the interval vs. 30 independent attempts
    clustered = bootstrap_interval([(3, 3)] * 5 + [(0, 3)] * 5, "k")
    independent = bootstrap_interval([(1, 1)] * 15 + [(0, 1)] * 15, "k")
    assert clustered[2] - clustered[1] > independent[2] - independent[1]
```

The caller builds `cells` sorted by input id, so the same raw records always give the same list and the same interval.

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** `rates()` receives the rows and the group key, builds per-input cells for each rate, calls `bootstrap_interval`. Keep `wilson` only if the UI's display-only pooling still needs it; otherwise delete it. Keep evaluate under 30 s on the largest results folder in the main checkout: precompute per-input (hits, n) once per group and reuse each draw's index list across all rates of the group.
- [ ] **Step 4: Run** the suite; time `evaluate` on `results/claude-haiku-5-5_2x2-3x3_20261102-2253` from the main checkout copy (`cp -r` it into `tmp/` of the worktree, never into `results/`); regenerate fixtures from code.
- [ ] **Step 5: Commit**: `Use a bootstrap over inputs for every confidence interval`.

---

### Task 6: More corruption types, and detection by corruption type

**Files:**
- Modify: `src/puzzles/cube.py` (`corrupt`)
- Modify: `src/evaluate/metrics.py` (new `corruption_rows(attempt_rows, inputs, models)`), `src/evaluate/evaluate.py` (CSV `<VERSION>.corruption.csv`), `src/evaluate/report.py` (section **Detection by corruption type** after Mismatch detection)
- Test: `tests/test_cube.py`, `tests/test_generate.py`, `tests/test_evaluate.py`, `tests/test_report.py`
- Docs: `docs/definitions.md` Puzzles: extend **Corruption** with "Its description starts with its **corruption type**, two words naming the kind of change, followed by the pieces it changed: `twisted corner`, `flipped edge`, `swapped corners`, `swapped edges`, or `recoloured sticker`." `docs/specs/cube.md`, `docs/puzzles/2x2.md`, `docs/puzzles/3x3.md` (list the types each cube uses), `docs/specs/evaluate.md`, `docs/specs/report.md`.

**Corruption types per cube:**
1. 2x2: `twisted corner` and `recoloured sticker`. (A swap of two 2x2 corners stays reachable, so it isn't a corruption.)
2. 3x3: `twisted corner`, `flipped edge`, `swapped corners`, `swapped edges`, and `recoloured sticker`.
3. The type is chosen uniformly with `rng = random.Random(input_seed)`; the piece and direction follow from the same `rng`.
4. `swapped corners A B`: swap the sticker triples of two corner positions so each corner keeps its orientation (position i's stickers in reading order go to position j's sticker slots in the same order). On a 3x3 this breaks the permutation parity, so the state is unreachable.
5. `swapped edges A B`: same for two edge positions.
6. `recoloured sticker F<k> X to Y`: pick a non-centre sticker (index k in face F's reading order, 1-based), change its colour X to a different colour Y chosen from the other five. Colour counts then differ from n*n per colour, so the state is unreachable.
7. Every result must fail `_is_reachable`; `generate` already checks it through `load_state()`.

**Interfaces:**
- Produces: `corruption_type(description: str) -> str` in `metrics.py` = the first two words of the description. `corruption_rows` returns one row per (model, puzzle, setup, corruption type) over invalid inputs, with `detection_rate` and its bootstrap interval (Task 5's function), sorted model, puzzle, setup, type in the order listed above.

- [ ] **Step 1: Failing tests**:

```python
@pytest.mark.parametrize("puzzle,types", [
    ("2x2", {"twisted corner", "recoloured sticker"}),
    ("3x3", {"twisted corner", "flipped edge", "swapped corners", "swapped edges", "recoloured sticker"})])
def test_corruption_types_cover_and_stay_unreachable(puzzle, types):
    engine = get_engine(puzzle)
    state, _ = engine.scramble(1, 10)
    seen = set()
    for seed in range(400):
        new, description = engine.corrupt(state, seed)
        seen.add(" ".join(description.split()[:2]))
        with pytest.raises(ValidityMismatchError):
            engine.load_state({"state": new, "validity": "valid"})
    assert seen == types

def test_corruption_type_reads_old_descriptions():
    assert corruption_type("twisted corner UFL clockwise") == "twisted corner"
    assert corruption_type("flipped edge UF") == "flipped edge"
```

and one `corruption_rows` test with two invalid inputs of different types.

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** in `cube.py`, `metrics.py`, `evaluate.py`, `report.py`.
- [ ] **Step 4: Run** the suite. Note: `tests/test_generate.py` may pin exact inputs for a seed; changing `corrupt` changes generated invalid inputs. That is expected for new input sets; frozen releases under `releases/` are never regenerated (invariant 5, rule 2 in `.claude/CLAUDE.md`). If a test pins a frozen release's bytes against `generate`, stop and report instead of editing the release.
- [ ] **Step 5: Commit**: `Add swapped and recoloured corruptions, and report detection by corruption type`.

---

### Task 7: `reasoning_effort` config parameter

**Files:**
- Modify: `src/config.py` (optional top-level `reasoning_effort`, one of `low`, `medium`, `high`; add `reasoning_effort`, `output_config`, `thinking_config`, `thinking` to `FORBIDDEN_PARAMS` so a model's `params` can't override it)
- Modify: `src/run/models.py` (`call_model(model, prompt, max_output_tokens, reasoning_effort=None)`; provider mapping below)
- Modify: `src/run/run.py` (pass `config.get("reasoning_effort")`)
- Modify: `src/evaluate/report.py` (Experiment section line: "Reasoning effort: medium." or "Reasoning effort: provider default.")
- Modify: `ui/experiments.py` (`DEFAULTS["reasoning_effort"] = "medium"`), `ui/forms.py`, `ui/static/pages/new.js` (a select with low/medium/high, default medium), `ui/static/pages/experiment.js` (show it), `config/experiments/example.toml` (`reasoning_effort = "medium"`), `config/models.toml` header comment (effort comes from the experiment config, not params)
- Test: `tests/test_config.py`, `tests/test_models.py`, `tests/test_run.py`, `tests/test_report.py`, `tests/test_ui.py`
- Docs: `docs/definitions.md` (new **Reasoning effort** under Setups: "How much an AI model reasons before it answers, one of `low`, `medium`, or `high`, set once per experiment in config and sent to every system-2 model in the provider's own parameter. Fixing it keeps the comparison between providers about ability, not about how long each provider lets its model think. An experiment config without it ran at each provider's default."), AGENTS.md invariant 2 (add "reasoning effort" to the config-parameter list), `docs/specs/config.md`, `docs/specs/models.md`, `docs/specs/run.md`, `docs/specs/report.md`, `docs/specs/ui.md`.

**Provider mapping (sent only when `reasoning_effort` is set and the model's `kind` is `system-2`; decision models ignore it):**
1. anthropic: `output_config={"effort": effort}` on `client.messages.stream(...)` (verified in anthropic 1.15.0: `output_config.effort` accepts `low`/`medium`/`high`).
2. openai: `reasoning_effort=effort` on `client.chat.completions.create(...)` (verified in openai 3.35.1).
3. google: `config["thinking_config"] = {"thinking_level": effort.upper()}` (verified: `ThinkingLevel` has `LOW`, `MEDIUM`, `HIGH`).
4. fake: ignored.

**Interfaces:**
- Produces: `call_model(model: dict, prompt: str, max_output_tokens: int, reasoning_effort: str | None = None) -> Reply`.

- [ ] **Step 1: Failing tests**:

```python
def test_reasoning_effort_optional_and_checked():
    base = 'release = "1.3.2"\nattempts = 1\nretry_cap = 0\nmax_output_tokens = 10\n[[models]]\nname = "f"\nprovider = "fake"\napi_model_id = "f"\nkind = "system-2"\n'
    assert "reasoning_effort" not in parse_experiment_config(base, "e", "x")
    assert parse_experiment_config('reasoning_effort = "medium"\n' + base, "e", "x")["reasoning_effort"] == "medium"
    with pytest.raises(ValueError, match="reasoning_effort"):
        parse_experiment_config('reasoning_effort = "max"\n' + base, "e", "x")

def test_params_cannot_set_effort():
    text = ('release = "1.3.2"\nattempts = 1\nretry_cap = 0\nmax_output_tokens = 10\n[[models]]\nname = "f"\n'
            'provider = "fake"\napi_model_id = "f"\nkind = "system-2"\nparams = {reasoning_effort = "high"}\n')
    with pytest.raises(ValueError, match="reasoning_effort"):
        parse_experiment_config(text, "e", "x")

def test_every_committed_experiment_config_still_parses():
    for path in Path("results").glob("*/experiment.toml"):
        load_experiment_config(path)
```

In `tests/test_models.py`, monkeypatch each SDK client (follow the file's existing pattern) and assert the request kwargs: anthropic gets `output_config == {"effort": "medium"}`, openai gets `reasoning_effort == "medium"`, google config has `thinking_config == {"thinking_level": "MEDIUM"}`; with `None` none of these keys is sent; a `system-1` model gets none of them.

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** as mapped. The worst-case request cost in `src/run/budget.py` already uses `max_output_tokens`, which is unchanged, so budgets need nothing new.
- [ ] **Step 4: Run** the suite.
- [ ] **Step 5: Commit**: `Add reasoning_effort to the experiment config and send it to every provider`.

---

### Task 8: Say why an infrastructure failure happened

**Files:**
- Modify: `src/run/run.py` (`call_with_retries` and the decision loop's retry path in `src/run/decision.py`: on every `InfrastructureError`, write one line to stderr: `infrastructure error: <model name> <input id> <setup> attempt <n> call <k>: <str(error)>`, truncated to 300 characters)
- Modify: `src/run/models.py` (OpenAI and Anthropic clients get an explicit `timeout=httpx.Timeout(1800.0, connect=30.0)`; Google `HttpOptions(timeout=1_800_000)` in ms; document the value as a constant `REQUEST_TIMEOUT_S = 1800`)
- Modify: `src/run/models.py` OpenAI branch: `openai.APITimeoutError` is a subclass of `APIConnectionError` and already counts; also map `openai.APIStatusError` with status 408/409 to `InfrastructureError`
- Test: `tests/test_run.py` (capsys: a fake `InfrastructureError("boom")` prints the line to stderr and nothing to stdout), `tests/test_models.py` (timeout passed to clients)
- Docs: `docs/specs/run.md`, `docs/specs/models.md`.

Nothing goes into raw records (invariant 13 is unchanged). The UI already captures `run`'s stderr in its job log; check `ui/` (`grep -rn stderr ui`) and make sure the line shows there, or say in the spec where it is visible.

- [ ] **Step 1: Failing tests** as above.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the suite.
- [ ] **Step 5: Commit**: `Log the reason for every infrastructure failure and set explicit request timeouts`.

---

### Task 9: Methodology: power analysis and the development/held-out split

**Files:**
- Modify: `docs/methodology.md`, `docs/definitions.md` (add **Development input set** and **Held-out input set** under Inputs), `README.md` only if it describes metrics that changed.

Docs only. Content for `docs/methodology.md`:

1. New section `## Development and held-out inputs`: "Input set 1 (releases 1.x) is the development input set. Prompts were changed while its results were read, so its results show how the method was built and are not evidence for the research question. Release 2.0.0 freezes a new input set from a new seed, the held-out input set, with the prompts and the assessment as they stand when it is cut. Every AI model runs on it once. A prompt change after that is a new minor release, and its results are reported next to, never instead of, the earlier ones."
2. New section `## Sample size`: the [paired setup test](definitions.md#metrics) compares setups on the same inputs. With per-input outcomes treated as independent between setups (a conservative assumption, since a hard input tends to be hard under every setup), the exact sign test needs about this many valid inputs per AI model and puzzle for 80% power:

| Rate under setup A | Rate under setup B | Inputs at α 0.05 | Inputs at α 0.0167 (Holm, worst case) |
|---|---|---|---|
| 0.50 | 0.60 | 410 | 540 |
| 0.50 | 0.65 | 190 | 250 |
| 0.50 | 0.70 | 110 | 140 |
| 0.20 | 0.35 | 160 | 200 |
| 0.10 | 0.25 | 120 | 150 |

   Then: "Input set 1 has 30 valid inputs per puzzle, which has about 10–25% power for a 15–20 point difference, so a null result on it says little. The held-out input set aims for at least 150 valid inputs per puzzle (a scramble count of 50 over three depths), enough to detect a 20-point difference. More attempts per input add little power, because the paired test uses the input as its unit, so the held-out run uses 1 attempt per input unless the budget allows more inputs."
3. Edit `## Measurement` item 3 to mention balanced accuracy and detection by corruption type, linking definitions.
4. Edit the decision-model paragraph: "Their hallucination rate is n/a" (if Task 2 hasn't already).

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Check every link resolves**: `.venv/bin/python -m pytest -q tests/test_report.py -k link` and a manual grep of new anchors.
- [ ] **Step 3: Commit**: `Add the sample size analysis and the development and held-out split to the methodology`.

---

## After this plan (separate PRs, not tasks here)

1. Release 1.3.3, a mirror of 1.3.2, so the existing raw records are re-scored with the new validator and metrics. Then run `evaluate` for each experiment and commit the reports on each `results/<id>` branch.
2. Release 2.0.0 with a new seed and the scramble count from Task 9, after the owner confirms the count and the budget.
3. A one-call diagnostic of the OpenAI 3x3 infrastructure failures with Task 8's logging, after the owner says go (it costs money).
