# Spec: docs/specs/cube.md
"""Tests for the cube engine. They read nothing and write nothing."""

import hashlib
import random
from collections import deque

import pytest

from src.puzzles.cube import CubeEngine, _positions, _wings
from src.puzzles.engine import IllegalMoveError, ValidityMismatchError

E2, E3, E4, E5 = CubeEngine(2), CubeEngine(3), CubeEngine(4), CubeEngine(5)
BIG = [E4, E5]
WIDE = "U U' U2 R R' R2 F F' F2 D D' D2 L L' L2 B B' B2 " \
       "Uw Uw' Uw2 Rw Rw' Rw2 Fw Fw' Fw2 Dw Dw' Dw2 Lw Lw' Lw2 Bw Bw' Bw2"


def apply_all(engine, state, moves):
    for move in moves:
        state = engine.apply_move(state, move)
    return state


def test_basic_shape():
    assert E2.solved_state() == "UUUURRRRFFFFDDDDLLLLBBBB"
    assert E3.legal_moves() == "U U' U2 R R' R2 F F' F2 D D' D2 L L' L2 B B' B2".split()
    assert E4.legal_moves() == E5.legal_moves() == WIDE.split()
    assert E4.solved_state() == "".join(f * 16 for f in "URFDLB")
    for size in (0, 1, 6):
        with pytest.raises(ValueError):
            CubeEngine(size)


def test_known_move_results():
    # A clockwise U sends the right face's top row to the front and the back's to the right.
    u = E3.apply_move(E3.solved_state(), "U")
    assert u == "UUUUUUUUU" + "BBBRRRRRR" + "RRRFFFFFF" + "DDDDDDDDD" + "FFFLLLLLL" + "LLLBBBBBB"
    r = E3.apply_move(E3.solved_state(), "R")
    assert r[0:9] == "UUFUUFUUF" and r[18:27] == "FFDFFDFFD"


@pytest.mark.parametrize("engine", [E2, E3, E4, E5])
def test_turns_return_to_start(engine):
    start, _ = engine.scramble(7, 12)
    for turn in {m.rstrip("'2") for m in engine.legal_moves()}:
        assert apply_all(engine, start, [turn] * 4) == start
        assert apply_all(engine, start, [turn + "2"] * 2) == start
        assert apply_all(engine, start, [turn, turn + "'"]) == start
        assert apply_all(engine, start, [turn + "'"] * 2) == apply_all(engine, start, [turn + "2"])


@pytest.mark.parametrize("engine", [E3, E4, E5])
def test_sexy_move_has_order_six(engine):
    state = apply_all(engine, engine.solved_state(), ["R", "U", "R'", "U'"] * 6)
    assert state == engine.solved_state()
    assert apply_all(engine, engine.solved_state(), ["R", "U", "R'", "U'"]) != engine.solved_state()


def test_whole_cube_turn_stays_solved():
    assert E2.is_solved(apply_all(E2, E2.solved_state(), ["R", "L'"]))
    recoloured = "".join(c * 9 for c in "FUBLDR")
    assert E3.is_solved(recoloured) and not E3.is_solved(E3.apply_move(E3.solved_state(), "R"))


def test_wide_turn_stickers():
    # Rw on a solved 4x4 turns the two right-hand layers: the front's right two columns go up.
    assert E4.apply_move(E4.solved_state(), "Rw") == (
        "UUFF" * 4 + "R" * 16 + "FFDD" * 4 + "DDBB" * 4 + "L" * 16 + "UUBB" * 4)
    # The 5x5 wide turn takes the second layer but leaves the middle one.
    rw = E5.apply_move(E5.solved_state(), "Rw")
    assert rw[:25] == "UUUFF" * 5 and rw[25:50] == "R" * 25
    assert E5.apply_move(E5.solved_state(), "Rw") != E5.apply_move(E5.solved_state(), "R")


