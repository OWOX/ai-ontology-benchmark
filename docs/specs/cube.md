# cube

File: `src/puzzles/cube.py`.

## Purpose

One [engine](engine.md) for every NxN cube. `CubeEngine(n)` handles the 2x2 and 3x3 now. The 5x5 waits on [open item 5](../../AGENTS.md#open).

## Inputs

1. `n`: 2 or 3. 5 waits on [open item 5](../../AGENTS.md#open).
2. A state is a string of 6·n² colour letters, one per sticker, with faces in the order U, R, F, D, L, B and stickers in each face read row by row from the top left. A solved 2x2 is `UUUURRRRFFFFDDDDLLLLBBBB`.

## Outputs

The nine interface methods:

1. `legal_moves()` returns the move group in Singmaster notation. For 2x2 and 3x3 that is the 18 face turns: `U U' U2 R R' R2 F F' F2 D D' D2 L L' L2 B B' B2`.
2. `solved_state()` returns the solved string above.
3. `load_state(input)` returns the input's state. It raises `ValidityMismatchError` if the reachability check below disagrees with the input's validity label.
4. `apply_move(state, move)` returns the new state. It raises `IllegalMoveError` for any string not in `legal_moves()`.
5. `is_solved(state)` returns true when all stickers on each face share one colour, whatever that colour is.
6. `scramble(input_seed, depth)` returns `(state, moves)`. It picks moves with `random.Random(input_seed)`, never picks two moves in a row on the same face, and draws again if the result is solved.
7. `corrupt(state, input_seed)` returns `(state, description)`. It twists one corner in place. On the 3x3 it may instead flip one edge, chosen by the input seed. The description names the piece and the change, for example `"twisted corner UFR clockwise"`.
8. `render(state)` returns a text net of the six faces, one face block per label, with the colour letters spaced out.
9. `reference_length(state)` returns the optimal length found by IDA* search on the 2x2. On the 3x3 and 5x5 it raises `NotImplementedError` until a reference solver is chosen ([open item 2](../../AGENTS.md#open)). It raises `ValueError` on an invalid state.

The reachability check for `load_state()` and `reference_length()` tests corner twist sum, edge flip sum, and permutation parity.

The 3x3 code may reuse Cube Bench's `sim/`. Anything copied goes into `NOTICE`, as [AGENTS.md](../../AGENTS.md#reuse) says.

## How to test

1. Each face turn applied four times, and each half turn applied twice, returns the start state.
2. `R U R' U'` applied six times to a solved 3x3 returns solved.
3. A solved state turned as a whole cube, by applying the same rotation to all faces, still passes `is_solved()`.
4. `apply_move(state, "r")`, `apply_move(state, "R ")`, and `apply_move(state, "R′")` each raise `IllegalMoveError`.
5. `scramble()` with the same seed gives the same result twice. Over 1,000 seeds, no scramble has two consecutive moves on one face and none ends solved.
6. Every `corrupt()` output fails the reachability check, and every scramble output passes it.
7. `load_state()` raises on a valid state labelled invalid, and on an invalid state labelled valid.
8. On the 2x2, `reference_length()` of a scramble is at least 1 and at most its depth, and the IDA* result matches a breadth-first search on 20 random states.

## Open

1. The 5x5 move group: whether it includes wide moves, slice moves, and whole-cube rotations ([open item 5](../../AGENTS.md#open)). Until that is answered, `CubeEngine(5)` raises `NotImplementedError`.
2. Reference solvers for the 3x3 and 5x5 ([open item 2](../../AGENTS.md#open)).
