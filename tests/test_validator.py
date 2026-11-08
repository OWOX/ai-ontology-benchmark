# Spec: docs/specs/validator.md
"""Tests for the validator. They use the 2x2 engine and call no AI model."""

import json

import pytest

from src.puzzles.registry import get_engine
from src.validator import OUTCOMES, Verdict, offered_reasons, read_decision_call, validate

ENGINE = get_engine("2x2")
STATE, SCRAMBLE = ENGINE.scramble(7, 3)
INVERSE = {"": "'", "'": "", "2": "2"}
SOLVE = [m[0] + INVERSE[m[1:]] for m in reversed(SCRAMBLE)]
NO_SOLVE = ["R"] if SCRAMBLE[-1] != "R'" else ["U"]  # one turn never solves a depth-3 scramble
BAD_STATE, _ = ENGINE.corrupt(STATE, 5)

VALID = {"puzzle": "2x2", "state": STATE, "validity": "valid"}
INVALID = {"puzzle": "2x2", "state": BAD_STATE, "validity": "invalid"}


def reply(moves):
    return "\n".join(moves)


def fenced(text, tag="text"):
    return "```" + tag + "\n" + text + "\n```"


MISMATCH = "MISMATCH"

# (input, response, stop_reason, moves, hallucination, mismatch, move_count, outcome)
CASES = {
    "valid solved": (VALID, reply(SOLVE), "ok", SOLVE, False, False, 3, "success"),
    "valid trailing newline": (VALID, reply(SOLVE) + "\n", "ok", SOLVE, False, False, 3, "success"),
    "valid crlf": (VALID, "\r\n".join(SOLVE), "ok", SOLVE, False, False, 3, "success"),
    "valid blank lines": (VALID, "\n\n".join(SOLVE) + "\n  \n", "ok", SOLVE, False, False, 3, "success"),
    "valid mismatch": (VALID, MISMATCH, "ok", [], False, True, 0, "failure"),
    "valid mismatch trailing newline": (VALID, MISMATCH + "\r\n\n", "ok", [], False, True, 0, "failure"),
    "valid unsolved": (VALID, reply(NO_SOLVE), "ok", NO_SOLVE, False, False, 1, "failure"),
    "valid extra X": (VALID, reply(SOLVE + ["X"]), "ok", SOLVE, False, False, 3, "format_error"),
    "mismatch among moves": (VALID, reply(SOLVE + [MISMATCH]), "ok", SOLVE, False, False, 3, "format_error"),
    "trailing space": (VALID, reply(["R "]), "ok", ["R"], False, False, 1, "format_error"),
    "leading space": (VALID, reply([" R"]), "ok", ["R"], False, False, 1, "format_error"),
    "trailing dot": (VALID, reply(["R."]), "ok", ["R"], False, False, 1, "format_error"),
    "prime sign": (VALID, reply(["R′"]), "ok", [], False, False, None, "abstention"),
    "lower case": (VALID, reply(["r"]), "ok", ["r"], True, False, 1, "hallucination"),
    "wide move": (VALID, reply(["Rw"]), "ok", ["Rw"], True, False, 1, "hallucination"),
    "one line of moves": (VALID, " ".join(SOLVE), "ok", SOLVE, False, False, 3, "format_error"),
    "prose": (VALID, "I think the answer is R", "ok", [], False, False, None, "abstention"),
    "invalid flagged": (INVALID, MISMATCH, "ok", [], False, True, 0, "success"),
    "invalid X": (INVALID, "X", "ok", [], False, False, None, "abstention"),
    "invalid not flagged": (INVALID, reply(["R"]), "ok", ["R"], False, False, 1, "failure"),
    "empty": (VALID, "", "ok", [], False, False, None, "malformed_output"),
    "blank lines only": (VALID, "\n \r\n\t\n", "ok", [], False, False, None, "malformed_output"),
    "empty fence": (VALID, "```\n\n```", "ok", [], False, False, None, "malformed_output"),
    "fenced valid": (VALID, fenced(reply(SOLVE)), "ok", SOLVE, False, False, 3, "success"),
    "fenced json tag": (VALID, fenced(reply(SOLVE), "json"), "ok", SOLVE, False, False, 3, "success"),
    "fenced invalid": (INVALID, fenced(MISMATCH), "ok", [], False, True, 0, "success"),
    "truncated": (VALID, reply(SOLVE), "truncated", [], False, False, None, "truncated"),
    "refused": (VALID, reply(SOLVE), "refused", [], False, False, None, "malformed_output"),
    "infrastructure": (VALID, "", "infrastructure_failure", [], False, False, None, "infrastructure_failure"),
}


