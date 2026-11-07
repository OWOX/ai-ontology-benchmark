# cube

File: `src/puzzles/cube.py`.

## Purpose

One [engine](engine.md) for every NxN cube. `CubeEngine(n)` handles the 2x2, 3x3, 4x4, and 5x5. The 4x4 and 5x5 move group (face turns plus wide turns) was decided by the project owner on 2026-11-03.

## Inputs

1. `n`: 2, 3, 4, or 5. Any other size raises `ValueError`.
2. A state is a string of 6·n² colour letters, one per sticker, with faces in the order U, R, F, D, L, B and stickers in each face read row by row from the top left. A solved 2x2 is `UUUURRRRFFFFDDDDLLLLBBBB`. Stickers sit in 3D, at positions from -(n-1) to n-1 in steps of 2 along each axis, and every move table derives from that one placement.

## Outputs

The nine interface methods:

1. `legal_moves()` returns the move group in standard notation, Singmaster for the face turns and WCA notation for the wide turns:
   1. 2x2 and 3x3: the 18 face turns `U U' U2 R R' R2 F F' F2 D D' D2 L L' L2 B B' B2`.
   2. 4x4 and 5x5: those 18 face turns, then the 18 wide turns `Uw Uw' Uw2 Rw Rw' Rw2 Fw Fw' Fw2 Dw Dw' Dw2 Lw Lw' Lw2 Bw Bw' Bw2`.
   3. `Xw` turns the two outer layers on side X together, in the same direction as `X`. Layers sit at depth `n-1` (outer) and `n-3` (second), so a wide turn takes every sticker whose position has dot product with the face's axis of at least `n-3`. There are no slice moves and no whole-cube rotations. On the 5x5 the middle layer never turns, so its six centre stickers stay fixed, as on the 3x3.
2. `solved_state()` returns the solved string above.
3. `load_state(input)` returns the input's state. It raises `ValidityMismatchError` if the reachability check below disagrees with the input's validity label.
4. `apply_move(state, move)` returns the new state. It raises `IllegalMoveError` for any string not in `legal_moves()`.
5. `is_solved(state)` returns true when all stickers on each face share one colour, whatever that colour is.
6. `scramble(input_seed, depth)` returns `(state, moves)`. It picks moves with `random.Random(input_seed)`, never picks two moves in a row with the same face letter, so `R` is never followed by `Rw`, and draws again if the result is solved.
7. `corrupt(state, input_seed)` returns `(state, description)`. It picks a corruption type uniformly with `random.Random(input_seed)`, and the piece and direction follow from the same generator. The types per cube are:
   1. 2x2: `twisted corner` and `recoloured sticker`. A swap of two 2x2 corners stays reachable, so there is none.
   2. 3x3: `twisted corner`, `flipped edge`, `swapped corners`, `swapped edges`, and `recoloured sticker`. A swap exchanges the sticker triples (or pairs) of two positions, so each piece keeps its orientation and the permutation parity breaks.
   3. 4x4: `twisted corner`, `flipped wing`, and `recoloured sticker`.
   4. 5x5: `twisted corner`, `flipped wing`, `flipped edge` (a middle edge), and `recoloured sticker`.
   5. The 4x4 and 5x5 have no swaps, because a single swap of two pieces can be reachable there.
   6. A recolour changes one sticker that is not a centre sticker to another colour, so a colour count differs from n*n. On the big cubes no centre sticker is ever recoloured, whichever orbit it belongs to.
   7. The description starts with the two-word type. It then names the pieces and the change: `"twisted corner UFR clockwise"`, `"flipped edge UF"`, `"flipped wing UF near R"`, `"swapped edges UF UR"`, and `"recoloured sticker F3 R to U"`. A wing is an edge piece off the middle of its edge, so each edge has two. The wing is named by its edge, then the face whose end of the edge it is nearer: `UF near R` and `UF near L` are the two wings of the UF edge. The edge name lists faces in the order U or D, then F or B, then R or L.
