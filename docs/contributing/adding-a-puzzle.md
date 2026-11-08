# Adding a puzzle

Terms are defined in [definitions.md](../definitions.md). The examples use `fto` as the new puzzle's name.

## Before you start

1. The project owner decides which puzzle is added and which moves its move group holds. For the octahedral and tetrahedral puzzles these are [open items 4 and 5](../../AGENTS.md#open). Don't write an engine before both are decided.
2. If you copy code from Cube Bench, read its licence files first, as [AGENTS.md](../../AGENTS.md#reuse) sets out.

## Files to change

### Files for the new puzzle

| File | Why |
|---|---|
| `src/puzzles/fto.py` | The engine. It implements all 11 methods of the [puzzle engine interface](../../AGENTS.md#puzzle-engine-interface) and is the only place that knows the puzzle's rules. |
| `tests/test_fto.py` | The engine's tests, like `tests/test_cube.py`. |
| `docs/specs/fto.md` | The engine's spec. Every script has one, and the engine's first line links to it. |
| `docs/puzzles/fto.md` | A short description of the puzzle: its pieces, its moves, and its corruptions. |
| `prompts/no_model/fto.txt` | The no model prompt. `src/run/prompts.py` reads `prompts/<setup>/<puzzle>.txt`, so a puzzle without its three templates has no prompts. |
| `prompts/descriptive/fto.txt` | The descriptive model prompt, which explains the puzzle's rules and notation. |
| `prompts/prescriptive/fto.txt` | The prescriptive model prompt, which lists the move group through `{legal_moves}`. |

The project owner approves the prompt text, as for the cubes.

### Shared files

| File | Why |
|---|---|
| `src/puzzles/registry.py` | One entry in `ENGINES`. It is the only list of puzzles in the code, and no other code under `src/` or `ui/` names a puzzle. |
| `docs/specs/registry.md` | Its `ENGINES` example lists every puzzle. |
| `docs/specs/README.md` | Add the engine spec to the spec list, and update the note that the octahedral and tetrahedral engines have no spec yet. |
| `config/release.toml` | Add the puzzle to `puzzles` and give its `scramble_depths`. `release` reads this file only for a major bump. |
| `docs/definitions.md` | The Puzzles section: the puzzle list, shape, move, notation, move group, move token, and half-turn metric. Some of these define only the cube rules. If the puzzle has new corruption types or a new decoy reason, update corruption, mismatch reason, and decoy reason too. |
| `AGENTS.md` | Mark open items 4 and 5 as resolved for the puzzle. |
| `docs/methodology.md` | The puzzle list, and the paragraph on the held-out input set once a release holds the puzzle. |
| `docs/assumptions.md` | The assumption about which puzzles are added. |
| `README.md` | The puzzle list under Approach, and side question 2, which asks only about cube sizes. |
| `NOTICE` | Only if you copied third-party code. |

Changes to `definitions.md` and `AGENTS.md` need the project owner's approval, because they bind the code.

### Files that need no change

1. The validator, `generate`, `run`, `evaluate`, and `release` reach every puzzle through the registry.
2. The UI shows any puzzle that isn't an NxN cube as "no drawing for <puzzle>". A drawing is a separate change to the UI and its spec.

## Steps

1. Create a branch from `main`, for example `feat/fto-engine`.
2. Write `docs/specs/fto.md` first. Build the engine to it.
3. Write `src/puzzles/fto.py` and `tests/test_fto.py`.
4. Add the entry to `src/puzzles/registry.py`, and update `docs/specs/registry.md`.
5. Write the three prompt templates and `docs/puzzles/fto.md`.
6. Update the shared docs in the table above.
7. Run `pytest`. `tests/test_pipeline.py` runs the whole flow and is the first test to check.
8. Open a pull request to `main`.
9. After the merge, cut a new major release that holds the puzzle:
   ```
   python -m src.release.release --bump major --note "Add the FTO"
   ```
   A new puzzle means a new input set, and a new input set means a new major release ([invariant 7](../../AGENTS.md#invariants)).

## Timing the merge

`src/puzzles/*.py` are assessment files, so the new engine and the registry entry change the assessment hash. `run` and `evaluate` refuse a release whose assessment hash differs from the checkout's. After the merge, `main` can't run or score any existing release until the new major release is cut.

1. Merge when no experiment is running from the `main` checkout.
2. Cut the major release straight after the merge.
3. To score an experiment under an older release later, check out that release's tag `release-<version>` first, as the [evaluate spec](../specs/evaluate.md) says.
