# validator

File: `src/validator.py`.

## Purpose

The [validator](../definitions.md#workflows). It turns one raw response into parsed moves, flags, a move count, and an [outcome](../definitions.md#attempts-and-outcomes). [run](run.md) calls it before writing a raw record, and [evaluate](evaluate.md) calls it again. It has no randomness and no network access.

## Inputs

1. An input, as one line of `inputs.jsonl`.
2. `raw_response`: the text the AI model returned. Empty for an infrastructure failure.
3. `stop_reason`: `ok`, `truncated`, `refused`, or `infrastructure_failure`.

## Outputs

`validate(input, raw_response, stop_reason) -> Verdict`, where `Verdict` has `parsed_moves`, `hallucination`, `mismatch`, `move_count`, and `outcome`.

Steps, in order:

1. If `stop_reason` is not one of the four values above, raise `ValueError`.
2. If `stop_reason` is `infrastructure_failure`, return outcome `infrastructure_failure`.
3. If `stop_reason` is `truncated` or `refused`, return `malformed_output`.
4. Strip one surrounding Markdown code fence, if there is one, and parse JSON. The result must be an object `{"moves": [string, ...], "mismatch": true|false}` with no other keys, as [invariant 9](../../AGENTS.md#invariants) says. Anything else is `malformed_output`.
5. Mark each move as legal only if it exactly equals a string in `legal_moves()`. If any move isn't, `hallucination` is true and the outcome is `hallucination`.
6. Otherwise, apply every move to the input's state with `apply_move()`.
7. Return `success` if the expected result is reached and `failure` if not. For a valid input, the expected result is solved with mismatch off. For an invalid input, it is mismatch on.

`move_count` is the length of `parsed_moves`, and empty for the first two outcomes. `mismatch` and `hallucination` are false for the first two outcomes.

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

Every row also checks `move_count`, `hallucination`, and `mismatch`.