@pytest.mark.parametrize("name", list(CASES))
def test_validate(name):
    input, response, stop, moves, hallucination, mismatch, count, outcome = CASES[name]
    verdict = validate(input, response, stop)
    assert verdict == Verdict(moves, hallucination, mismatch, count, outcome, impossible_move=bool(hallucination))
    assert verdict.mismatch_reason is None and not verdict.decoy


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


def test_empty_llm_response_on_an_unknown_puzzle_is_malformed_output():
    assert validate(UNKNOWN, " \n", "ok").outcome == "malformed_output"


def test_well_formed_llm_response_on_an_unknown_puzzle_raises():
    with pytest.raises(KeyError):
        validate(UNKNOWN, "U", "ok")


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


def test_outcome_order():
    assert OUTCOMES == ("infrastructure_failure", "truncated", "malformed_output", "abstention",
                        "hallucination", "format_error", "success", "failure")


def test_truncated_is_its_own_outcome():
    v = validate(VALID, "R\nU", "truncated")
    assert (v.outcome, v.hallucination, v.mismatch, v.move_count) == ("truncated", False, False, None)


def test_refusal_text_is_abstention():
    v = validate(VALID, "I can\u2019t reliably derive a solving sequence for this state.", "ok")
    assert (v.outcome, v.hallucination, v.parsed_moves, v.move_count) == ("abstention", False, [], None)


def test_prose_with_move_shaped_word_is_abstention():
    assert validate(VALID, "R2 would not help here.\nUse an x rotation first.", "ok").outcome == "abstention"


def test_api_refusal_is_malformed():
    assert validate(VALID, "", "refused").outcome == "malformed_output"


def test_moves_on_one_line_are_format_error():
    v = validate(VALID, "R U' F2", "ok")
    assert (v.outcome, v.parsed_moves, v.move_count, v.hallucination) == ("format_error", ["R", "U'", "F2"], 3, False)


def test_prose_header_before_legal_moves_is_format_error():
    assert validate(VALID, "An optimal sequence is:\n\nR'\nF", "ok").outcome == "format_error"


def test_padded_move_is_format_error():
    assert validate(VALID, " R\nU", "ok").outcome == "format_error"


def test_mismatch_with_explanation_is_format_error():
    v = validate(INVALID, "MISMATCH\nThe UFL corner is twisted.", "ok")
    assert (v.outcome, v.mismatch, v.parsed_moves, v.move_count, v.hallucination) == ("format_error", False, [], 0, False)


def test_impossible_move_token_is_hallucination():
    v = validate(VALID, "R\nM\nU", "ok")  # M is a slice move, not in the 2x2 move group
    assert (v.outcome, v.hallucination, v.parsed_moves) == ("hallucination", True, ["R", "M", "U"])


def test_impossible_token_beside_prose_is_hallucination():
    assert validate(VALID, "Solution:\nRw U", "ok").outcome == "hallucination"


def test_single_mismatch_line_still_flags():
    v = validate(INVALID, "MISMATCH", "ok")
    assert (v.outcome, v.mismatch) == ("success", True)


def test_decision_hallucination_is_none():
    raw = '[{"answers": {"next_move": {"choice": "mismatch"}}}]'
    assert validate(INVALID, raw, "ok", decision=True).hallucination is None
    assert validate(INVALID, "", "infrastructure_failure", decision=True).hallucination is None
    assert validate(INVALID, "not json", "ok", decision=True).hallucination is None
    assert validate(ONE_VALID, calls(ONE_SOLVE, "done"), "ok", decision=True).hallucination is None
    assert validate(ONE_VALID, calls("done"), "ok", decision=True).hallucination is None