def test_whole_cube_turns_stay_solved_on_big_cubes():
    # On the 4x4, Rw and Lw' together turn every layer: a whole-cube rotation.
    rotated = apply_all(E4, E4.solved_state(), ["Rw", "Lw'"])
    assert rotated == "".join(c * 16 for c in "FRDBLU") and E4.is_solved(rotated)
    # On the 5x5 they leave the middle layer behind, so the cube is no longer solved.
    assert not E5.is_solved(apply_all(E5, E5.solved_state(), ["Rw", "Lw'"]))
    for engine in BIG:
        recoloured = "".join(c * engine.n ** 2 for c in "FUBLDR")
        assert engine.is_solved(recoloured)
        assert not engine.is_solved(engine.apply_move(engine.solved_state(), "Rw"))


@pytest.mark.parametrize("move", ["r", "R ", "R′", "", "M", "R3", None])
def test_illegal_moves(move):
    with pytest.raises(IllegalMoveError):
        E3.apply_move(E3.solved_state(), move)


@pytest.mark.parametrize("engine", [E2, E3, E4, E5])
def test_scramble_properties(engine):
    assert engine.scramble(5, 8) == engine.scramble(5, 8)
    for seed in range(1000):
        state, moves = engine.scramble(seed, 1 + seed % 10)
        assert len(moves) == 1 + seed % 10
        assert all(a[0] != b[0] for a, b in zip(moves, moves[1:]))
        assert not engine.is_solved(state)
        assert apply_all(engine, engine.solved_state(), moves) == state


@pytest.mark.parametrize("engine", [E2, E3, E4, E5])
def test_corrupt_fails_and_scramble_passes_reachability(engine):
    for seed in range(1000):
        state, _ = engine.scramble(seed, 1 + seed % 15)
        engine.load_state({"state": state, "validity": "valid"})
        bad, description = engine.corrupt(state, seed)
        with pytest.raises(ValidityMismatchError):
            engine.load_state({"state": bad, "validity": "valid"})
        assert engine.load_state({"state": bad, "validity": "invalid"}) == bad
        assert description.startswith(("twisted corner ", "flipped edge ", "flipped wing "))


def test_corrupt_descriptions_and_edge_choice():
    descriptions = {E3.corrupt(E3.solved_state(), s)[1] for s in range(200)}
    assert any(d.startswith("flipped edge") for d in descriptions)
    assert any(d == "twisted corner UFR clockwise" for d in descriptions)
    assert all(E2.corrupt(E2.solved_state(), s)[1].startswith("twisted corner") for s in range(50))


def test_load_state_label_mismatch():
    state, _ = E3.scramble(1, 10)
    with pytest.raises(ValidityMismatchError):
        E3.load_state({"state": state, "validity": "invalid"})
    with pytest.raises(ValidityMismatchError):
        E3.load_state({"state": state, "validity": "maybe"})


def test_malformed_strings_are_invalid():
    solved = E3.solved_state()
    # Swapping two edges alone breaks the parity match with the corners.
    swapped = list(solved)
    swapped[7], swapped[5], swapped[19], swapped[10] = swapped[5], swapped[7], swapped[10], swapped[19]
    cases = [solved[:-1], "X" + solved[1:], "U" * 54, "".join(swapped),
             solved[:4] + "R" + solved[5:]]
    for case in cases:
        with pytest.raises(ValidityMismatchError):
            E3.load_state({"state": case, "validity": "valid"})
        assert E3.load_state({"state": case, "validity": "invalid"}) == case
        with pytest.raises(ValueError):
            E3.reference_length(case)
    with pytest.raises(ValidityMismatchError):
        E2.load_state({"state": "U" * 24, "validity": "valid"})


def test_render():
    text = E2.render(E2.solved_state())
    assert text.split("\n\n")[0] == "U\nU U\nU U"
    assert len(text.split("\n\n")) == 6
    assert E3.render(E3.solved_state()).split("\n\n")[1] == "R\nR R R\nR R R\nR R R"


