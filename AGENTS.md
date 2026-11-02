# AGENTS.md

Instructions for any coding agent working in this repo. The design is decided. Build it, don't redesign it. If a task needs a decision that isn't written here, ask.

## Method

`docs/definitions.md` defines every term, workflow, and metric. `docs/methodology.md` sets out the research question, the experimental variable, and how each attempt is measured. Read both first. They bind code in the same way as the invariants below. Names in code, configs, and records follow `docs/definitions.md`.

## Invariants

Do not break these. Changing one needs explicit approval from the project owner.

1. API keys come from env vars. Never commit a key.
2. Scramble count, scramble depths, valid/invalid split, attempts per input, retry cap, and max moves are config parameters, not constants. Config can list several scramble depths.
3. Each puzzle uses the standard notation AI models already know: Singmaster for 3x3 and the established equivalent for the others. No invented unified notation.
4. A deterministic validator judges answers. An AI model never judges an AI model.
5. `generate` and `run` are separate workflows. `generate` builds scrambles and invalid inputs once, records the seed, and freezes the result. `run` only reads frozen inputs. It never generates, scrambles, or edits them.
6. Every AI model and every setup sees byte-identical inputs.
7. Releases are read-only. A new input set means a new major release, a prompt change a new minor release, and an assessment fix a new patch release that mirrors the one before it.
8. Invalid inputs are extra copies of valid inputs, corrupted by the engine under their own input seed. Every input carries a validity label, and the label is authoritative.
9. AI model output is the JSON object `{"moves": [string, ...], "mismatch": true|false}` with no other keys. Output that doesn't parse, is cut off at the token limit, or is a refusal, including a content-filter refusal returned as an API error, gets outcome `malformed_output`, counted apart from failures and hallucinations. A decision model's raw response is instead the JSON array of its calls' answers, and the validator builds the moves from its `next_move` choices and sets the mismatch flag when the last choice is `mismatch`.
10. Retry only infrastructure failures, up to the retry cap. Never re-ask because an answer is wrong or malformed. When the cap is reached, the attempt still gets a raw record, with outcome `infrastructure_failure`. For a decision model, the retry cap counts retries across all calls of an attempt, and the raw record keeps the calls that completed.
11. `results/<experiment id>/raw/` holds one raw record per attempt and is append-only. Nothing edits it.
12. Every report can be recomputed from the experiment's raw records, its release, and config. `evaluate` re-validates every raw response, so an assessment fix means a patch release and a new report under it, never running the AI models again or editing raw records. Metrics, including anything that depends on the reference solver, are never stored in raw records.
13. Every raw record carries its full context: experiment id, release version, input id, input set id, puzzle, scramble depth, validity label, setup, prompt version, AI model, seed, input seed, attempt number, raw response, parsed moves, outcome, hallucination flag, mismatch flag, move count, input tokens, output tokens, retry input tokens, retry output tokens, latency, stop reason, and served model. For a decision model, tokens and latency are summed over its calls, and the served model joins the distinct values.
14. `legal_moves()` in each engine is the only definition of a puzzle's move group. The prescriptive move list is exactly that list, and the validator reads it directly with an exact string match. No second copy exists anywhere.
15. Raw records store token counts as the API returned them, never a cost. Token prices live in config, and reports compute cost from them, so a price change only means recomputing the reports.
16. The prompt contains the rendered state and never the scramble.
17. Every experiment report names the release it was scored under and links to that release's inputs and prompts. It never copies them.

## Structure

