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
13. **Impossible move.** Any move an AI model returns that isn't a legal move for that puzzle. A move that exists on another puzzle but not on this one is impossible here, as is anything that isn't a move at all.
14. **Scramble.** A sequence of legal moves, chosen from the input seed and applied to the solved state. Two consecutive moves never turn the same part of the puzzle, so no move cancels or merges with the one before it. Each engine defines which moves turn the same part. `generate` rejects any scramble that leaves the puzzle solved, checked with `is_solved()`.
15. **Scramble depth.** The number of moves in a scramble. Config lists one or more depths, and every input records its own. Depth is an upper bound on the optimal distance to solved, not a measure of it, because a scramble can happen to end close to solved.
16. **Scramble count.** The number of scrambles `generate` makes for each puzzle and scramble depth. A config parameter.
17. **Seed.** The number in config that makes the random choices in `generate` repeatable. The same config, including the seed, always produces the same input set.
18. **Input seed.** The seed for one input, which `generate` derives from the seed and the input's position in the input set. Every scramble and corruption uses its input's seed, so no two inputs share their random choices.
19. **Rendered state.** The text form of a state that goes into the prompt, produced by the engine's `render()`. It is the same under every setup.
20. **Corruption.** The change the engine's `corrupt()` applies to a valid state to make an invalid one. Every invalid input records its corruption.

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
3. **Mirror.** A patch release is a mirror of the release before it: its input set and every prompt version are identical, and only the assessment differs. Raw records made under one release are scored under any of its mirrors without calling an AI model again.
4. **Assessment.** The code that judges attempts and computes metrics: the validator, the engines, and `evaluate`. The code that only formats the experiment report isn't part of it. A release pins the assessment as one hash over those files.
5. **Experiment.** One `run` of every AI model in an experiment config over one release, and the reports computed from it.
6. **Experiment id.** The name of an experiment config file, without the extension. Every raw record carries it.
7. **Experiment report.** The Markdown file `results/<experiment id>/<release version>.md`. It starts with the release it was scored under, and it links to the release's inputs and prompts instead of copying them.

## Workflows

1. **`generate`.** Builds an input set once. It never talks to an AI model. Only `release` calls it, for a major release.
2. **`release`.** Freezes a new release from the current input set, prompt templates, and assessment, and refuses if the change doesn't match the version bump.
3. **`run`.** Sends every input of one release to every AI model under every setup, validates each attempt, and appends one raw record per attempt. It never changes a release.
4. **`evaluate`.** Re-validates every attempt of one experiment from its raw response under one release, then computes the metrics into reports. It never edits raw records.
5. **Validator.** The deterministic code that turns a raw response into parsed moves, flags, a move count, and an outcome. `run` calls it before writing each raw record, and `evaluate` calls it again. If a validator fix changes an outcome, the reports follow the outcome from `evaluate`, and the raw record stays as written. No AI model judges another AI model.

## Setups

1. **AI model.** The language model being tested. Which ones are tested comes from config.
2. **Ontology model.** The rules of the system the AI model works in. For a puzzle, that means its pieces, its legal moves, and what each move does.
3. **Setup.** How the ontology model goes into the prompt. There are three setups, and every input goes through all three.
4. **No model.** The setup where the prompt asks the AI model to solve the puzzle and gives no rules.
5. **Descriptive model.** The setup where the prompt explains the rules: what the puzzle is, how its moves work, and what the notation means. The AI model chooses moves on its own.
6. **Prescriptive model.** The setup where the prompt lists the puzzle's move group, exactly as `legal_moves()` returns it, and the AI model must pick every move from that list. Only the prompt states the list. The output schema doesn't enforce it, so a move off the list is still possible, and it is an impossible move.
7. **Prompt.** The full text sent to the AI model for one attempt. It contains the rendered state and never the scramble, because reversing the scramble solves the puzzle. It is the same for every AI model under the same setup and input.
8. **Prompt version.** The version of the prompt text for one setup and puzzle in a release: the first 12 hex characters of one sha256 over every prompt built for that setup and puzzle, in input order. A change to the template, to `render()`, or to `legal_moves()` gives a new version.

## Attempts and outcomes