def test_reference_length_unsolved_cubes():
    with pytest.raises(NotImplementedError):
        E3.reference_length(E3.scramble(1, 5)[0])
    with pytest.raises(ValueError):
        E2.reference_length(E2.corrupt(E2.solved_state(), 3)[0])
    assert E2.reference_length(E2.solved_state()) == 0
    assert E2.reference_length(E2.apply_move(E2.solved_state(), "R2")) == 1


def breadth_first_distance(state):
    seen, queue = {state}, deque([(state, 0)])
    while queue:
        current, dist = queue.popleft()
        if E2.is_solved(current):
            return dist
        for move in E2.legal_moves():
            new = E2.apply_move(current, move)
            if new not in seen:
                seen.add(new)
                queue.append((new, dist + 1))


def test_ida_star_matches_breadth_first():
    rng = random.Random(0)
    for _ in range(20):
        depth = rng.randint(1, 4)
        state, _ = E2.scramble(rng.randrange(10**6), depth)
        assert 1 <= E2.reference_length(state) <= depth
        assert E2.reference_length(state) == breadth_first_distance(state)


def test_ida_star_on_deep_scrambles():
    for seed in range(10):
        state, _ = E2.scramble(seed, 14)
        assert 1 <= E2.reference_length(state) <= 11


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# Values computed from the engine before the 4x4 and 5x5 were added. Frozen releases
# depend on the 2x2 and 3x3 staying exactly like this.
SMALL_CUBE_PINS = {
    2: {
        "scrambles": {
            1: ("R' L B' L B U' F' U' D' B F' D' L' F B R U' D' U B2", "979224845e08"),
            2: ("U' R' U' F2 B' U2 L2 B D' B' R' F' L R L U L D' U2 D", "e72d46192e0f"),
            3: ("F' L F2 U2 F2 B2 D F' L' D U' L U B2 L' F' R' D2 R F", "ac79fea8d32e"),
        },
        "corrupts": {(1, 1): ("twisted corner UBR clockwise", "adff17501505"),
                     (1, 11): ("twisted corner DBL clockwise", "31cb9aa41b4f"),
                     (2, 12): ("twisted corner DFR anticlockwise", "db4a97663e4d")},
        "all_moves": "80cce0b2dc23", "render": "0900562d705c",
    },
    3: {
        "scrambles": {
            1: ("R' L B' L B U' F' U' D' B F' D' L' F B R U' D' U B2", "3420ed54bff4"),
            2: ("U' R' U' F2 B' U2 L2 B D' B' R' F' L R L U L D' U2 D", "7663cc4c1189"),
            3: ("F' L F2 U2 F2 B2 D F' L' D U' L U B2 L' F' R' D2 R F", "1f5eec3783b4"),
        },
        "corrupts": {(1, 1): ("twisted corner UBR clockwise", "628512d436d2"),
                     (1, 11): ("flipped edge DF", "859c77130ebe"),
                     (2, 12): ("flipped edge FR", "a3d68b6f4566")},
        "all_moves": "f12a7a39061d", "render": "05c25137b7d2",
    },
}


@pytest.mark.parametrize("n", [2, 3])
def test_small_cubes_unchanged(n):
    engine, pins = CubeEngine(n), SMALL_CUBE_PINS[n]
    assert engine.legal_moves() == "U U' U2 R R' R2 F F' F2 D D' D2 L L' L2 B B' B2".split()
    for seed, (moves, state_digest) in pins["scrambles"].items():
        state, got = engine.scramble(seed, 20)
        assert " ".join(got) == moves and digest(state) == state_digest
    for (scramble_seed, corrupt_seed), (description, state_digest) in pins["corrupts"].items():
        bad, got = engine.corrupt(engine.scramble(scramble_seed, 20)[0], corrupt_seed)
        assert (got, digest(bad)) == (description, state_digest)
    state, _ = engine.scramble(1, 20)
    assert digest("".join(engine.apply_move(state, m) for m in engine.legal_moves())) == pins["all_moves"]
    assert digest(engine.render(state)) == pins["render"]


