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
    # The offered mismatch reason on the first MISMATCH line or decorated MISMATCH line, or on the
    # mismatch choice of a decision model. None without reasons, and when there is none.
    mismatch_reason: str | None = None
    # The two causes of a hallucination, so evaluate can count them apart: a parsed move that is
    # not in legal_moves(), and a mismatch reason that is a decoy reason.
    impossible_move: bool = False
    decoy: bool = False


def offered_reasons(engine) -> list[str]:
    """The mismatch reasons a prompt offers: the engine's, then `other`. The one source of the list."""
    return engine.mismatch_reasons() + ["other"]


def _no_moves(outcome: str, decision: bool, reasons: list[str] | None = None) -> Verdict:
    # A decision model has no hallucination flag without reasons, since it can't return an impossible move.
    return Verdict(parsed_moves=[], hallucination=None if decision and reasons is None else False,
                   mismatch=False, move_count=None, outcome=outcome)


def _lines(raw_response: str) -> list[str]:
    """One surrounding code fence stripped, one trailing \r per line dropped, blank lines dropped."""
    text = raw_response
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    return [line for line in lines if line.strip()]


# A list marker at the start of a token: `1.`, `1)`, `-`, `*`, or a bullet.
LIST_MARKER = re.compile(r"^(?:\d+[.)]|[-*\u2022])")
# Characters stripped from both ends of a token, for classification only. The prime ' is not one of
# them, because it is part of a move.
DECORATION = "`*_.)("


def _strip_token(token: str, first: bool = False) -> str:
    """Strip a list marker glued to the first token left after dropped markers and surrounding decoration from one
    token, for classification only."""
    if first:
        token = LIST_MARKER.sub("", token)
    while True:
        stripped = token.strip(DECORATION)
        if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
            stripped = stripped[1:-1]
        if stripped == token:
            return token
        token = stripped


LETTER_MARKER = re.compile(r"[A-Za-z][.)]")


# A token that is only a numeric or bullet marker can never be a move, so it is dropped anywhere.
WHOLE_MARKER = re.compile(r"(?:\d+[.)]|[-*\u2022])")


def _decorated_tokens(line: str, engine) -> list[str]:
    """The tokens of a line split on whitespace and commas and stripped, with empty ones dropped.
    A token that is only a numeric or bullet marker is dropped wherever it is, and one glued to the
    first token left after those is stripped from it. A single letter and a full stop or bracket,
    as in `b)`, is a lettered list marker only as that first token, and is kept when it is a
    capital letter that is a move token, as in `R.`."""
    tokens = []
    first = True
    for raw in line.replace(",", " ").split():
        if WHOLE_MARKER.fullmatch(raw):
            continue
        token = _strip_token(raw, first)
        lettered = (first and LETTER_MARKER.fullmatch(raw)
                    and not (raw[0].isupper() and engine.is_move_token(token)))
        first = False
        if token and not lettered:
            tokens.append(token)
    return tokens


def _read_lines(lines: list[str], engine, reasons: list[str] | None) -> tuple[list[str], bool, str | None, bool]:
    """Return (parsed moves, whether the layout is exactly one bare move per line, the reason of
    the first offered MISMATCH line, whether a MISMATCH line was seen). A move line is bare tokens
    that are all move tokens. A decorated move line has them only once list markers and decoration
    are stripped. Under reasons a MISMATCH line has MISMATCH as its first stripped token and the
    reason after it, and without reasons MISMATCH as its only stripped token. Either counts as an
    answer in the wrong layout, since a single MISMATCH line is read before this."""
    moves, layout_ok, reason, mismatch_line = [], True, None, False
    for line in lines:
        tokens = line.split()
        if tokens and all(engine.is_move_token(t) for t in tokens):
            moves += tokens
            layout_ok = layout_ok and tokens == [line]
            continue
        layout_ok = False
        decorated = _decorated_tokens(line, engine)
        if decorated and all(engine.is_move_token(t) for t in decorated):
            moves += decorated
        elif reasons is None and decorated == ["MISMATCH"]:
            mismatch_line = True
        elif reasons is not None and decorated and decorated[0] == "MISMATCH":
            mismatch_line = True
            if reason is None and " ".join(decorated[1:]) in reasons:
                reason = " ".join(decorated[1:])
    return moves, layout_ok, reason, mismatch_line


