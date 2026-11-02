# Decision models: design

Status: design approved in conversation on 2026-11-01. Waiting for written review.

## Goal

Add three decision models to the study: Jev from TypeSafe AI, and Clef and Clef-flash from Cloudflare Workers AI. They answer the same frozen inputs under the same three setups as the other AI models. The same validator judges them, and `evaluate` computes the same metrics. Their `kind` is `system-1`.

Success means a real `run` writes raw records for these models that `evaluate` scores like any other AI model's, with every invariant change approved by the project owner first.

## Why they need their own path

A decision model takes a `state` and a set of typed questions, and returns a probability for every option of every question. It never generates text. Cloudflare's model page says so directly: "it does not generate text". So it can't return the `{"moves": [...], "mismatch": ...}` object that invariant 9 requires. Each attempt therefore runs as a loop of calls, one move per call, and the validator builds the moves and the mismatch flag from the recorded answers.

## Decisions

1. The model works blind. Every call carries the start state and the moves the model chose so far. `run` never applies a move, so the task matches the one the LLMs get.
2. An attempt ends when the model picks `done`, when the mismatch probability reaches 0.5 in any call, or when the move count reaches `max_moves`.
3. The mismatch question is asked in every call. The flag is on if any call's probability is 0.5 or more, and the loop stops at that call.
4. The raw response holds every call's answers as returned. The validator, never `run`, turns them into moves and a flag, so a rule fix is a patch release and never a re-run.
5. The retry cap covers the whole attempt, across all its calls. Reaching it gives outcome `infrastructure_failure`, which every rate leaves out, as for the LLMs. The raw response keeps the calls that completed, for audit, and their tokens count toward cost.
6. Clef needs an API token and an account id. Both are secrets: env vars `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`, or `secrets/cloudflare.json` with `api_key` and `account_id`.
7. The `state` of every call is the exact prompt the LLMs get under that setup, byte for byte, followed by the moves so far. The question wording lives in a new prompt file.
8. Both providers use their official Python SDKs: `typesafe-sdk` for Jev and `cloudflare` for Clef. SDK retries are switched off in both.

## The loop

One attempt for one input, setup, and decision model:

1. Build the setup's prompt as for any AI model. Call it `P`.
2. For call `k` (from 1), send:
   1. `state`: `P`, a blank line, then `Moves so far: ` and the chosen moves joined by single spaces, or `none` for the first call.
   2. Question `next_move`, type `choice`. Its options are every move of `legal_moves()` in engine order, then `done`. Each option's description is the move string itself, and `done` has the description from the questions file.
   3. Question `mismatch`, type `noul` (a yes/no probability), with the wording from the questions file.
3. Stop after call `k` when its `mismatch` probability is 0.5 or more, or its `next_move` choice is `done`. Otherwise add the choice to the moves. Stop when the moves number `max_moves`, and else make call `k + 1`.

`max_moves` is a new config parameter. Its default is twice the largest scramble depth in the release.

The model only ever sees its own moves. It never sees a state after a move, and `run` never calls the engine.

## Clients

All provider code stays in `src/run/models.py`, the only file that talks to an AI model API.

1. Provider `typesafe`. The client is `typesafe_sdk`'s, with its key from `TYPESAFE_API_KEY` and retries off. It calls the System One endpoint with `model`, `state`, and `questions`.
2. Provider `cloudflare`. The client is `cloudflare.Cloudflare` with `api_token` from `CLOUDFLARE_API_TOKEN` and `max_retries=0`. It calls `client.ai.run(api_model_id, account_id=..., extra_body={"model": ..., "state": ..., "questions": ...})`. The SDK has no typed request for decision models, so the body goes through `extra_body`.
3. Each client makes one call and returns the answers, the usage, the served model, and the latency, or raises `InfrastructureError` on a network error, a timeout, HTTP 429, or HTTP 5xx. A content-filter refusal is not retried and is recorded as a refusal, as for the LLMs.
4. A loop driver in `src/run/` runs the loop above. It counts retries across all calls of the attempt against `retry_cap`, and asks the budget check before every call, the same way `call_with_retries` does now.

`KEY_VARIABLES` gains `typesafe` and `cloudflare`. Cloudflare has two variables, so the key store, the UI's secrets endpoint, and the Models edit row learn a second field for that provider: Account id.

## Raw record

The record keeps every field of invariant 13. For a decision model:

1. Raw response: a JSON array, one element per completed call, in order. Each element is `{"answers": ..., "usage": ..., "model": ...}` exactly as the API returned them.
2. Input tokens and output tokens: the sums over completed calls, as returned. Clef and Jev report output tokens as 0 or a small number, and both bill output at 0.
3. Retry input tokens and retry output tokens: the sums over failed calls. When the cap is reached, the completed calls' tokens stay in input and output tokens, so cost still counts them.
4. Latency: the sum of the completed calls' latencies.
5. Stop reason: `ok`, `refused`, or `infrastructure_failure`. Never `truncated`, because Clef cuts an over-long text state without saying so. Every prompt in this study is far below Clef-flash's 24,576-token context, so the spec records this limit instead of detecting it.
6. Served model: the distinct `model` values of the calls, in first-seen order, joined with `,`.
7. Parsed moves, the mismatch flag, the hallucination flag, the move count, and the outcome: from the validator, as for every AI model.