DECORATED = {
    "numbered list": ("1. R\n2. U", ["R", "U"], "format_error"),
    "numbered with paren": ("1) R\n2) U'", ["R", "U'"], "format_error"),
    "bullets": ("- R\n* U\n\u2022 F2", ["R", "U", "F2"], "format_error"),
    "backticked move": ("`R`", ["R"], "format_error"),
    "commas": ("R, U, F", ["R", "U", "F"], "format_error"),
    "quoted move": ('"R"', ["R"], "format_error"),
    "bold move": ("**R**", ["R"], "format_error"),
    "markers mid-line": ("1. R 2. U", ["R", "U"], "format_error"),
    "hidden illegal mid-line": ("1. R 2. M", ["R", "M"], "hallucination"),
    "dashes": ("- R - U", ["R", "U"], "format_error"),
    "bracketed numbers": ("1) R, 2) U'", ["R", "U'"], "format_error"),
    "lettered marker": ("b) R U", ["R", "U"], "format_error"),
    "glued number after a bullet": ("- 1.R", ["R"], "format_error"),
    "glued paren number after a bullet": ("* 2)U", ["U"], "format_error"),
    "spaced number after a bullet": ("- 1. R", ["R"], "format_error"),
    "lettered marker after a bullet": ("- b) R", ["R"], "format_error"),
    "move with full stop then move": ("R. U", ["R", "U"], "format_error"),
    "lettered marker after a number": ("1. b) R", ["R"], "format_error"),
    "capital move after a bullet": ("- B. R", ["B", "R"], "format_error"),
    "lettered lines": ("a. R\nb. U", ["R", "U"], "format_error"),
    "move with full stop": ("R.", ["R"], "format_error"),
    "impossible move glued after a bullet": ("- 1.M", ["M"], "hallucination"),
    "illegal in a numbered list": ("1. M", ["M"], "hallucination"),
    "illegal among commas": ("R, M", ["R", "M"], "hallucination"),
    "mismatch with a full stop": ("MISMATCH.", [], "format_error"),
    "bold mismatch": ("**MISMATCH**", [], "format_error"),
    "mismatch with trailing space": ("MISMATCH ", [], "format_error"),
    "backticked mismatch": ("`MISMATCH`", [], "format_error"),
    "mismatch glued after a bullet": ("- 1.MISMATCH", [], "format_error"),
}


@pytest.mark.parametrize("name", list(DECORATED))
def test_decorated_layouts(name):
    response, moves, outcome = DECORATED[name]
    for input in (VALID, INVALID):
        v = validate(input, response, "ok")
        assert (v.outcome, v.parsed_moves, v.mismatch) == (outcome, moves, False)
        assert v.hallucination is (outcome == "hallucination")
        assert v.move_count == len(moves)


def test_prose_stays_abstention_and_a_lone_mismatch_stays_a_verdict():
    assert validate(VALID, "I can't solve this.", "ok").outcome == "abstention"
    assert validate(VALID, "R2 would not help here.", "ok").outcome == "abstention"
    assert validate(VALID, "1. I cannot do this", "ok").outcome == "abstention"
    v = validate(INVALID, "MISMATCH", "ok")
    assert (v.outcome, v.mismatch) == ("success", True)


def test_decorated_mismatch_beside_moves_is_format_error():
    v = validate(VALID, "1. R\n**MISMATCH**", "ok")
    assert (v.outcome, v.parsed_moves, v.mismatch) == ("format_error", ["R"], False)


def test_lettered_marker_alone_is_abstention_and_a_lone_quote_is_not_stripped():
    assert validate(VALID, "x.", "ok").outcome == "abstention"
    assert validate(VALID, "1. M", "ok").outcome == "hallucination"
    assert validate(VALID, '"R', "ok").outcome == "abstention"
    assert validate(VALID, '"R"', "ok").outcome == "format_error"


def test_list_markers_count_only_at_the_start_of_a_line():
    for response in ("R U r.", "R U x."):
        v = validate(VALID, response, "ok")
        assert v.outcome == "hallucination", response
    assert validate(VALID, "R U r.", "ok").parsed_moves == ["R", "U", "r"]


# Mismatch reasons. The offered list is the engine's, then `other`.
REASONS = offered_reasons(ENGINE)


