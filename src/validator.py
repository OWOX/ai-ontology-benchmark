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



@dataclass(frozen=True)
class Verdict:
    # Moves read from the AI model's output, in order. Empty when there is no usable output.
    # For a decision model they are its calls' next_move choices, in order.
    parsed_moves: list[str]
    # True when at least one parsed move is an impossible move, i.e. not in legal_moves().
    hallucination: bool
    # Whether the AI model picked up the wrong state: its own claim that the input can't be
    # reached from the solved state. Read from its output, not computed. False when there is
    # no usable output. For a decision model it is true when the call that ended the attempt
    # chose mismatch.
    mismatch: bool
    # Number of parsed moves in the half-turn metric. None for infrastructure_failure and malformed_output.
    move_count: int | None
    # infrastructure_failure, malformed_output, hallucination, success, or failure.
    outcome: str


def _no_moves(outcome: str) -> Verdict:
    return Verdict(parsed_moves=[], hallucination=False, mismatch=False, move_count=None, outcome=outcome)


def _parse(raw_response: str) -> tuple[list[str], bool] | None:
    """Return (moves, mismatch) from an LLM's lines, else None when no line is left.

    One surrounding code fence is stripped. Each line loses one trailing \r. Empty and
    whitespace-only lines are dropped, and no other line is stripped. The single line MISMATCH
    means no moves and the mismatch flag on. Otherwise every line is a move.
    """
    text = raw_response
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return None
    if lines == ["MISMATCH"]:
        return [], True
    return lines, False


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


def validate(input: dict, raw_response: str, stop_reason: str, decision: bool = False) -> Verdict:
    """Judge one raw response against its input and return the Verdict."""
    if stop_reason not in STOP_REASONS:
        raise ValueError(f"unknown stop_reason {stop_reason!r}; expected one of {', '.join(STOP_REASONS)}")
    if stop_reason == "infrastructure_failure":
        return _no_moves("infrastructure_failure")
    if stop_reason in ("truncated", "refused"):
        return _no_moves("malformed_output")
    if decision:  # the options come from the engine, so it is needed before parsing
        engine = get_engine(input["puzzle"])
        legal = engine.legal_moves()
        parsed = _parse_decision(raw_response, legal)
    else:
        parsed = _parse(raw_response)
    if parsed is None:
        return _no_moves("malformed_output")
    if not decision:
        engine = get_engine(input["puzzle"])
        legal = engine.legal_moves()
    moves, mismatch = parsed

    if any(move not in legal for move in moves):
        return Verdict(moves, True, mismatch, len(moves), "hallucination")

    state = input["state"]
    for move in moves:
        state = engine.apply_move(state, move)
    # An empty list is never solved, because no input starts solved.
    if input["validity"] == "valid":
        reached = engine.is_solved(state) and not mismatch
    else:
        reached = mismatch
    return Verdict(moves, False, mismatch, len(moves), "success" if reached else "failure")