The folder layout is in [README.md](README.md#structure). Keep it in that one place.

`prompts/` is top-level because the setup is a variable. Language: Python.

Every script has a spec in [docs/specs/](docs/specs/README.md) and starts with a comment linking to it. Build a script to its spec. If the code needs to differ from the spec, change the spec in the same pull request.

## Puzzle engine interface

Every engine implements:

1. `legal_moves()` returns the puzzle's move group in standard notation.
2. `solved_state()` returns the solved state in its standard orientation.
3. `load_state(input)` returns the state and checks it against the input's validity label. A disagreement raises an error, never a silent relabel.
4. `apply_move(state, move)` returns the new state. It accepts only moves from `legal_moves()` and raises on anything else. The validator never uses it to decide whether a move is legal.
5. `is_solved(state)` returns true when every face shows a single colour, whatever the orientation of the whole puzzle.
6. `scramble(input_seed, depth)` returns the state and the move sequence that produced it. Both go into the frozen input. `generate` derives each input seed from the config seed and passes it in.
7. `corrupt(state, input_seed)` returns a state that can't be reached from the solved state by legal moves, and a description of the corruption applied.
8. `render(state)` returns the text form of the state for the prompt.
9. `reference_length(state)` returns the reference length in the half-turn metric. It accepts valid states only and raises on invalid ones.

Adding a puzzle means one new engine, one registry entry, one short description in `docs/puzzles/<puzzle>.md`, and its tests. If anything else has to change, the interface is wrong. Stop and ask.

## Reuse

Cube Bench (arXiv 2512.20595, code at github.com/dana-23/cube-bench) is the prior art. Reusing its code is planned, not done.

1. Its licence is split: `LICENSE.MIT` covers code, `LICENSE.CC-BY-4.0` covers data and docs, and it ships a `NOTICE`. Read those files before copying anything, and record what you copied in our `NOTICE`.
2. Candidates for reuse are `sim/` and `optimal/`. Its engine, `src/cube_bench/sim/cube_simulator.py`, handles 3x3 only. 2x2 and 5x5 need an NxN generalization.
3. Octahedral and tetrahedral need new engines.
4. Don't reuse Cube Bench prompts or evaluation. That's where this study differs: the three setups, hallucination as an impossible move, and mismatch detection.
5. The README cites Cube Bench and HalluLens.

## Git

1. Do every change on a branch and open a pull request for it.
2. Never merge to `main` or push to it directly unless the user explicitly says to.

## UI

1. After changes reach the checkout that the running UI serves from, restart the UI server so it runs the new code. The page files in `ui/static/` are read on every request, but Python code is loaded once at start-up.
2. Restart only when no job is running. Stop the server with SIGTERM, which stops its jobs, and start it again with `./ui/start.sh`. If a job is running, say so and leave the server as it is.

### Architecture

Decided by the project owner on 2026-10-25. The full design is in [docs/specs/ui.md](docs/specs/ui.md).

1. Git is the only source of persistent data. The UI reads releases, prompts, inputs, docs, the README, and `config/models.toml` from `origin/main`, and experiments from `origin/results/*`, with `git fetch`, `git show`, and `git ls-tree`. It never lists the work tree. The one exception is an experiment with a live job in this server, which is read from its local `results/<experiment id>` branch and marked as not pushed.
2. `ui/` holds code only. No data file, and no copy of data held elsewhere in the repo, lives there.
3. The UI process writes only `./secrets/`. Experiment data reaches git through `run`, `evaluate`, and the commit step, which write to the branch `results/<experiment id>`. The UI never writes `config/experiments/<experiment id>.toml`. It passes the experiment config to `run` on stdin.
4. One experiment is one branch, `results/<experiment id>`. The New Experiment screen names the id from the chosen AI models and puzzles by default, and picking an existing branch loads that experiment.
5. The server builds one structured bundle per release, with everything the menu shows, and keeps it in memory only, keyed by the shas of the refs it read. The page caches each bundle in browser storage and renders from it at once. The refresh icon at the bottom of the menu fetches from GitHub and replaces the bundle.
6. The Experiments list has one row per experiment, AI model, and puzzle. Its metrics come from the committed report CSV when there is one. Otherwise they are computed from the raw records for display only, and marked with `*` and a note saying so.
7. The Puzzles page lists as not allowed only the impossible moves AI models returned in pushed experiments. There is no hand-written list of impossible moves.

## Writing

1. Write all prose in plain Oxford English. Use British spelling with -ize endings (organize, realize, analyse), and always use the Oxford comma.
2. Define a term in `docs/definitions.md` before using it anywhere else, and link to it instead of restating it.

## Open

Ask before building anything that depends on these.

1. Resolved: the prompt text for each setup is in `prompts/`, approved by the project owner on 2026-10-23.
2. Reference solver for each puzzle.
3. Resolved: the output schema is in invariant 9.
4. The exact octahedral and tetrahedral puzzles, for example the face-turning octahedron (FTO) and the Pyraminx. Tetrahedral itself still needs confirmation.
5. Which moves each move group contains: whole-puzzle rotations, slice moves, and wide moves, and how each counts in the half-turn metric.
6. Repo visibility.