def test_offered_reasons_end_with_other_on_every_cube():
    for puzzle in ("2x2", "3x3", "4x4", "5x5"):
        offered = offered_reasons(get_engine(puzzle))
        assert offered[-1] == "other" and offered[:-1] == get_engine(puzzle).mismatch_reasons()
        assert "twisted centre" in offered


# (name, input, response, reason, outcome, mismatch, hallucination, decoy, impossible)
WITH_REASONS = {
    "valid mismatch bare": (VALID, "MISMATCH", None, "format_error", False, False, False, False),
    "valid offered reason": (VALID, "MISMATCH twisted corner", "twisted corner", "failure", True, False, False, False),
    "valid decoy": (VALID, "MISMATCH twisted centre", "twisted centre", "hallucination", True, True, True, False),
    "invalid other": (INVALID, "MISMATCH other", "other", "success", True, False, False, False),
    "invalid wrong reason": (INVALID, "MISMATCH swapped edges", "swapped edges", "success", True, False, False, False),
    "invalid decoy": (INVALID, "MISMATCH twisted centre", "twisted centre", "hallucination", True, True, True, False),
    "invalid fenced": (INVALID, fenced("MISMATCH twisted corner"), "twisted corner", "success", True, False, False, False),
    "double space": (VALID, "MISMATCH  twisted corner", "twisted corner", "format_error", False, False, False, False),
    "bold reason": (VALID, "**MISMATCH twisted corner**", "twisted corner", "format_error", False, False, False, False),
    "trailing full stop": (VALID, "MISMATCH twisted corner.", "twisted corner", "format_error", False, False, False, False),
    "free text reason": (VALID, "MISMATCH colours look wrong", None, "format_error", False, False, False, False),
    "bold decoy": (VALID, "**MISMATCH twisted centre**", "twisted centre", "hallucination", False, True, True, False),
    "explanation beside": (INVALID, "MISMATCH twisted corner\nbecause", "twisted corner", "format_error", False, False, False, False),
    "moves then decoy": (VALID, reply(SOLVE) + "\nMISMATCH twisted centre", "twisted centre", "hallucination", False, True, True, False),
    "moves then reason": (VALID, reply(SOLVE) + "\nMISMATCH twisted corner", "twisted corner", "format_error", False, False, False, False),
    "illegal move and decoy": (VALID, "M\nMISMATCH twisted centre", "twisted centre", "hallucination", False, True, True, True),
    "first offered reason wins": (VALID, "MISMATCH colours\n**MISMATCH other**\nMISMATCH twisted corner", "other", "format_error", False, False, False, False),
}


@pytest.mark.parametrize("name", list(WITH_REASONS))
def test_validate_with_reasons(name):
    input, response, reason, outcome, mismatch, halluc, decoy, impossible = WITH_REASONS[name]
    v = validate(input, response, "ok", reasons=REASONS)
    assert (v.outcome, v.mismatch, v.mismatch_reason, v.hallucination, v.decoy, v.impossible_move) == (
        outcome, mismatch, reason, halluc, decoy, impossible)


def test_lone_mismatch_line_has_no_moves_and_a_zero_count():
    v = validate(INVALID, "MISMATCH twisted corner", "ok", reasons=REASONS)
    assert (v.parsed_moves, v.move_count) == ([], 0)


def test_rows_without_a_stated_setting_agree_with_and_without_reasons():
    for input, response in ((VALID, reply(SOLVE)), (VALID, "R "), (VALID, "r"), (VALID, "I can't solve this."),
                            (INVALID, "X"), (VALID, ""), (VALID, "1. R"), (INVALID, reply(NO_SOLVE))):
        a = validate(input, response, "ok")
        b = validate(input, response, "ok", reasons=REASONS)
        assert (a.outcome, a.parsed_moves, a.mismatch, a.hallucination, a.move_count) == (
            b.outcome, b.parsed_moves, b.mismatch, b.hallucination, b.move_count)
        assert b.mismatch_reason is None and not b.decoy


