# Spec: docs/specs/validator.md
"""Tests for the validator. They use the 2x2 engine and call no AI model."""

import json

import pytest

from src.puzzles.registry import get_engine
from src.validator import Verdict, validate

ENGINE = get_engine("2x2")
STATE, SCRAMBLE = ENGINE.scramble(7, 3)
INVERSE = {"": "'", "'": "", "2": "2"}
SOLVE = [m[0] + INVERSE[m[1:]] for m in reversed(SCRAMBLE)]
NO_SOLVE = ["R"] if SCRAMBLE[-1] != "R'" else ["U"]  # one turn never solves a depth-3 scramble
BAD_STATE, _ = ENGINE.corrupt(STATE, 5)

VALID = {"puzzle": "2x2", "state": STATE, "validity": "valid"}
INVALID = {"puzzle": "2x2", "state": BAD_STATE, "validity": "invalid"}


def reply(moves, mismatch=False):
    return json.dumps({"moves": moves, "mismatch": mismatch})


def fenced(text):
    return "```json\n" + text + "\n```"


# (input, response, stop_reason, moves, hallucination, mismatch, move_count, outcome)
CASES = {
    "valid solved": (VALID, reply(SOLVE), "ok", SOLVE, False, False, 3, "success"),
    "valid solved mismatch on": (VALID, reply(SOLVE, True), "ok", SOLVE, False, True, 3, "failure"),
    "valid empty": (VALID, reply([]), "ok", [], False, False, 0, "failure"),
    "valid unsolved": (VALID, reply(NO_SOLVE), "ok", NO_SOLVE, False, False, 1, "failure"),
    "valid extra X": (VALID, reply(SOLVE + ["X"]), "ok", SOLVE + ["X"], True, False, 4, "hallucination"),
    "trailing space": (VALID, reply(["R "]), "ok", ["R "], True, False, 1, "hallucination"),
    "prime sign": (VALID, reply(["R′"]), "ok", ["R′"], True, False, 1, "hallucination"),
    "lower case": (VALID, reply(["r"]), "ok", ["r"], True, False, 1, "hallucination"),
    "wide move": (VALID, reply(["Rw"]), "ok", ["Rw"], True, False, 1, "hallucination"),
    "invalid flagged": (INVALID, reply([], True), "ok", [], False, True, 0, "success"),
    "invalid X": (INVALID, reply(["X"], True), "ok", ["X"], True, True, 1, "hallucination"),
    "invalid not flagged": (INVALID, reply(["R"]), "ok", ["R"], False, False, 1, "failure"),
    "not json": (VALID, "not json", "ok", [], False, False, None, "malformed_output"),
    "fenced valid": (VALID, fenced(reply(SOLVE)), "ok", SOLVE, False, False, 3, "success"),
    "fenced invalid": (INVALID, fenced(reply([], True)), "ok", [], False, True, 0, "success"),
    "fenced not json": (VALID, fenced("not json"), "ok", [], False, False, None, "malformed_output"),
    "truncated": (VALID, reply(SOLVE), "truncated", [], False, False, None, "malformed_output"),
    "refused": (VALID, reply(SOLVE), "refused", [], False, False, None, "malformed_output"),
    "infrastructure": (VALID, "", "infrastructure_failure", [], False, False, None, "infrastructure_failure"),
    "extra key": (VALID, json.dumps({"moves": [], "mismatch": False, "why": "x"}), "ok", [], False, False, None, "malformed_output"),
    "missing key": (VALID, json.dumps({"moves": []}), "ok", [], False, False, None, "malformed_output"),
    "mismatch not bool": (VALID, json.dumps({"moves": [], "mismatch": "false"}), "ok", [], False, False, None, "malformed_output"),
    "moves not strings": (VALID, json.dumps({"moves": [1], "mismatch": False}), "ok", [], False, False, None, "malformed_output"),
    "json list": (VALID, "[]", "ok", [], False, False, None, "malformed_output"),
}


@pytest.mark.parametrize("name", list(CASES))
def test_validate(name):
    input, response, stop, moves, hallucination, mismatch, count, outcome = CASES[name]
    verdict = validate(input, response, stop)
    assert verdict == Verdict(moves, hallucination, mismatch, count, outcome)


def test_scramble_is_not_solved_in_one_move():
    assert not ENGINE.is_solved(ENGINE.apply_move(STATE, NO_SOLVE[0]))


def test_unknown_stop_reason_raises():
    with pytest.raises(ValueError, match="stop_reason"):
        validate(VALID, reply(SOLVE), "stop")
