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


# Decision path: the raw response is the array of a decision model's calls.
ONE_STATE, ONE_SCRAMBLE = ENGINE.scramble(7, 1)
ONE_SOLVE = ONE_SCRAMBLE[0][0] + INVERSE[ONE_SCRAMBLE[0][1:]]
ONE_VALID = {"puzzle": "2x2", "state": ONE_STATE, "validity": "valid"}


def calls(*choices):
    """choices: a move, 'done', 'mismatch', or a raw id. Returns the raw response."""
    legal = ENGINE.legal_moves()
    out = []
    for choice in choices:
        cid = choice if choice in ("done", "mismatch") else (f"move_{legal.index(choice) + 1}" if choice in legal else choice)
        out.append({"answers": {"next_move": {"type": "choice", "choice": cid}},
                    "usage": {"input_tokens": 10, "output_tokens": 0}, "model": "m"})
    return json.dumps(out)


UNKNOWN = {"puzzle": "no-such-puzzle", "state": "", "validity": "valid"}


def test_malformed_llm_response_on_an_unknown_puzzle_is_malformed_output():
    assert validate(UNKNOWN, "not json", "ok").outcome == "malformed_output"


def test_well_formed_llm_response_on_an_unknown_puzzle_raises():
    with pytest.raises(KeyError):
        validate(UNKNOWN, json.dumps({"moves": [], "mismatch": False}), "ok")


def test_decision_path_needs_the_engine():
    with pytest.raises(KeyError):
        validate(UNKNOWN, "[]", "ok", decision=True)


def test_decision_solves():
    v = validate(ONE_VALID, calls(ONE_SOLVE, "done"), "ok", decision=True)
    assert v.outcome == "success" and v.move_count == 1 and v.parsed_moves == [ONE_SOLVE] and not v.hallucination


def test_decision_done_first_is_failure():
    v = validate(ONE_VALID, calls("done"), "ok", decision=True)
    assert v.outcome == "failure" and v.parsed_moves == [] and not v.mismatch


def test_decision_mismatch_in_later_call():
    v = validate(INVALID, calls("R", "U", "mismatch"), "ok", decision=True)
    assert v.mismatch and v.outcome == "success" and v.parsed_moves == ["R", "U"] and not v.hallucination


def test_decision_mismatch_on_a_valid_input_is_failure():
    v = validate(ONE_VALID, calls("mismatch"), "ok", decision=True)
    assert v.mismatch and v.outcome == "failure" and v.parsed_moves == []


def test_decision_ignores_calls_after_done():
    v = validate(ONE_VALID, calls(ONE_SOLVE, "done", "mismatch"), "ok", decision=True)
    assert v.outcome == "success" and v.parsed_moves == [ONE_SOLVE] and not v.mismatch


def test_decision_ignores_calls_after_mismatch():
    v = validate(INVALID, calls("mismatch", "U", "bogus"), "ok", decision=True)
    assert v.outcome == "success" and v.parsed_moves == [] and v.mismatch


def test_decision_ignores_an_old_probability_field():
    raw = json.dumps([{"answers": {"next_move": {"choice": "done"}, "mismatch": {"noul": 0.9}}}])
    v = validate(ONE_VALID, raw, "ok", decision=True)
    assert v.outcome == "failure" and not v.mismatch


@pytest.mark.parametrize("raw", [
    "not json", "{}", "[]", json.dumps([{"answers": {}}]),
    json.dumps([{"answers": {"mismatch": {"noul": 0.9}}}]),
    json.dumps([{"answers": {"next_move": {"choice": "move_99"}}}]),
    json.dumps([{"answers": {"next_move": {"choice": "move_0"}}}]),
    json.dumps([{"answers": {"next_move": {"choice": "R"}}}]),
    json.dumps([{"answers": {"next_move": {"choice": "Mismatch"}}}]),
    json.dumps([{"answers": {"next_move": {"choice": 3}}}]),
    json.dumps([{"answers": {"next_move": {"choice": "move_\u00b2"}}}]),
    json.dumps([{"answers": {"next_move": {"choice": "move_03"}}}]),
    json.dumps([{"answers": {"next_move": {"choice": "move_\u0663"}}}]),
    json.dumps([{"answers": {"next_move": {"choice": "move_1"}}}, {"answers": {}}, {"answers": {"next_move": {"choice": "done"}}}]),
])
def test_decision_malformed(raw):
    assert validate(ONE_VALID, raw, "ok", decision=True).outcome == "malformed_output"


def test_decision_cap_reached_is_infrastructure():
    v = validate(ONE_VALID, calls("R"), "infrastructure_failure", decision=True)
    assert v.outcome == "infrastructure_failure"
