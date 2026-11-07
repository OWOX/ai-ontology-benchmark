# validator

File: `src/validator.py`.

## Purpose

The [validator](../definitions.md#workflows). It turns one raw response into parsed moves, flags, a move count, and an [outcome](../definitions.md#attempts-and-outcomes). [run](run.md) calls it before writing a raw record, and [evaluate](evaluate.md) calls it again. It has no randomness and no network access.

## Inputs

1. An input, as one line of `inputs.jsonl`.
2. `raw_response`: the text the AI model returned. Empty for an infrastructure failure.
3. `stop_reason`: `ok`, `truncated`, `refused`, or `infrastructure_failure`.
4. `decision`: a boolean, false by default. [evaluate](evaluate.md) reads it from the raw record, and falls back to the AI model's provider for a record without the field. The validator never guesses it from the text.
5. `reasons`: the offered [mismatch reasons](../definitions.md#attempts-and-outcomes) in order, or `None`, the default, for a release without mismatch reasons. `offered_reasons(engine) -> list[str]`, in this module, returns `engine.mismatch_reasons()` followed by `other`. [run](run.md), [evaluate](evaluate.md), and [prompts](prompts.md) all call it, so the list has one source. The caller passes it when the release's manifest has `mismatch_reasons` true.

## Outputs

`validate(input, raw_response, stop_reason, decision=False, reasons=None) -> Verdict`, where `Verdict` has `parsed_moves`, `hallucination`, `mismatch`, `mismatch_reason`, `impossible_move`, `decoy`, `move_count`, and `outcome`. `mismatch_reason` is a string or `None`. `impossible_move` and `decoy` say which of the two causes of a hallucination applied, so [evaluate](evaluate.md) can count them apart.

Steps, in order:

1. If `stop_reason` is not one of the four values above, raise `ValueError`.
2. If `stop_reason` is `infrastructure_failure`, return outcome `infrastructure_failure`.
3. If `stop_reason` is `truncated`, return `truncated`. If it is `refused`, return `malformed_output`.
4. With `decision` false, read the lines as [invariant 9](../../AGENTS.md#invariants) says:
   1. Strip one surrounding Markdown code fence, if there is one.
   2. Split on `\n` and remove one trailing `\r` from each line. Drop lines that are empty or only whitespace. No other line is stripped.
   3. No lines left: `malformed_output`, even for a puzzle with no engine, because the parse comes before the engine is looked up.
   4. Exactly one line, and it is a **MISMATCH line**: with `reasons`, `MISMATCH`, one space, and a string in `reasons`; without, exactly `MISMATCH`. No moves, mismatch flag on, and `mismatch_reason` is that string (`None` without `reasons`). Go to step 5 below.
   5. Otherwise the mismatch flag is off. A line is a **move line** when it splits on whitespace into one or more tokens and every token is a move token (`is_move_token()`). Any other line is split on whitespace and commas, and each token that is only a numeric or bullet marker (`1.`, `1)`, `-`, `*`, `•`) is dropped, wherever it is. A marker glued to the first token left after those is removed, and so is a single letter and a `.` or `)` as that first token only, as in `b)`, unless it is a capital letter that is a move token (`is_move_token()`), as in `R.`. Then the characters `` ` ``, `*`, `_`, `.`, `)`, `(` and any matching pair of straight double quotes are stripped from both ends, repeatedly, so nested pairs such as `""R""` go too, with empty tokens dropped. The prime `'` is never stripped, because it is part of a move. The line is a **decorated move line** when it has tokens and all are move tokens. It is a **decorated MISMATCH line** when its first token is `MISMATCH` (with `reasons`), or when its only token is `MISMATCH` (without), and the line isn't a MISMATCH line; its reason is the tokens after `MISMATCH` joined with single spaces. Every other line is a **prose line**. The parsed moves are the tokens of the move lines and, stripped, of the decorated move lines, in order. With `reasons`, `mismatch_reason` is the reason of the first MISMATCH line or decorated MISMATCH line whose reason is in `reasons`, and `None` when there is none.
   6. No move line, no decorated move line, no MISMATCH line, and no decorated MISMATCH line: `abstention`, with no parsed moves and no move count. The AI model answered in prose.

   With `decision` true, see [the decision path](#decision-path) instead, which needs the engine first for the move options.
5. Mark each parsed move as legal only if it exactly equals a string in `legal_moves()`. A move token that isn't legal is an impossible move, and sets `impossible_move`. With `reasons`, `decoy` is true when `mismatch_reason` is in `engine.decoy_reasons()`. If either is true, `hallucination` is true and the outcome is `hallucination`, even beside prose lines and even with the mismatch flag on. The first impossible move is enough: the attempt fails whatever follows it or whether the final state would be solved, `run` stores the reply whole, and the attempt is never re-asked ([run](run.md#outputs) retries only infrastructure failures).
6. Otherwise, if the response isn't exactly one bare move per line or a single MISMATCH line (there is a prose line, a move line with more than one token or with whitespace around its token, a decorated move line, a decorated MISMATCH line, or a MISMATCH line beside other lines), the outcome is `format_error`. A decorated MISMATCH line whose reason isn't offered, such as `MISMATCH` alone under a release with reasons, is one of these.
7. Otherwise, apply every move to the input's state with `apply_move()`. Return `success` if the expected result is reached and `failure` if not. For a valid input, the expected result is solved with mismatch off. For an invalid input, it is mismatch on.

`move_count` is the length of `parsed_moves` for `hallucination`, `format_error`, `success`, and `failure`, and empty for the other outcomes. The mismatch flag is on only for a response that is a single MISMATCH line. `hallucination` is true for outcome `hallucination` and false for every other outcome of a text model. For a decision model it is `None` (JSON `null`) for every outcome without `reasons`, and `decoy` with them.

`OUTCOMES`, exported from the validator, lists the outcomes in this check order: `infrastructure_failure`, `truncated`, `malformed_output`, `abstention`, `hallucination`, `format_error`, `success`, `failure`.

## Decision path

With `decision` true, `raw_response` is a JSON array, one element per completed call, each shaped `{"answers": {"next_move": {"type": "choice", "choice": "move_3"}}, ...}`. Steps 1 to 3 above are unchanged, and the parse in step 4 is replaced by these rules:

1. The array must parse and hold at least one call. Each call needs a `next_move` choice. Anything else is `malformed_output`. Any other answer in a call, such as an old `mismatch` probability, is ignored.
2. A choice is `done`, `move_<n>`, where `n` is the 1-based position in `legal_moves()`, or, with `reasons`, `mismatch_<n>`, where `n` is the 1-based position in `reasons`, and without them `mismatch`. Each is written exactly as offered (no leading zeros, no other digits). Any other choice, including a move written out as `R` or `mismatch` under a release with reasons, is `malformed_output`.
3. The parsed moves are the moves behind the `move_<n>` choices before the first ending choice (`done` or a mismatch choice). Calls after it are ignored.
4. The mismatch flag is on if the first ending choice is a mismatch choice. `mismatch_reason` is the reason behind a `mismatch_<n>` choice.
5. Each call is read by `read_decision_call(call, legal, reasons=None) -> str | None`, which returns what a text model would have written for that choice: the move, `"done"`, `"MISMATCH <reason>"` for `mismatch_<n>`, or `"MISMATCH"` for `mismatch`, and `None` for a malformed call. [run](run.md) uses the same function to stop its loop.
6. Step 5 then runs with no impossible move possible, because the options hold only legal moves, and `decoy` is set as for a text model. The hallucination flag is `decoy` with `reasons` and `None` without. The judging in step 7 is unchanged.

## How to test

One table-driven test, one row per case, each on a fixed 2x2 input:

| Input | Response | Expected outcome |
|---|---|---|
| valid | the solving moves, one per line | `success` |
| valid | the solving moves with CRLF line endings | `success` |
| valid | the solving moves with blank lines between them | `success` |
| valid | `MISMATCH`, without reasons | `failure` |
| valid | `MISMATCH twisted corner` | `failure`, flag on, reason `twisted corner` |
| valid | `MISMATCH twisted centre` | `hallucination`, flag on, `decoy` true |
| valid | a solving list with `MISMATCH` among the lines | `format_error` |
| valid | legal moves that don't solve it | `failure` |
| valid | a solving list with `X` added at the end | `format_error` (`X` is prose) |
| valid | `R `, ` R`, or the solving moves on one line | `format_error` |
| valid | `R′` as a line | `abstention` (not a move token) |
| any | `1. R` then `2. U`, `` `R` ``, `R, U, F`, or `"R"` | `format_error` (decorated move lines), or `hallucination` with an illegal move such as `1. M` |
| any | `R.` as a line | `format_error` |
| any | `MISMATCH.`, `**MISMATCH**`, or `MISMATCH `, without reasons | `format_error`, flag off |
| any | `MISMATCH`, `MISMATCH  twisted corner`, `**MISMATCH twisted corner**`, or `MISMATCH colours look wrong`, with reasons | `format_error`, flag off; reason `twisted corner` where it is offered, else `None` |
| any | `**MISMATCH twisted centre**`, with reasons | `hallucination`, flag off, `decoy` true |
| any | legal moves then `MISMATCH twisted centre`, with reasons | `hallucination`, `impossible_move` false, `decoy` true |
| any | `I can't solve this.` or `R2 would not help here.` | `abstention` |
| valid | `r`, `Rw`, or `M` as a line | `hallucination` (move tokens that aren't legal) |
| valid | `Solution:` then `Rw U` | `hallucination` |
| valid | prose such as `I think the answer is R` | `abstention` |
| invalid | `MISMATCH`, without reasons | `success` |
| invalid | `MISMATCH` inside a ```` ``` ```` fence, without reasons | `success` |
| invalid | `MISMATCH other`, or a reason that isn't its corruption type | `success`, flag on |
| invalid | `MISMATCH twisted centre` | `hallucination`, flag on |
| invalid | `X` | `abstention` |
| invalid | `MISMATCH` then an explanation | `format_error`, flag off |
| invalid | legal moves | `failure` |
| any | the solving moves inside a ```` ```text ```` fence | same as without the fence |
| any | empty, or only blank lines | `malformed_output` |
| any | the solving moves, `stop_reason="truncated"` | `truncated` |
| any | empty, `stop_reason="refused"` | `malformed_output` |
| any | empty, `stop_reason="infrastructure_failure"` | `infrastructure_failure` |
| any | any response, `stop_reason="other"` | `ValueError` |

Decision rows, each on a 2x2 input one move from solved: a solving move then `done` (`success`), `done` first (`failure`), `mismatch` in a later call without reasons (flag on, `hallucination` `None`), `mismatch_1` with reasons (flag on, reason `twisted corner`, `hallucination` false), the decoy's `mismatch_<n>` (outcome `hallucination`, flag true), `mismatch` with reasons and `mismatch_1` without (`malformed_output`), calls after `done` or `mismatch` ignored, an old probability field ignored, malformed arrays (bad JSON, `{}`, `[]`, a missing question, an unknown or out-of-range id, a raw move name), and `infrastructure_failure` with completed calls.

Every row also checks `move_count`, `hallucination`, `mismatch`, and `mismatch_reason`. A row with `MISMATCH` and no stated setting runs with reasons. Every other row without one runs both with and without reasons and expects the same result. A decision row without reasons checks that `hallucination` is `None`. `offered_reasons` of every cube engine ends with `other`.