def swap_stickers(state, a, b):
    chars = list(state)
    chars[a], chars[b] = chars[b], chars[a]
    return "".join(chars)


@pytest.mark.parametrize("engine", BIG)
def test_reachable_states_pass_the_check(engine):
    seen, frontier = {engine.solved_state()}, [engine.solved_state()]
    for _ in range(2):
        frontier = [new for state in frontier for move in engine.legal_moves()
                    if (new := engine.apply_move(state, move)) not in seen]
        seen.update(frontier)
    assert len(seen) > 1000
    rng = random.Random(3)
    for _ in range(200):
        state = engine.solved_state()
        for _ in range(60):
            state = engine.apply_move(state, rng.choice(engine.legal_moves()))
            seen.add(state)
    for state in seen:
        assert engine.load_state({"state": state, "validity": "valid"}) == state


def test_4x4_parities_are_free_and_5x5_parities_are_not():
    for engine in BIG:
        swapped = engine.solved_state()
        first, second = _positions(engine.n, 3)[:2]
        for a, b in zip(first, second):
            swapped = swap_stickers(swapped, a, b)
        assert engine.is_solved(swapped) is False
        label = "valid" if engine is E4 else "invalid"
        assert engine.load_state({"state": swapped, "validity": label}) == swapped
    # Two wings swapped is reachable on the 4x4, since a centre swap absorbs the parity.
    (a1, a2), (b1, b2) = _wings(4)[:2]
    swapped = swap_stickers(swap_stickers(E4.solved_state(), a1, b1), a2, b2)
    assert E4.load_state({"state": swapped, "validity": "valid"}) == swapped


def test_5x5_middle_edges_are_checked_apart_from_wings():
    first, second = _positions(5, 2)[:2]
    swapped = E5.solved_state()
    for a, b in zip(first, second):
        swapped = swap_stickers(swapped, a, b)
    assert E5.load_state({"state": swapped, "validity": "invalid"}) == swapped


@pytest.mark.parametrize("engine", BIG)
def test_impossible_wings_and_centres_are_invalid(engine):
    solved = engine.solved_state()
    x, y = _wings(engine.n)[0]
    flipped = swap_stickers(solved, x, y)
    duplicated = solved[:x] + solved[_wings(engine.n)[1][0]] + solved[x + 1:]
    centre = next(i for i in range(len(solved)) if i % engine.n ** 2 == engine.n + 1)
    recoloured = solved[:centre] + "R" + solved[centre + 1:]
    for bad in (flipped, duplicated, recoloured, solved[:-1], "X" + solved[1:]):
        with pytest.raises(ValidityMismatchError):
            engine.load_state({"state": bad, "validity": "valid"})
        with pytest.raises(ValueError):
            engine.reference_length(bad)


@pytest.mark.parametrize("engine", BIG)
def test_corrupt_descriptions_per_size(engine):
    descriptions = {engine.corrupt(engine.solved_state(), s)[1] for s in range(900)}
    assert "twisted corner UFR clockwise" in descriptions
    wings = {d for d in descriptions if d.startswith("flipped wing ")}
    assert len(wings) == 24 and "flipped wing UF near R" in wings and "flipped wing UF near L" in wings
    assert any(d.startswith("flipped edge ") for d in descriptions) == (engine is E5)


@pytest.mark.parametrize("engine", BIG)
def test_reference_length_is_not_available_yet(engine):
    with pytest.raises(NotImplementedError):
        engine.reference_length(engine.scramble(1, 5)[0])
    with pytest.raises(ValueError):
        engine.reference_length(engine.corrupt(engine.solved_state(), 3)[0])
