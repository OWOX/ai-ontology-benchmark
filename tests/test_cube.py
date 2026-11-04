# Spec: docs/specs/cube.md
"""Tests for the cube engine. They read nothing and write nothing."""

import pytest

from src.puzzles.cube import CubeEngine
from src.puzzles.engine import IllegalMoveError, ValidityMismatchError
from src.puzzles.registry import get_engine

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
    with pytest.raises(ValidityMismatchError):
        E2.load_state({"state": "U" * 24, "validity": "valid"})


def test_render():
    text = E2.render(E2.solved_state())
    assert text.split("\n\n")[0] == "U\nU U\nU U"
    assert len(text.split("\n\n")) == 6
    assert E3.render(E3.solved_state()).split("\n\n")[1] == "R\nR R R\nR R R\nR R R"


@pytest.mark.parametrize("puzzle", ["2x2", "3x3"])
@pytest.mark.parametrize("token", ["R", "U'", "F2", "r", "Rw", "Rw2", "3Fw'", "M", "E2", "S'", "x", "y2", "z'", "R2'", "u"])
def test_move_shaped_tokens(puzzle, token):
    assert get_engine(puzzle).is_move_token(token)


@pytest.mark.parametrize("puzzle", ["2x2", "3x3"])
@pytest.mark.parametrize("token", ["", "I", "can't", "MISMATCH", "2x2", "R,", "(R", "R3", "Q", "RU", "R''", " R", "R ", "R\u2019", "a", "The"])
def test_prose_tokens(puzzle, token):
    assert not get_engine(puzzle).is_move_token(token)


@pytest.mark.parametrize("puzzle", ["2x2", "3x3"])
def test_every_legal_move_is_a_move_token(puzzle):
    engine = get_engine(puzzle)
    assert all(engine.is_move_token(m) for m in engine.legal_moves())


def test_engine_has_no_reference_length():
    assert not hasattr(get_engine("2x2"), "reference_length")