1. **Attempt.** One request to one AI model, under one setup, on one input. Each input gets as many attempts per AI model and setup as config says.
2. **Attempt number.** The position of an attempt among the attempts for the same input, AI model, and setup, starting at 1.
3. **Raw record.** The stored result of one attempt in `results/<experiment id>/raw/`. It is never edited.
4. **Raw response.** The full text the API returned for an attempt, stored as received.
5. **Report.** The experiment report and a CSV of its metrics, computed by `evaluate` from raw records, one release, and config.
6. **Parsed moves.** The list of moves read from the AI model's JSON output, in the order given.
7. **Malformed output.** A response the validator can't use: it doesn't parse as the required JSON, it was cut off at the token limit, or the AI model or a content filter refused to answer. A content-filter refusal counts here even when the API returns it as an error, and it is never retried.
8. **Infrastructure failure.** A network error, timeout, or rate limit. `run` retries it up to the retry cap. When the cap is reached, the raw response is empty.
9. **Retry cap.** The maximum number of retries for one attempt. A config parameter.
10. **Mismatch flag.** The flag in the AI model's JSON output that says the input describes a puzzle that can't be reached from the solved state by legal moves. Off for outcomes `malformed_output` and `infrastructure_failure`.
11. **Hallucination flag.** True when the parsed moves contain at least one impossible move. False for outcomes `malformed_output` and `infrastructure_failure`, which have no parsed moves.
12. **Solved.** The validator applied every parsed move to the input state in order, every move was legal, and `is_solved()` is true for the final state. An empty move list is never solved, because no input starts solved.
13. **Expected result.** For a valid input, the puzzle ends solved and the mismatch flag is off. For an invalid input, the mismatch flag is on. Moves returned with the flag on are still checked for impossible moves.
14. **Outcome.** The one result the validator gives each attempt, checked in this order:
    1. `infrastructure_failure`: the retry cap was reached, so there is no response to judge.
    2. `malformed_output`: malformed output.
    3. `hallucination`: the hallucination flag is true. The attempt fails, even if the final state happens to be solved.
    4. `success`: the expected result is reached.
    5. `failure`: every move was legal, but the expected result is missed. That means a valid input left unsolved or flagged, or an invalid input left unflagged.

## Recorded values

Raw records store these values. Invariant 13 in [AGENTS.md](../AGENTS.md#invariants) lists every field of a raw record.

1. **Move count.** The number of parsed moves, in the half-turn metric. Each impossible move counts as one. Empty for outcomes `infrastructure_failure` and `malformed_output`.
2. **Half-turn metric.** The way moves are counted: any turn of one part, including a half turn such as `R2`, counts as one move. How whole-puzzle rotations and wide moves count is still [open](../AGENTS.md#open).
3. **Input tokens and output tokens.** The token counts the API reports for the call that produced the raw response, stored as returned. Zero for outcome `infrastructure_failure`.
4. **Retry input tokens and retry output tokens.** The token counts the API reports for every call in the attempt that failed, retried or not, summed and stored as returned. Zero when no call failed or the API reported no counts.
5. **Latency.** The time from sending the request to receiving the full response, for the call that produced the raw response. Empty for outcome `infrastructure_failure`.
6. **Stop reason.** How the call that produced the raw response ended: `ok`, `truncated`, `refused`, or `infrastructure_failure`. The validator needs it, because a truncated or refused response can look like valid JSON.
7. **Served model.** The AI model id the API reported for the call, stored as returned. Empty for outcome `infrastructure_failure`. It shows when a model alias pointed at a different model than expected.

## Baseline and prices

1. **Reference solver.** The program that solves each valid input to give a baseline move count. Every AI model is compared against the same reference solver. Computing the true optimum on 2x2 and 3x3 is optional and only checks the reference solver.
2. **Reference length.** The number of moves `reference_length()` returns for a valid input's state, in the half-turn metric. Never zero, because no input starts solved. It is the reference solver's count, not the optimal distance, so it can exceed the scramble depth when the reference solver isn't optimal. Invalid inputs have no reference length.
3. **Token price.** The price per input token and per output token for each AI model, kept in config.

## Metrics

`evaluate` computes every metric. No metric is stored in raw records. Reports split each metric by puzzle, setup, AI model, scramble depth, and validity label. Attempts with outcome `infrastructure_failure` are left out of every rate, efficiency, consistency, and latency, and counted on their own, so the denominators never change silently. They still count in tokens per attempt and cost per success, because their failed calls cost money.

Every rate is reported with its denominator `n` and a 95% Wilson score interval, because a rate from a few dozen attempts can move by more than ten points by chance.

1. **Success rate.** The share of attempts, on valid and invalid inputs, with outcome `success`.
2. **Hallucination rate.** The share of attempts with outcome `hallucination`.
3. **Mismatch detection rate.** The share of attempts on invalid inputs where the mismatch flag is on, whatever the outcome. Malformed output counts as not detected. The flag is enough. The AI model doesn't have to say what is wrong.
4. **False mismatch rate.** The share of attempts on valid inputs where the mismatch flag is on. Malformed output counts as not flagged.
5. **Malformed output rate.** The share of attempts with outcome `malformed_output`. Malformed output never counts as a hallucination.
6. **Infrastructure failure count.** The number of attempts with outcome `infrastructure_failure`.
7. **Efficiency.** Move count divided by reference length, over attempts with outcome `success` on valid inputs. A value of 1.0 means as short as the reference.
8. **Consistency.** For one input, AI model, and setup, the share of attempts with the most common outcome. Reported as the mean over inputs. A value of 1.0 means every attempt gave the same outcome. Reported as n/a for an input with fewer than two attempts left after exclusions.
9. **Latency per attempt.** The mean latency per attempt.
10. **Tokens per attempt.** The mean input and output tokens per attempt, including retry tokens.
11. **Cost per success.** The cost of all attempts, including retry tokens, divided by the number of attempts with outcome `success`. Cost comes from token counts and token prices, never from a number stored in raw records. Reported as n/a when there are no successes.
