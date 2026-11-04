# Spec: docs/specs/validator.md
"""Turns one raw response into a Verdict. Reads the input, the raw response text, and the
stop reason. Writes nothing and makes no network calls.
"""

import json
import re
from dataclasses import dataclass

from src.puzzles.registry import get_engine

STOP_REASONS = ("ok", "truncated", "refused", "infrastructure_failure")
# One Markdown code fence around the whole response, with an optional language tag.
FENCE = re.compile(r"^\s*```[A-Za-z]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


# In check order.
OUTCOMES = ("infrastructure_failure", "truncated", "malformed_output", "abstention",
            "hallucination", "format_error", "success", "failure")


@dataclass(frozen=True)
class Verdict:
    # Moves read from the AI model's output, in order. Empty when there is no usable output, for
    # abstention, and for a lone MISMATCH line.
    # For a decision model they are its calls' next_move choices, in order.
    parsed_moves: list[str]
    # True when at least one parsed move is an impossible move, i.e. a move token that is not in
    # legal_moves(). None for every outcome of a decision model, which can't return one.
    hallucination: bool | None
    # Whether the AI model picked up the wrong state: its own claim that the input can't be
    # reached from the solved state. Read from its output, not computed. False when there is
    # no usable output, for abstention, and for format_error. For a decision model it is true when the call that ended the attempt
    # chose mismatch.
    mismatch: bool
    # Number of parsed moves in the half-turn metric. None for infrastructure_failure, truncated,
    # malformed_output, and abstention.
    move_count: int | None
    # One of OUTCOMES.
    outcome: str


def _no_moves(outcome: str, decision: bool) -> Verdict:
    return Verdict(parsed_moves=[], hallucination=None if decision else False, mismatch=False,
                   move_count=None, outcome=outcome)


def _lines(raw_response: str) -> list[str]:
    """One surrounding code fence stripped, one trailing \r per line dropped, blank lines dropped."""
    text = raw_response
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    return [line for line in lines if line.strip()]


def _read_lines(lines: list[str], engine) -> tuple[list[str], bool]:
    """Return (parsed moves, whether the layout is exactly one bare move per line)."""
    moves, layout_ok = [], True
    for line in lines:
        tokens = line.split()
        if tokens and all(engine.is_move_token(t) for t in tokens):
            moves += tokens
            layout_ok = layout_ok and tokens == [line]
        else:
            layout_ok = False
    return moves, layout_ok


def read_decision_call(call: object, legal: list[str]) -> str | None:
    """Read one call of a decision model: return "done", "mismatch", or the legal move behind the
    chosen move_<n>, or None when the call is malformed. The id must match exactly (move_1, never
    move_01). Any other answer in the call is ignored. The run loop shares this reader."""
    try:
        choice = call["answers"]["next_move"]["choice"]
    except (KeyError, TypeError):
        return None
    if choice in ("done", "mismatch"):
        return choice
    ids = {f"move_{i}": m for i, m in enumerate(legal, 1)}
    if not isinstance(choice, str) or choice not in ids:
        return None
    return ids[choice]


def _parse_decision(raw_response: str, legal: list[str]) -> tuple[list[str], bool] | None:
    """Return (moves before the first done or mismatch, whether that stop was mismatch) from a
    decision model's array of calls, else None."""
    try:
        data = json.loads(raw_response)
    except ValueError:
        return None
    if not isinstance(data, list) or not data:
        return None
    moves = []
    for call in data:
        read = read_decision_call(call, legal)
        if read is None:
            return None
        if read in ("done", "mismatch"):
            return moves, read == "mismatch"
        moves.append(read)
    return moves, False


def _judge(input: dict, engine, moves: list[str], mismatch: bool, hallucination: bool | None) -> Verdict:
    """Apply legal moves to the input state and return success or failure."""
    state = input["state"]
    for move in moves:
        state = engine.apply_move(state, move)
    # An empty list is never solved, because no input starts solved.
    if input["validity"] == "valid":
        reached = engine.is_solved(state) and not mismatch
    else:
        reached = mismatch
    return Verdict(moves, hallucination, mismatch, len(moves), "success" if reached else "failure")


def validate(input: dict, raw_response: str, stop_reason: str, decision: bool = False) -> Verdict:
    """Judge one raw response against its input and return the Verdict."""
    if stop_reason not in STOP_REASONS:
        raise ValueError(f"unknown stop_reason {stop_reason!r}; expected one of {', '.join(STOP_REASONS)}")
    if stop_reason == "infrastructure_failure":
        return _no_moves("infrastructure_failure", decision)
    if stop_reason == "truncated":
        return _no_moves("truncated", decision)
    if stop_reason == "refused":
        return _no_moves("malformed_output", decision)
    if decision:  # the options come from the engine, so it is needed before parsing
        engine = get_engine(input["puzzle"])
        parsed = _parse_decision(raw_response, engine.legal_moves())
        if parsed is None:
            return _no_moves("malformed_output", True)
        moves, mismatch = parsed
        return _judge(input, engine, moves, mismatch, None)
    lines = _lines(raw_response)
    if not lines:
        return _no_moves("malformed_output", False)
    engine = get_engine(input["puzzle"])
    if lines == ["MISMATCH"]:
        return _judge(input, engine, [], True, False)
    moves, layout_ok = _read_lines(lines, engine)
    if not moves and "MISMATCH" not in lines:
        return _no_moves("abstention", False)
    legal = engine.legal_moves()
    if any(m not in legal for m in moves):
        return Verdict(moves, True, False, len(moves), "hallucination")
    if not layout_ok:
        return Verdict(moves, False, False, len(moves), "format_error")
    return _judge(input, engine, moves, False, False)
