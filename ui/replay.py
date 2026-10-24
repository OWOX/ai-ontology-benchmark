# Spec: docs/specs/ui.md
"""One attempt's moves played on its input, state by state, for the cube panel. Reads
releases/<version>/inputs.jsonl and results/<id>/raw/<model>.jsonl. Writes nothing.
"""

import json
from pathlib import Path

from src.puzzles.registry import get_engine
from src.run.prompts import SETUPS
from src.run.raw import read_raw
from ui import experiments
from ui.common import ApiError


def _field(query: dict, name: str) -> str:
    values = query.get(name)
    if not values or not values[0]:
        raise ApiError(400, f"query '{name}' is required")
    return values[0]


def parse_query(query: dict) -> tuple[str, str, str, int]:
    model, input_id, setup = _field(query, "model"), _field(query, "input_id"), _field(query, "setup")
    if setup not in SETUPS:
        raise ApiError(400, f"query 'setup' must be one of {', '.join(SETUPS)}")
    text = _field(query, "attempt")
    if not text.isascii() or not text.isdigit() or int(text) < 1:
        raise ApiError(400, "query 'attempt' must be a whole number of at least 1")
    return model, input_id, setup, int(text)


def frames_for(puzzle: str, state: str, moves: list) -> tuple[list[str], int | None, bool]:
    """Return (frames, stopped_at, solved). A move outside legal_moves() stops the replay."""
    try:
        engine = get_engine(puzzle)
    except KeyError:
        return [state], None, False  # a puzzle with no engine in the registry has nothing to play
    legal = set(engine.legal_moves())
    frames = [state]
    for index, move in enumerate(moves):
        if not isinstance(move, str) or move not in legal:
            return frames, index, False
        frames.append(engine.apply_move(frames[-1], move))
    return frames, None, bool(moves) and engine.is_solved(frames[-1])


def replay(root: Path, experiment_id: str, query: dict) -> dict:
    model, input_id, setup, attempt = parse_query(query)
    config = experiments.load_config(root, experiment_id)
    if model not in [m["name"] for m in config["models"]]:
        raise ApiError(404, f"model {model} is not in experiment {experiment_id}")
    record = next((r for r in read_raw(root / "results" / experiment_id / "raw" / f"{model}.jsonl")[0]
                   if r.get("input_id") == input_id and r.get("setup") == setup
                   and r.get("attempt_number") == attempt), None)
    if record is None:
        raise ApiError(404, "no such record")
    lines = (root / "releases" / config["release"] / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
    row = next((r for r in map(json.loads, (ln for ln in lines if ln.strip())) if r["input_id"] == input_id), None)
    if row is None:
        raise ApiError(404, f"input {input_id} is not in release {config['release']}")
    moves = list(record.get("parsed_moves") or [])
    frames, stopped_at, solved = frames_for(row["puzzle"], row["state"], moves)
    return {"input_id": input_id, "puzzle": row["puzzle"], "outcome": record.get("outcome"),
            "moves": moves, "frames": frames, "stopped_at": stopped_at, "solved": solved}