def read_decision_call(call: object, legal: list[str], reasons: list[str] | None = None) -> str | None:
    """Read one call of a decision model: return "done", "MISMATCH <reason>" for a mismatch_<n>
    choice under reasons, "MISMATCH" for mismatch without them, or the legal move behind the
    chosen move_<n>, or None when the call is malformed. These are what a text model would have
    written. The id must match exactly (move_1, never move_01). Any other answer in the call is
    ignored. The run loop shares this reader."""
    try:
        choice = call["answers"]["next_move"]["choice"]
    except (KeyError, TypeError):
        return None
    if not isinstance(choice, str):
        return None
    if choice == "done":
        return choice
    if reasons is None:
        if choice == "mismatch":
            return "MISMATCH"
    else:
        ids = {f"mismatch_{i}": r for i, r in enumerate(reasons, 1)}
        if choice in ids:
            return f"MISMATCH {ids[choice]}"
    ids = {f"move_{i}": m for i, m in enumerate(legal, 1)}
    return ids.get(choice)


def _parse_decision(raw_response: str, legal: list[str],
                    reasons: list[str] | None) -> tuple[list[str], bool, str | None] | None:
    """Return (moves before the first done or mismatch, whether that stop was a mismatch choice, its
    reason) from a decision model's array of calls, else None."""
    try:
        data = json.loads(raw_response)
    except ValueError:
        return None
    if not isinstance(data, list) or not data:
        return None
    moves = []
    for call in data:
        read = read_decision_call(call, legal, reasons)
        if read is None:
            return None
        if read == "done":
            return moves, False, None
        if read.startswith("MISMATCH"):
            return moves, True, read[len("MISMATCH "):] if reasons is not None else None
        moves.append(read)
    return moves, False, None


def _judge(input: dict, engine, moves: list[str], mismatch: bool, hallucination: bool | None,
           reason: str | None = None) -> Verdict:
    """Apply legal moves to the input state and return success or failure."""
    state = input["state"]
    for move in moves:
        state = engine.apply_move(state, move)
    # An empty list is never solved, because no input starts solved.
    if input["validity"] == "valid":
        reached = engine.is_solved(state) and not mismatch
    else:
        reached = mismatch
    return Verdict(moves, hallucination, mismatch, len(moves), "success" if reached else "failure", reason)


def _hallucination(engine, moves: list[str], mismatch: bool, reason: str | None,
                   reasons: list[str] | None) -> Verdict | None:
    """The hallucination verdict when a parsed move is not legal or the reason is a decoy, else None."""
    legal = engine.legal_moves()
    impossible = any(m not in legal for m in moves)
    decoy = reasons is not None and reason is not None and reason in engine.decoy_reasons()
    if not (impossible or decoy):
        return None
    return Verdict(moves, True, mismatch, len(moves), "hallucination", reason, impossible, decoy)


def validate(input: dict, raw_response: str, stop_reason: str, decision: bool = False,
             reasons: list[str] | None = None) -> Verdict:
    """Judge one raw response against its input and return the Verdict. `reasons` are the offered
    mismatch reasons (see offered_reasons), or None for a release without them."""
    if stop_reason not in STOP_REASONS:
        raise ValueError(f"unknown stop_reason {stop_reason!r}; expected one of {', '.join(STOP_REASONS)}")
    if stop_reason == "infrastructure_failure":
        return _no_moves("infrastructure_failure", decision, reasons)
    if stop_reason == "truncated":
        return _no_moves("truncated", decision, reasons)
    if stop_reason == "refused":
        return _no_moves("malformed_output", decision, reasons)
    if decision:  # the options come from the engine, so it is needed before parsing
        engine = get_engine(input["puzzle"])
        parsed = _parse_decision(raw_response, engine.legal_moves(), reasons)
        if parsed is None:
            return _no_moves("malformed_output", True, reasons)
        moves, mismatch, reason = parsed
        halluc = _hallucination(engine, moves, mismatch, reason, reasons)
        if halluc:
            return halluc
        return _judge(input, engine, moves, mismatch, None if reasons is None else False, reason)
    lines = _lines(raw_response)
    if not lines:
        return _no_moves("malformed_output", False)
    engine = get_engine(input["puzzle"])
    if len(lines) == 1 and (lines[0] == "MISMATCH" if reasons is None
                            else lines[0].startswith("MISMATCH ") and lines[0][9:] in reasons):
        reason = None if reasons is None else lines[0][9:]
        return _hallucination(engine, [], True, reason, reasons) or _judge(input, engine, [], True, False, reason)
    moves, layout_ok, reason, mismatch_line = _read_lines(lines, engine, reasons)
    if not moves and not mismatch_line:
        return _no_moves("abstention", False)
    halluc = _hallucination(engine, moves, False, reason, reasons)
    if halluc:
        return halluc
    if not layout_ok:
        return Verdict(moves, False, False, len(moves), "format_error", reason)
    return _judge(input, engine, moves, False, False)