## Validator

The validator gets a second parse path. It picks the path from the AI model's provider: `DECISION_PROVIDERS = {"typesafe", "cloudflare"}` in `src/run/models.py`. It never guesses from the text.

1. Parse the raw response as the JSON array above. If it doesn't parse, or a call lacks `next_move` or `mismatch`, or a `next_move` choice isn't one of the offered options, the outcome is `malformed_output`.
2. The mismatch flag is on if any call's `mismatch` probability is 0.5 or more.
3. The parsed moves are the `next_move` choices of every call before the first `done`, leaving out `done`.
4. The stop reason `infrastructure_failure` gives outcome `infrastructure_failure`, whatever the array holds.
5. Every later step is unchanged: the same legality check, the same `apply_move` sequence, the same `is_solved()`, and the same outcome order.

The options are exactly the legal moves and `done`, so a decision model can't return an impossible move. Its hallucination rate is 0 by construction.

## Prompts

A new file, `prompts/decision/questions.txt`, holds the two question texts and the description of `done`. It is a prompt, so the project owner approves its text, and a change to it is a new minor release. The prompt version for a decision model covers the setup's prompts and this file.

Draft text for approval:

1. `next_move`: "Which move should be applied next to solve the puzzle, after the moves so far? Pick done when the moves so far solve it."
2. `done`: "The moves so far solve the puzzle."
3. `mismatch`: "Is this state impossible to reach from the solved state by legal moves?"

## Catalogue and prices

`config/models.toml` gains three entries, each `kind = "system-1"` and `params = {}`:

| name | provider | api_model_id |
|---|---|---|
| `jev` | `typesafe` | to check with `GET /v1/models` before committing: `jev-1.13.0` pinned, or `jev-latest` |
| `clef` | `cloudflare` | `@cf/cloudflare/clef` |
| `clef-flash` | `cloudflare` | `@cf/cloudflare/clef-flash` |

`config/prices.toml`, per million tokens:

| model | input | output | source |
|---|---|---|---|
| `clef` | 0.24 | 0 | Cloudflare model page and changelog, 2026-10-09 |
| `clef-flash` | 0.038 | 0 | Cloudflare model page and changelog, 2026-10-09 |
| `jev` | 0.042 | 0 | third-party only. Check against TypeSafe's pricing before committing. |

The worst-case request cost stays a per-call figure. The worst case for one attempt is that figure times `max_moves`, and the budget check runs before every call.

## Docs and invariants

Every change below needs the project owner's approval before it is merged.

1. Invariant 2: add `max_moves` to the config parameters.
2. Invariant 9: add that a decision model's raw response is the array of its calls' answers, and the validator builds the moves and the mismatch flag from it.
3. Invariant 10: add that for a decision model the retry cap counts across all calls of an attempt, and the raw response keeps the calls that completed.
4. Invariant 13: add that a decision model's tokens and latency are summed over calls, and its served model joins the distinct values.
5. `docs/definitions.md`: add decision model, call, and `max_moves`. Change attempt (one or more requests), raw response, input and output tokens, latency, served model, stop reason, malformed output, and worst-case request cost.
6. `docs/methodology.md`: a short paragraph on decision models and the consequences below.
7. Specs: `docs/specs/models.md`, `run.md`, `validator.md`, `config.md`, `prompts.md`, and `ui.md` follow the code in the same pull request.

## Consequences for the results

1. A decision model's hallucination rate is always 0. Reports show it as 0 for these models, and the methodology says why.
2. The move list is offered under every setup, including no model. The setups differ less for decision models than for LLMs, so a setup effect is harder to see in them.
3. A network failure never counts against the success rate. The attempt is `infrastructure_failure` and every rate leaves it out.
4. A long loop is more likely to reach the retry cap than a single LLM call, so these models may show more infrastructure failures.

## Testing

No test touches the network.

1. Clients: both SDKs stubbed. Cases are a normal answer, HTTP 429 and 5xx raising `InfrastructureError`, a refusal, and a 400 that isn't retried.
2. Loop driver: canned answers for stopping on `done`, on mismatch in the first and in a later call, on `max_moves`, and on reaching the retry cap partway through, with the token and latency sums.
3. Validator: recorded arrays for success, failure, mismatch, malformed (bad JSON, missing question, unknown choice), and `infrastructure_failure` with completed calls.
4. End to end: `run` and then `evaluate` with a fake decision provider, checking that the report rates match the outcomes.
5. UI: the Cloudflare edit row saves and clears both fields, and the page never shows either value.
