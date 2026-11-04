# Definitions

Every term below means the same thing in code, configs, records, reports, and docs. Each concept has one name. If a word is used in this project with a meaning that isn't here, add it here first.

## Puzzles

1. **Twisty puzzle.** A puzzle whose parts turn around fixed axes, so that each turn moves pieces to new positions.
2. **Puzzle.** A twisty puzzle covered by the study, implemented as one engine. The current puzzles are the 2x2, 3x3, and 5x5 cubes, an octahedral puzzle, and a tetrahedral puzzle. The exact octahedral and tetrahedral puzzles are still [open](../AGENTS.md#open).
3. **Shape.** The solid a puzzle is built on. The cubes are cubes, the octahedral puzzle is an octahedron with 8 faces, and the tetrahedral puzzle is a tetrahedron with 4 faces. The shape fixes the number of faces and colours.
4. **Cube.** A puzzle with the shape of a cube and six coloured faces. An NxN cube has N layers along each axis: 2x2, 3x3, or 5x5.
5. **Engine.** The code for one puzzle. It implements the [puzzle engine interface](../AGENTS.md#puzzle-engine-interface) and is the only place that knows the puzzle's rules.
6. **Registry.** The list that maps each puzzle name to its engine. Adding a puzzle adds one entry.
7. **State.** The arrangement of colours on every face of a puzzle at one moment.
8. **Solved state.** A state where every face shows a single colour. The orientation of the whole puzzle doesn't matter, so a 2x2 turned upside down is still solved. `is_solved()` checks colours this way and never compares with `solved_state()`.
9. **Move.** One turn of one part of the puzzle, written in the puzzle's standard notation. Whether whole-puzzle rotations and wide moves are moves is still [open](../AGENTS.md#open).
10. **Notation.** The standard way to write moves for a puzzle, the one AI models already know from their training data. For the 3x3 cube that is Singmaster notation, for example `R`, `U'`, and `F2`.
11. **Move group.** The full list of moves a puzzle allows, as returned by its engine's `legal_moves()`. It is the only definition of a puzzle's moves. Whether it includes whole-puzzle rotations, slice moves, and wide moves is still [open](../AGENTS.md#open) for each puzzle.
12. **Legal move.** A string that exactly matches a move in the puzzle's move group. There is no normalization, so `r` doesn't match `R`, `′` doesn't match `'`, and a move with surrounding spaces doesn't match at all.
13. **Move token.** A string written in the shape of a move in the puzzle's notation, whether or not the puzzle allows it, as decided by the engine's `is_move_token()`. For the cubes that is a face letter (`U`, `R`, `F`, `D`, `L`, or `B`) with an optional layer count and an optional `w`, or a lower-case face letter (a wide move), a slice letter (`M`, `E`, or `S`), or a rotation letter (`x`, `y`, or `z`), then an optional `'` or `2` or both, for example `R`, `r'`, `Rw2`, `3Fw`, `M`, `x2`, and `R2'`. Every legal move is a move token. A move token that isn't a legal move is an impossible move.
14. **Impossible move.** A move token an AI model returns that isn't a legal move for that puzzle. A move that exists on another puzzle but not on this one is impossible here. Prose is not an impossible move: see [abstention](#attempts-and-outcomes).
15. **Scramble.** A sequence of legal moves, chosen from the input seed and applied to the solved state. Two consecutive moves never turn the same part of the puzzle, so no move cancels or merges with the one before it. Each engine defines which moves turn the same part. `generate` rejects any scramble that leaves the puzzle solved, checked with `is_solved()`.
16. **Scramble depth.** The number of moves in a scramble. Config lists one or more depths, and every input records its own. Depth is an upper bound on the optimal distance to solved, not a measure of it, because a scramble can happen to end close to solved.
17. **Scramble count.** The number of scrambles `generate` makes for each puzzle and scramble depth. A config parameter.
18. **Seed.** The number in config that makes the random choices in `generate` repeatable. The same config, including the seed, always produces the same input set.
19. **Input seed.** The seed for one input, which `generate` derives from the seed and the input's position in the input set. Every scramble and corruption uses its input's seed, so no two inputs share their random choices.
20. **Rendered state.** The text form of a state that goes into the prompt, produced by the engine's `render()`. It is the same under every setup.
21. **Corruption.** The change the engine's `corrupt()` applies to a valid state to make an invalid one. Every invalid input records its corruption. Its description starts with its **corruption type**, two words naming the kind of change, followed by the pieces it changed: `twisted corner`, `flipped edge`, `swapped corners`, `swapped edges`, or `recoloured sticker`.

## Inputs

1. **Input.** One frozen puzzle state given to an AI model. It records its id, input set id, input seed, puzzle, state, scramble, scramble depth, and validity label. An invalid input also records its source input id and its corruption.
2. **Valid input.** An input whose state can be reached from the solved state by legal moves.
3. **Invalid input.** An input whose state can't be reached from the solved state by legal moves. `generate` makes one as an extra copy of a valid input, its source, and applies a corruption under its own input seed. The source stays in the input set. The invalid input keeps the scramble and scramble depth of its source.
4. **Source input id.** The id of the valid input an invalid input was made from.
5. **Validity label.** The valid or invalid label `generate` gives each input. The label is authoritative. `load_state()` only checks it, and a disagreement raises an error, because it means a bug in the engine or in `generate`.
6. **Valid/invalid split.** The share of valid inputs for which `generate` also makes an invalid copy. A config parameter.
7. **Input set.** All inputs made by one `generate` call, under one config.
8. **Input set id.** The id of an input set. It is the major number of the release that first holds the input set. Every input and every raw record carries it.
9. **Frozen.** Written once and never changed again. A different input set needs a new major release.

## Releases and experiments

1. **Release.** A frozen bundle in `releases/<release version>/` that holds everything an AI model sees and everything that judges it: the input set, the prompt templates, and the assessment. Each release has a git tag `release-<release version>`.
2. **Release version.** `MAJOR.MINOR.PATCH`. A new input set bumps MAJOR. A prompt change with the same input set bumps MINOR. An assessment fix bumps PATCH.
3. **Mirror.** A patch release is a mirror of the release before it: its input set and every prompt version are identical, and only the assessment differs. A patch release may also add `decision_prompt_versions` to a release that lacked them, because no earlier raw record used them. Raw records made under one release are scored under any of its mirrors without calling an AI model again.
4. **Assessment.** The code that judges attempts and computes metrics: the validator, the engines, `evaluate`, the decision loop, and the code that builds its states. The code that only formats the experiment report isn't part of it. A release pins the assessment as one hash over those files.
5. **Experiment.** One `run` of every AI model in an experiment config over one release, and the reports computed from it.
6. **Experiment id.** The name of an experiment config file, without the extension. Every raw record carries it.
7. **Experiment report.** The Markdown file `results/<experiment id>/<release version>.md`. It starts with the release it was scored under, and it links to the release's inputs and prompts instead of copying them.

## Workflows

1. **`generate`.** Builds an input set once. It never talks to an AI model. Only `release` calls it, for a major release.
2. **`release`.** Freezes a new release from the current input set, prompt templates, and assessment, and refuses if the change doesn't match the version bump.
3. **`run`.** Sends every input of one release to every AI model under every setup, validates each attempt, and appends one raw record per attempt. It never changes a release.
4. **`evaluate`.** Re-validates every attempt of one experiment from its raw response under one release, then computes the metrics into reports. It never edits raw records.
5. **Validator.** The deterministic code that turns a raw response into parsed moves, flags, a move count, and an outcome. `run` calls it before writing each raw record, and `evaluate` calls it again. If a validator fix changes an outcome, the reports follow the outcome from `evaluate`, and the raw record stays as written. No AI model judges another AI model.
6. **Parallel requests.** The number of attempts `run` keeps in flight at once in one process, set with `--parallel`. It changes how fast an experiment runs and never what any attempt sends or records.

## Setups

1. **AI model.** The language model being tested. Which ones are tested comes from config.
2. **System-1 model.** An AI model that answers directly, without a separate reasoning step before the answer.
3. **Decision model.** An AI model that chooses among options defined in the request and never generates text. It answers through a per-move loop of [calls](#attempts-and-outcomes), so it can't return an impossible move. Its options are the [decision options](#setups).
4. **System-2 model.** An AI model trained to reason in tokens before it answers. It stays a system-2 model when an experiment runs it with reasoning switched off. Which kind an AI model is comes from the `kind` field of its entry in config.
5. **Ontology model.** The rules of the system the AI model works in. For a puzzle, that means its pieces, its legal moves, and what each move does.
6. **Setup.** How the ontology model goes into the prompt. There are three setups, and every input goes through all three.
7. **No model.** The setup where the prompt asks the AI model to solve the puzzle and gives no rules.
8. **Descriptive model.** The setup where the prompt explains the rules: what the puzzle is, how its moves work, and what the notation means. The AI model chooses moves on its own.
9. **Prescriptive model.** The setup where the prompt lists the puzzle's move group, exactly as `legal_moves()` returns it, and the AI model must pick every move from that list. Only the prompt states the list. The output schema doesn't enforce it, so a move off the list is still possible, and it is an impossible move.
10. **Prompt.** The full text sent to the AI model for one attempt. It contains the rendered state and never the scramble, because reversing the scramble solves the puzzle. It is the same for every AI model under the same setup and input.
11. **Prompt version.** The version of the prompt text for one setup and puzzle in a release: the first 12 hex characters of one sha256 over every prompt built for that setup and puzzle, in input order. A change to the template, to `render()`, or to `legal_moves()` gives a new version.
12. **Decision options.** The options of a decision model's move question: one per legal move, with id `move_<n>`, where `<n>` is the move's position in `legal_moves()` from 1, plus `done`, which says the moves so far solve the puzzle, and `mismatch`, which says the state can't be reached from the solved state by legal moves. Choosing `done` or `mismatch` ends the attempt. The request holds one question, `next_move`, a choice among the options.
13. **Decision prompt version.** The version of what a decision model is sent for one setup and puzzle in a release: the first 12 hex characters of one sha256 over the bytes of `prompts/decision/questions.txt`, then, for every input in order, its state as the decision model first receives it (the prompt, then `Moves so far: none`) and its request's questions object as JSON with sorted keys. A change to the template, to `render()`, to `legal_moves()`, to the questions file, or to how the state or the request is built gives a new version. It changes no [prompt version](#setups).
14. **Reasoning effort.** How much an AI model reasons before it answers, one of `low`, `medium`, or `high`, set once per experiment in config and sent to every system-2 model in the provider's own parameter. Fixing it keeps the comparison between providers about ability, not about how long each provider lets its model think. An experiment config without it ran at each provider's default.

## Attempts and outcomes

1. **Attempt.** One or more requests to one AI model, under one setup, on one input. A decision model makes one request per move. Each input gets as many attempts per AI model and setup as config says.
2. **Attempt number.** The position of an attempt among the attempts for the same input, AI model, and setup, starting at 1.
3. **Raw record.** The stored result of one attempt in `results/<experiment id>/raw/`. It is never edited.
4. **Raw response.** The full text the API returned for an attempt, stored as received. For a decision model, it is the JSON array of the answers of every completed call, in order.
5. **Report.** The experiment report and a CSV of its metrics, computed by `evaluate` from raw records, one release, and config.
6. **Parsed moves.** The list of moves read from the AI model's output, in the order given: the tokens of its move lines. A line is a **move line** when it splits on whitespace into one or more tokens and every token is a [move token](#puzzles). Every other line is a **prose line**. Empty for outcome `abstention`. For a decision model, the moves behind each call's `next_move` choice, in call order, before the first `done` or `mismatch`.
7. **Malformed output.** A response the validator can't use: it has no lines left once blank lines are dropped (for a decision model, it doesn't parse as the array of answers, where every call holds a `next_move` choice the call offered), or the AI model or a content filter refused to answer. A content-filter refusal counts here even when the API returns it as an error, and it is never retried. A response cut off at the token limit is not malformed output: it is `truncated`. Prose instead of moves is not malformed output either: with no move line it is an `abstention`, and a prose line beside legal moves is a `format_error`.
8. **Infrastructure failure.** A network error, timeout, or rate limit. `run` retries it up to the retry cap. When the cap is reached, the raw response is empty, except that a decision-model attempt keeps the calls that completed, and the retry cap counts across all its calls.
9. **Retry cap.** The maximum number of retries for one attempt. A config parameter.
10. **Mismatch flag.** The flag set only when the whole response is the single line `MISMATCH`, which says the input describes a puzzle that can't be reached from the solved state by legal moves. For a decision model, it is on when the call that ended the attempt chose `mismatch`. Off for every other outcome, including `format_error`, `truncated`, `malformed_output`, and `infrastructure_failure`.
11. **Hallucination flag.** True when the parsed moves contain at least one impossible move, which is outcome `hallucination`. False for outcomes `abstention`, `format_error`, `success`, and `failure`, and for `infrastructure_failure`, `truncated`, and `malformed_output` of a text model, which have no parsed moves to judge. Null for every outcome of a decision model, which can't return an impossible move, so there is nothing to judge.
12. **Solved.** The validator applied every parsed move to the input state in order, every move was legal, and `is_solved()` is true for the final state. An empty move list is never solved, because no input starts solved.
13. **Expected result.** For a valid input, the puzzle ends solved and the mismatch flag is off. For an invalid input, the mismatch flag is on.
14. **Outcome.** The one result the validator gives each attempt, checked in this order:
    1. `infrastructure_failure`: the retry cap was reached, so there is no complete response to judge.
    2. `truncated`: the stop reason is `truncated`, so the response was cut off at the token limit.
    3. `malformed_output`: the stop reason is `refused` (a refusal by the API or a content filter), no line is left, or, for a decision model, the raw response doesn't parse as the array of answers.
    4. `abstention`: there is no move line and no line that is exactly `MISMATCH`. The AI model answered in prose, for example to say it can't solve the puzzle.
    5. `hallucination`: a parsed move is not a legal move, so the hallucination flag is true. The attempt fails, even if the final state happens to be solved.
    6. `format_error`: every parsed move is legal, but the response isn't in the required layout: it has a prose line, a move line with more than one token or with whitespace around its token, or the line `MISMATCH` together with any other line.
    7. `success`: the expected result is reached.
    8. `failure`: every move was legal and the layout was right, but the expected result is missed. That means a valid input left unsolved or flagged, or an invalid input left unflagged.
15. **Call.** One request inside an attempt. An attempt by a [decision model](#setups) is a loop of calls, one per move, and every other attempt is one call plus its retries. Retries of a call count against the [retry cap](#attempts-and-outcomes) of the attempt.

## Recorded values

Raw records store these values. Invariant 13 in [AGENTS.md](../AGENTS.md#invariants) lists every field of a raw record.

1. **Move count.** The number of parsed moves, in the half-turn metric. Each impossible move counts as one. Set for outcomes `hallucination`, `format_error`, `success`, and `failure`. Empty for `infrastructure_failure`, `truncated`, `malformed_output`, and `abstention`.
2. **Half-turn metric.** The way moves are counted: any turn of one part, including a half turn such as `R2`, counts as one move. How whole-puzzle rotations and wide moves count is still [open](../AGENTS.md#open).
3. **Input tokens and output tokens.** The token counts the API reports for the call that produced the raw response, stored as returned. For a decision model, the sums over its completed calls. Zero for outcome `infrastructure_failure`, except that a decision model with completed calls keeps their sums, so cost counts them. For Google, output tokens are `candidates_token_count + thoughts_token_count`, both as returned, because Gemini bills thoughts as output. The other providers' output counts already include reasoning tokens.
4. **Retry input tokens and retry output tokens.** The token counts the API reports for every call in the attempt that failed, retried or not, summed and stored as returned. Zero when no call failed or the API reported no counts.
5. **Latency.** The time from sending the request to receiving the full response, for the call that produced the raw response. For a decision model, the sum over its completed calls. Empty for outcome `infrastructure_failure`, except that a decision model with completed calls keeps their sum.
6. **Stop reason.** How the call that produced the raw response ended (for a decision model, the last call of the attempt): `ok`, `truncated`, `refused`, or `infrastructure_failure`. The validator needs it, because a truncated or refused response can look like valid JSON.
7. **Served model.** The AI model id the API reported for the call, stored as returned. For a decision model, the distinct values over its calls, in first-seen order, joined with `,`. Empty when the API reports none for a call, and never filled in with the id the request asked for. Empty for outcome `infrastructure_failure`, except that a decision model with completed calls keeps its calls' values. It shows when a model alias pointed at a different model than expected.
8. **Decision flag.** True when the attempt was made by a [decision model](#setups), false otherwise. Scoring reads it from the raw record to choose how the raw response is parsed. A record written before the field existed falls back to the model's provider in the experiment config.
9. **Requested model.** The `api_model_id` the request asked for, recorded for every provider and every outcome, including `infrastructure_failure`. Compare it with the served model to see when an alias pointed elsewhere.
10. **Max moves.** The cap on the moves in one [decision-model](#setups) attempt. The attempt ends when its moves reach it. A config parameter, default twice the largest scramble depth in the release.

## Prices

1. **Token price.** The price per input token and per output token for each AI model, kept in config.
2. **Cost.** For one raw record, its input and retry input tokens times the input token price, plus its output and retry output tokens times the output token price, in USD.
3. **Worst-case request cost.** The most one request can cost, per call for a decision model, whose request then holds the state with `max_moves` moves and the questions object: the request's characters divided by 4, rounded up, as input tokens, plus `max_output_tokens` as output tokens, at the AI model's token prices.
4. **Budget.** A cost limit in USD in the experiment config. There are three:
   1. **Request budget.** No worst-case request cost may exceed it. Default 2.00 USD.
   2. **Model budget.** The cost of one AI model's raw records in one experiment may not exceed it. Default 25.00 USD.
   3. **Experiment budget.** The cost of all raw records in one experiment may not exceed it. Default 50.00 USD.

## Metrics

`evaluate` computes every metric. No metric is stored in raw records. Reports split each metric by puzzle, setup, AI model, scramble depth, and validity label, except the paired setup test, which pools scramble depths. Attempts with outcome `infrastructure_failure` are left out of every rate, consistency, and latency, and counted on their own, so the denominators never change silently. They still count in tokens per attempt and cost per success, because their failed calls cost money.

Every rate is reported with its denominator `n`, the number of inputs behind it, and a 95% bootstrap interval over inputs: inputs are drawn with replacement 2000 times, each draw keeps all attempts of the inputs drawn, and the interval is the 2.5th and 97.5th percentile of the rate over the draws. Attempts on one input aren't independent, so resampling attempts would make the interval too narrow. The draws come from a fixed seed, so the same raw records always give the same interval. The interval is n/a when fewer than 2 inputs are behind the rate.

1. **Success rate.** The share of attempts, on valid and invalid inputs, with outcome `success`. Reported separately for valid and invalid inputs, never pooled.
2. **Hallucination rate.** The share of attempts with outcome `hallucination`. n/a for decision models, which can't return an impossible move.
3. **Mismatch detection rate.** The share of attempts on invalid inputs where the mismatch flag is on, whatever the outcome. Truncated output, malformed output, abstention, and format errors count as not detected. The flag is enough. The AI model doesn't have to say what is wrong.
4. **False mismatch rate.** The share of attempts on valid inputs where the mismatch flag is on. Truncated output, malformed output, abstention, and format errors count as not flagged.
5. **Malformed output rate.** The share of attempts with outcome `malformed_output`. Malformed output never counts as a hallucination.
6. **Truncation rate.** The share of attempts with outcome `truncated`.
7. **Abstention rate.** The share of attempts with outcome `abstention`.
8. **Format error rate.** The share of attempts with outcome `format_error`.
9. **Infrastructure failure count.** The number of attempts with outcome `infrastructure_failure`.
10. **Consistency.** For one input, AI model, and setup, the share of attempts with the most common outcome. Reported as the mean over inputs. A value of 1.0 means every attempt gave the same outcome. Reported as n/a for an input with fewer than two attempts left after exclusions.
11. **Latency per attempt.** The mean latency per attempt.
12. **Tokens per attempt.** The mean input and output tokens per attempt, including retry tokens.
13. **Cost per success.** The cost of all attempts, including retry tokens, divided by the number of attempts with outcome `success`. Cost comes from token counts and token prices, never from a number stored in raw records. Reported as n/a when there are no successes.
14. **Paired setup test.** For one AI model, puzzle, validity label, and metric, a comparison of two setups on the same inputs. The metric is the success rate, the hallucination rate, or the mismatch detection rate (invalid inputs only). The hallucination rate is skipped for a decision model. Each input gets one share per setup: the share of its attempts, with outcome `infrastructure_failure` left out, that are a hit for the metric: outcome `success` for the success rate, outcome `hallucination` for the hallucination rate, and the mismatch flag on for the mismatch detection rate. The comparison is pooled over scramble depths, never over validity labels. The test is an exact two-sided sign test on the inputs whose shares differ. An input is paired only when at least one attempt that is not `infrastructure_failure` is left under each of the two setups. It reports the inputs paired, the inputs where each setup is higher, the mean share difference (second setup minus first), the p-value, and the Holm-adjusted p-value over the three setup pairs. The difference is significant when the Holm-adjusted p-value is below 0.05. Every setup sees the same inputs (invariant 6), so pairing removes input difficulty from the comparison. Using the input as the unit keeps repeated attempts on one input from counting as independent. The p-value is `n/a` when no input is paired, and 1.0 when no paired input differs.
15. **Balanced accuracy.** For one AI model, setup, and puzzle, the mean of the mismatch detection rate and one minus the false mismatch rate. 0.5 is what answering MISMATCH always, or never, scores, so only a value above 0.5 shows detection. It is reported because a model that flags most valid inputs gets a high detection rate for free.
16. **Always-MISMATCH baseline.** The scores of an answerer that returns MISMATCH on every input: detection rate 1.0, false mismatch rate 1.0, balanced accuracy 0.5, success rate 0 on valid inputs and 1.0 on invalid inputs. Reports show it beside every balanced accuracy.