def test_stop_reasons_with_reasons_keep_their_outcomes():
    assert validate(VALID, reply(SOLVE), "truncated", reasons=REASONS).outcome == "truncated"
    assert validate(VALID, "", "refused", reasons=REASONS).outcome == "malformed_output"
    assert validate(VALID, "", "infrastructure_failure", reasons=REASONS).outcome == "infrastructure_failure"
    assert validate(VALID, "", "ok", reasons=REASONS).outcome == "malformed_output"
    with pytest.raises(ValueError):
        validate(VALID, "R", "other", reasons=REASONS)


# Decision path with reasons.
def test_decision_mismatch_choice_with_reasons():
    n = REASONS.index("twisted corner") + 1
    v = validate(INVALID, calls(f"mismatch_{n}"), "ok", decision=True, reasons=REASONS)
    assert (v.outcome, v.mismatch, v.mismatch_reason, v.hallucination, v.move_count) == (
        "success", True, "twisted corner", False, 0)
    v = validate(ONE_VALID, calls(f"mismatch_{n}"), "ok", decision=True, reasons=REASONS)
    assert (v.outcome, v.mismatch, v.mismatch_reason, v.hallucination) == ("failure", True, "twisted corner", False)


def test_decision_decoy_choice_is_a_hallucination():
    n = REASONS.index("twisted centre") + 1
    v = validate(INVALID, calls(f"mismatch_{n}"), "ok", decision=True, reasons=REASONS)
    assert (v.outcome, v.mismatch, v.hallucination, v.decoy, v.impossible_move) == (
        "hallucination", True, True, True, False)


def test_decision_solves_and_done_with_reasons():
    v = validate(ONE_VALID, calls(ONE_SOLVE, "done"), "ok", decision=True, reasons=REASONS)
    assert (v.outcome, v.hallucination, v.mismatch, v.mismatch_reason, v.move_count) == ("success", False, False, None, 1)
    v = validate(ONE_VALID, calls("done"), "ok", decision=True, reasons=REASONS)
    assert (v.outcome, v.hallucination) == ("failure", False)


def test_decision_ids_must_match_the_release():
    assert validate(INVALID, calls("mismatch"), "ok", decision=True, reasons=REASONS).outcome == "malformed_output"
    assert validate(INVALID, calls("mismatch_1"), "ok", decision=True).outcome == "malformed_output"
    for bad in ("mismatch_0", f"mismatch_{len(REASONS) + 1}", "mismatch_01", "mismatch_"):
        assert validate(INVALID, calls(bad), "ok", decision=True, reasons=REASONS).outcome == "malformed_output", bad


def test_decision_ignores_calls_after_a_mismatch_choice_with_reasons():
    v = validate(ONE_VALID, calls("mismatch_1", ONE_SOLVE, "done"), "ok", decision=True, reasons=REASONS)
    assert (v.outcome, v.parsed_moves, v.mismatch_reason) == ("failure", [], REASONS[0])


def test_decision_none_hallucination_without_reasons_and_false_with_them():
    assert validate(INVALID, "", "infrastructure_failure", decision=True).hallucination is None
    assert validate(INVALID, "", "infrastructure_failure", decision=True, reasons=REASONS).hallucination is False
    assert validate(INVALID, "not json", "ok", decision=True, reasons=REASONS).hallucination is False


def test_read_decision_call_returns_the_text_model_line():
    legal = ENGINE.legal_moves()

    def call(choice):
        return {"answers": {"next_move": {"choice": choice}}}

    assert read_decision_call(call("move_1"), legal) == legal[0]
    assert read_decision_call(call("done"), legal, REASONS) == "done"
    assert read_decision_call(call("mismatch"), legal) == "MISMATCH"
    assert read_decision_call(call("mismatch"), legal, REASONS) is None
    assert read_decision_call(call("mismatch_1"), legal) is None
    assert read_decision_call(call("mismatch_1"), legal, REASONS) == "MISMATCH " + REASONS[0]
    assert read_decision_call(call(f"mismatch_{len(REASONS)}"), legal, REASONS) == "MISMATCH other"
    assert read_decision_call(call("mismatch_01"), legal, REASONS) is None
    assert read_decision_call(call(5), legal, REASONS) is None
    assert read_decision_call({}, legal, REASONS) is None
