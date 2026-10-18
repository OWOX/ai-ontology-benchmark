# Spec: docs/specs/cube.md
"""Tests for the cube engine. They read nothing and write nothing."""

import random
from collections import deque

import pytest

from src.puzzles.cube import CubeEngine
from src.puzzles.engine import IllegalMoveError, ValidityMismatchError

E2, E3 = CubeEngine(2), CubeEngine(3)


def apply_all(engine, state, moves):
    for move in moves:
        state = engine.apply_move(state, move)
    return state


def test_basic_shape():
    assert E2.solved_state() == "UUUURRRRFFFFDDDDLLLLBBBB"
    assert E3.legal_moves() == "U U' U2 R R' R2 F F' F2 D D' D2 L L' L2 B B' B2".split()
    with pytest.raises(NotImplementedError, match="open item 5"):
        CubeEngine(5)


def test_known_move_results():
    # A clockwise U sends the right face's top row to the front and the back's to the right.
    u = E3.apply_move(E3.solved_state(), "U")
    assert u == "UUUUUUUUU" + "BBBRRRRRR" + "RRRFFFFFF" + "DDDDDDDDD" + "FFFLLLLLL" + "LLLBBBBBB"
    r = E3.apply_move(E3.solved_state(), "R")
    assert r[0:9] == "UUFUUFUUF" and r[18:27] == "FFDFFDFFD"


@pytest.mark.parametrize("engine", [E2, E3])
def test_turns_return_to_start(engine):
    start, _ = engine.scramble(7, 12)
    for face in "URFDLB":
        assert apply_all(engine, start, [face] * 4) == start
        assert apply_all(engine, start, [face + "2"] * 2) == start
        assert apply_all(engine, start, [face, face + "'"]) == start


def test_sexy_move_has_order_six():
    state = apply_all(E3, E3.solved_state(), ["R", "U", "R'", "U'"] * 6)
    assert state == E3.solved_state()
    assert apply_all(E3, E3.solved_state(), ["R", "U", "R'", "U'"]) != E3.solved_state()


def test_whole_cube_turn_stays_solved():
    assert E2.is_solved(apply_all(E2, E2.solved_state(), ["R", "L'"]))
    recoloured = "".join(c * 9 for c in "FUBLDR")
    assert E3.is_solved(recoloured) and not E3.is_solved(E3.apply_move(E3.solved_state(), "R"))


@pytest.mark.parametrize("move", ["r", "R ", "R′", "", "M", "R3", None])
def test_illegal_moves(move):
    with pytest.raises(IllegalMoveError):
        E3.apply_move(E3.solved_state(), move)


@pytest.mark.parametrize("engine", [E2, E3])
def test_scramble_properties(engine):
    assert engine.scramble(5, 8) == engine.scramble(5, 8)
    for seed in range(1000):
        state, moves = engine.scramble(seed, 1 + seed % 10)
        assert len(moves) == 1 + seed % 10
        assert all(a[0] != b[0] for a, b in zip(moves, moves[1:]))
        assert not engine.is_solved(state)
        assert apply_all(engine, engine.solved_state(), moves) == state


@pytest.mark.parametrize("engine", [E2, E3])
def test_corrupt_fails_and_scramble_passes_reachability(engine):
    for seed in range(1000):
        state, _ = engine.scramble(seed, 1 + seed % 15)
        engine.load_state({"state": state, "validity": "valid"})
        bad, description = engine.corrupt(state, seed)
        with pytest.raises(ValidityMismatchError):
            engine.load_state({"state": bad, "validity": "valid"})
        assert engine.load_state({"state": bad, "validity": "invalid"}) == bad
        assert description.startswith(("twisted corner ", "flipped edge "))


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
