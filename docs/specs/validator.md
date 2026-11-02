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
3. If `stop_reason` is `truncated` or `refused`, return `malformed_output`.
4. With `decision` false, strip one surrounding Markdown code fence, if there is one, and parse JSON. The result must be an object `{"moves": [string, ...], "mismatch": true|false}` with no other keys, as [invariant 9](../../AGENTS.md#invariants) says. Anything else is `malformed_output`. With `decision` true, see [the decision path](#decision-path) instead.
5. Mark each move as legal only if it exactly equals a string in `legal_moves()`. If any move isn't, `hallucination` is true and the outcome is `hallucination`. The first impossible move is enough: the attempt fails whatever follows it or whether the final state would be solved, `run` stores the reply whole, and the attempt is never re-asked ([run](run.md#outputs) retries only infrastructure failures).
6. Otherwise, apply every move to the input's state with `apply_move()`.
7. Return `success` if the expected result is reached and `failure` if not. For a valid input, the expected result is solved with mismatch off. For an invalid input, it is mismatch on.

`move_count` is the length of `parsed_moves`, and empty for the first two outcomes. `mismatch` and `hallucination` are false for the first two outcomes.

## Decision path

With `decision` true, `raw_response` is a JSON array, one element per completed call, each shaped `{"answers": {"next_move": {"type": "choice", "choice": "move_3"}, "mismatch": {"type": "noul", "noul": 0.12}}, ...}`. Steps 1 to 3 above are unchanged, and the parse in step 4 is replaced by these rules:

1. The array must parse and hold at least one call. Each call needs a `next_move` choice and a finite `mismatch` probability from 0 to 1. Anything else is `malformed_output`.
2. A choice is `done` or `move_<n>`, where `n` is the 1-based position in `legal_moves()`, written exactly as offered (no leading zeros, no other digits). Any other choice, including a move written out as `R`, is `malformed_output`.
3. The parsed moves are the moves behind the `move_<n>` choices before the first `done`. Calls after `done` are ignored.
4. The mismatch flag is on if any call up to and including the first `done` has a `mismatch` probability of `MISMATCH_THRESHOLD` (0.5) or more.
5. Steps 5 to 7 are unchanged. The options are exactly the legal moves and `done`, so a decision model's hallucination rate is 0 by construction.

## How to test

One table-driven test, one row per case, each on a fixed 2x2 input:

| Input | Response | Expected outcome |
|---|---|---|
| valid | moves that solve it, mismatch off | `success` |
| valid | moves that solve it, mismatch on | `failure` |
| valid | `[]`, mismatch off | `failure` |
| valid | legal moves that don't solve it | `failure` |
| valid | a solving list with `"X"` added at the end | `hallucination` |
| valid | `["R "]`, `["R′"]`, `["r"]`, `["Rw"]` | `hallucination` |
| invalid | `[]`, mismatch on | `success` |
| invalid | `["X"]`, mismatch on | `hallucination` |
| invalid | legal moves, mismatch off | `failure` |
| any | `not json` | `malformed_output` |
| any | the same JSON inside a ```` ```json ```` fence | same as without the fence |
| any | valid JSON, `stop_reason="truncated"` | `malformed_output` |
| any | empty, `stop_reason="infrastructure_failure"` | `infrastructure_failure` |
| any | any response, `stop_reason="other"` | `ValueError` |

Decision rows, each on a 2x2 input one move from solved: a solving move then `done` (`success`), `done` first (`failure`), a mismatch probability of 0.7 in a later call (flag on), calls after `done` ignored, malformed arrays (bad JSON, `{}`, `[]`, a missing question, an unknown or out-of-range id, a raw move name, a non-numeric probability), and `infrastructure_failure` with completed calls.

Every row also checks `move_count`, `hallucination`, and `mismatch`.
