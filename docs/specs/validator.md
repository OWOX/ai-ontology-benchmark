# validator

File: `src/validator.py`.

## Purpose

The [validator](../definitions.md#workflows). It turns one raw response into parsed moves, flags, a move count, and an [outcome](../definitions.md#attempts-and-outcomes). [run](run.md) calls it before writing a raw record, and [evaluate](evaluate.md) calls it again. It has no randomness and no network access.

## Inputs

1. An input, as one line of `inputs.jsonl`.
2. `raw_response`: the text the AI model returned. Empty for an infrastructure failure.
3. `stop_reason`: `ok`, `truncated`, `refused`, or `infrastructure_failure`.
4. `decision`: a boolean, false by default. [evaluate](evaluate.md) sets it from the AI model's provider, and the validator never guesses it from the text.

## Outputs

`validate(input, raw_response, stop_reason, decision=False) -> Verdict`, where `Verdict` has `parsed_moves`, `hallucination`, `mismatch`, `move_count`, and `outcome`.

Steps, in order:

1. If `stop_reason` is not one of the four values above, raise `ValueError`.
2. If `stop_reason` is `infrastructure_failure`, return outcome `infrastructure_failure`.
3. If `stop_reason` is `truncated`, return `truncated`. If it is `refused`, return `malformed_output`.
4. With `decision` false, read the lines as [invariant 9](../../AGENTS.md#invariants) says:
   1. Strip one surrounding Markdown code fence, if there is one.
   2. Split on `\n` and remove one trailing `\r` from each line. Drop lines that are empty or only whitespace. No other line is stripped.
   3. No lines left: `malformed_output`, even for a puzzle with no engine, because the parse comes before the engine is looked up.
   4. Exactly one line, and it is `MISMATCH`: no moves, mismatch flag on. Go to step 7 below.
   5. Otherwise the mismatch flag is off. A line is a **move line** when it splits on whitespace into one or more tokens and every token is a move token (`is_move_token()`). Any other line is split on whitespace and commas, and each token that is only a numeric or bullet marker (`1.`, `1)`, `-`, `*`, `•`) is dropped, wherever it is. A marker glued to the first token left after those is removed, and so is a single letter and a `.` or `)` as that first token only, as in `b)`, unless it is a capital letter that is a move token (`is_move_token()`), as in `R.`. Then the characters `` ` ``, `*`, `_`, `.`, `)`, `(` and any matching pair of straight double quotes are stripped from both ends, repeatedly, so nested pairs such as `""R""` go too, with empty tokens dropped. The prime `'` is never stripped, because it is part of a move. The line is a **decorated move line** when it has tokens and all are move tokens, and a **decorated MISMATCH line** when its only token is `MISMATCH`. Every other line is a **prose line**. The parsed moves are the tokens of the move lines and, stripped, of the decorated move lines, in order.
   6. No move line, no decorated move line, and no decorated MISMATCH line (a line that is exactly `MISMATCH` is one, beside other lines): `abstention`, with no parsed moves and no move count. The AI model answered in prose.

   With `decision` true, see [the decision path](#decision-path) instead, which needs the engine first for the move options.
5. Mark each parsed move as legal only if it exactly equals a string in `legal_moves()`. A move token that isn't legal is an impossible move. If any parsed move is impossible, `hallucination` is true and the outcome is `hallucination`, even beside prose lines. The first impossible move is enough: the attempt fails whatever follows it or whether the final state would be solved, `run` stores the reply whole, and the attempt is never re-asked ([run](run.md#outputs) retries only infrastructure failures).
6. Otherwise, if the layout isn't exactly one bare move per line (there is a prose line, a move line with more than one token or with whitespace around its token, a decorated move line, a decorated MISMATCH line, or a `MISMATCH` line beside other lines), the outcome is `format_error`.
7. Otherwise, apply every move to the input's state with `apply_move()`. Return `success` if the expected result is reached and `failure` if not. For a valid input, the expected result is solved with mismatch off. For an invalid input, it is mismatch on.

`move_count` is the length of `parsed_moves` for `hallucination`, `format_error`, `success`, and `failure`, and empty for the other outcomes. The mismatch flag is on only for the single line `MISMATCH` and is off for every other outcome. `hallucination` is true for outcome `hallucination` and false for every other outcome of a text model. For a decision model it is `None` (JSON `null`) for every outcome.

`OUTCOMES`, exported from the validator, lists the outcomes in this check order: `infrastructure_failure`, `truncated`, `malformed_output`, `abstention`, `hallucination`, `format_error`, `success`, `failure`.

## Decision path

With `decision` true, `raw_response` is a JSON array, one element per completed call, each shaped `{"answers": {"next_move": {"type": "choice", "choice": "move_3"}}, ...}`. Steps 1 to 3 above are unchanged, and the parse in step 4 is replaced by these rules:

1. The array must parse and hold at least one call. Each call needs a `next_move` choice. Anything else is `malformed_output`. Any other answer in a call, such as an old `mismatch` probability, is ignored.
2. A choice is `done`, `mismatch`, or `move_<n>`, where `n` is the 1-based position in `legal_moves()`, written exactly as offered (no leading zeros, no other digits). Any other choice, including a move written out as `R`, is `malformed_output`.
3. The parsed moves are the moves behind the `move_<n>` choices before the first `done` or `mismatch`. Calls after it are ignored.
4. The mismatch flag is on if the first `done` or `mismatch` is `mismatch`.
5. Each call is read by `read_decision_call(call, legal) -> str | None`, the move, `"done"`, or `"mismatch"`, which returns `None` for a malformed call. [run](run.md) uses the same function to stop its loop.
6. The judging in step 7 is unchanged. The options are exactly the legal moves, `done`, and `mismatch`, so a decision model can't return an impossible move, and its hallucination flag is `None` for every outcome.

## How to test

One table-driven test, one row per case, each on a fixed 2x2 input:

| Input | Response | Expected outcome |
|---|---|---|
| valid | the solving moves, one per line | `success` |
| valid | the solving moves with CRLF line endings | `success` |
| valid | the solving moves with blank lines between them | `success` |
| valid | `MISMATCH` | `failure` |
| valid | a solving list with `MISMATCH` among the lines | `format_error` |
| valid | legal moves that don't solve it | `failure` |
| valid | a solving list with `X` added at the end | `format_error` (`X` is prose) |
| valid | `R `, ` R`, or the solving moves on one line | `format_error` |
| valid | `R′` as a line | `abstention` (not a move token) |
| any | `1. R` then `2. U`, `` `R` ``, `R, U, F`, or `"R"` | `format_error` (decorated move lines), or `hallucination` with an illegal move such as `1. M` |
| any | `R.` as a line | `format_error` |
| any | `MISMATCH.`, `**MISMATCH**`, or `MISMATCH ` | `format_error`, flag off |
| any | `I can't solve this.` or `R2 would not help here.` | `abstention` |
| valid | `r`, `Rw`, or `M` as a line | `hallucination` (move tokens that aren't legal) |
| valid | `Solution:` then `Rw U` | `hallucination` |
| valid | prose such as `I think the answer is R` | `abstention` |
| invalid | `MISMATCH` | `success` |
| invalid | `MISMATCH` inside a ```` ``` ```` fence | `success` |
| invalid | `X` | `abstention` |
| invalid | `MISMATCH` then an explanation | `format_error`, flag off |
| invalid | legal moves | `failure` |
| any | the solving moves inside a ```` ```text ```` fence | same as without the fence |
| any | empty, or only blank lines | `malformed_output` |
| any | the solving moves, `stop_reason="truncated"` | `truncated` |
| any | empty, `stop_reason="refused"` | `malformed_output` |
| any | empty, `stop_reason="infrastructure_failure"` | `infrastructure_failure` |
| any | any response, `stop_reason="other"` | `ValueError` |

Decision rows, each on a 2x2 input one move from solved: a solving move then `done` (`success`), `done` first (`failure`), `mismatch` in a later call (flag on), calls after `done` or `mismatch` ignored, an old probability field ignored, malformed arrays (bad JSON, `{}`, `[]`, a missing question, an unknown or out-of-range id, a raw move name), and `infrastructure_failure` with completed calls.

Every row also checks `move_count`, `hallucination`, and `mismatch`. A decision row checks that `hallucination` is `None`.