8. `render(state)` returns a text net of the six faces, one face block per label, with the colour letters spaced out.
9. `is_move_token(token)` returns true when `MOVE_TOKEN` matches the whole token: a face letter with an optional layer count and an optional `w`, or a lower-case face letter, a slice letter (`M`, `E`, or `S`), or a rotation letter (`x`, `y`, or `z`), then an optional `'`, `2`, or both. The layer count goes with face letters only. It is true for every legal move and for shapes the puzzle doesn't allow, such as `r` or `3Fw'`.
10. `mismatch_reasons()` returns, on every size, `twisted corner`, `flipped edge`, `flipped wing`, `swapped corners`, `swapped edges`, `recoloured sticker`, and `twisted centre`: the corruption types of all four cubes in `CORRUPTION_TYPES` order, then the decoy. The list is the same on every size, so a 2x2 is offered edges and wings it doesn't have.
11. `decoy_reasons()` returns `twisted centre`. A centre piece shows one sticker on every size, so no state shows its twist.

## Reachability

The check for `load_state()` works on colours only, so pieces of one colour are interchangeable. A state is reachable when all of these hold:

1. It has 6·n² letters, all from `URFDLB`.
2. Corners (every size): all eight are present and the twist sum is 0 mod 3.
3. 3x3 and 5x5: every fixed centre shows its own face, the twelve middle edges are all present with an even flip sum, and corner permutation parity equals middle edge permutation parity.
4. 4x4 and 5x5, centres: the centre stickers are grouped into orbits, the sets the moves exchange with each other. The 4x4 has one orbit of 24. The 5x5 has the X-centre orbit and the T-centre orbit, 24 each, and six fixed centres. Each orbit shows every colour as often as the solved cube does, which is 4 times for an orbit of 24.
5. 4x4 and 5x5, wings: there are 24 wings. Each slot lists its two stickers in the order the first wing's pair reaches that slot, found by a breadth-first search over the move tables. Read in that order, the 24 colour pairs must be exactly the 24 pairs of the solved cube, each once. A wing can never be flipped, and the two wings of one edge are told apart by that order, so a flipped wing leaves a pair duplicated and another missing.
6. 4x4: wing parity and corner parity are free. Identical centre pieces absorb any parity, so the check adds no parity rule for them.

As a one-off development check, the number of states the rules accept was compared with the known group orders of the 4x4 and 5x5, and the counts matched. The check isn't part of the repo. The repo's tests are the random-walk and corruption checks.

The 3x3 code may reuse Cube Bench's `sim/`. Anything copied goes into `NOTICE`, as [AGENTS.md](../../AGENTS.md#reuse) says.

## How to test

1. Each move applied four times, and each half turn applied twice, returns the start state, for all 36 moves on the 4x4 and 5x5.
   1. `legal_moves()` of the 4x4 and 5x5 is the exact list above.
   2. `Rw` on a solved 4x4 gives the hand-checked stickers, and on the 5x5 it takes the second layer and leaves the middle one.
2. `R U R' U'` applied six times to a solved 3x3 returns solved.
3. A solved state turned as a whole cube, by applying the same rotation to all faces, still passes `is_solved()`. On the 4x4, `Rw Lw'` is such a rotation.
4. `apply_move(state, "r")`, `apply_move(state, "R ")`, and `apply_move(state, "R′")` each raise `IllegalMoveError`.
5. `scramble()` with the same seed gives the same result twice. Over 1,000 seeds, no scramble has two consecutive moves with the same face letter and none ends solved.
6. Every `corrupt()` output fails the reachability check, and every scramble output passes it, on every size. Over many seeds every corruption type of each cube appears, and each result fails `load_state()` as valid. Breadth-first states to depth 2 and random walks on the 4x4 and 5x5 always pass. A flipped wing, a duplicated wing, a changed centre sticker, and (5x5 only) swapped middle edges fail. Two swapped corners pass on the 4x4 and fail on the 5x5.
7. `load_state()` raises on a valid state labelled invalid, and on an invalid state labelled valid.
8. `is_move_token()` is true for `R`, `U'`, `r`, `Rw2`, `3Fw'`, `M`, `x`, and `R2'`, and false for the empty string, `MISMATCH`, `2x2`, `R''`, `R3`, a token with a space, and `R’` with a typographic apostrophe. It is true for every move in `legal_moves()` of all four cubes.
9. The 2x2 and 3x3 give the same `legal_moves()`, scrambles, move results, and render as before the 4x4 and 5x5 were added. Pinned literal values in the tests check this. Their corruptions changed on purpose with the new corruption types, so the tests check those for being unreachable and typed instead.
