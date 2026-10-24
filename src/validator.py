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
    # Moves read from the AI model's JSON output, in order. Empty when there is no usable output.
    parsed_moves: list[str]
    # True when at least one parsed move is an impossible move, i.e. not in legal_moves().
    hallucination: bool
    # The AI model's own claim that the input can't be reached from the solved state.
    # Read from its output, not computed. False when there is no usable output.
    mismatch: bool
    # Number of parsed moves in the half-turn metric. None for infrastructure_failure and malformed_output.
    move_count: int | None
    # infrastructure_failure, malformed_output, hallucination, success, or failure.
    outcome: str


def _no_moves(outcome: str) -> Verdict:
    return Verdict(parsed_moves=[], hallucination=False, mismatch=False, move_count=None, outcome=outcome)


def _parse(raw_response: str) -> tuple[list[str], bool] | None:
    """Return (moves, mismatch) if the response is the required JSON object, else None."""
    text = raw_response
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or set(data) != {"moves", "mismatch"}:
        return None
    moves, mismatch = data["moves"], data["mismatch"]
    if not isinstance(mismatch, bool) or not isinstance(moves, list):
        return None
    if not all(isinstance(move, str) for move in moves):
        return None
    return moves, mismatch


def validate(input: dict, raw_response: str, stop_reason: str) -> Verdict:
    """Judge one raw response against its input and return the Verdict."""
    if stop_reason not in STOP_REASONS:
        raise ValueError(f"unknown stop_reason {stop_reason!r}; expected one of {', '.join(STOP_REASONS)}")
    if stop_reason == "infrastructure_failure":
        return _no_moves("infrastructure_failure")
    if stop_reason in ("truncated", "refused"):
        return _no_moves("malformed_output")
    parsed = _parse(raw_response)
    if parsed is None:
        return _no_moves("malformed_output")
    moves, mismatch = parsed

    engine = get_engine(input["puzzle"])
    legal = engine.legal_moves()
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
