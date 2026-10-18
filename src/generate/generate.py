# Spec: docs/specs/generate.md
"""Builds one input set from the release config. Reads nothing itself (the caller
loads config/release.toml) and writes nothing; it returns the text of inputs.jsonl.
"""

import hashlib
import json

from src.puzzles.registry import get_engine


def make_input_seed(seed: int, input_id: str) -> int:
    """Derive an input seed from the config seed and an input id."""
    digest = hashlib.sha256(f"{seed}:{input_id}".encode()).hexdigest()
    return int(digest[:16], 16)


def build_inputs(release_config: dict, input_set_id: str) -> str:
    """Return the full text of inputs.jsonl, one JSON object per line."""
    seed = release_config["seed"]
    count = release_config["scramble_count"]
    invalid_count = round(release_config["valid_invalid_split"] * count)
    lines = []
    for puzzle in release_config["puzzles"]:
        engine = get_engine(puzzle)
        for depth in release_config["scramble_depths"]:
            for n in range(1, count + 1):
                input_id = f"{puzzle}-d{depth}-{n:03d}"
                valid = {
                    "input_id": input_id,
                    "input_set_id": input_set_id,
                    "input_seed": make_input_seed(seed, input_id),
                    "puzzle": puzzle,
                    "scramble_depth": depth,
                    "validity": "valid",
                    "source_input_id": None,
                    "corruption": None,
                }
                valid["state"], valid["scramble"] = engine.scramble(valid["input_seed"], depth)
                engine.load_state(valid)  # raises if the label and the state disagree
                lines.append(valid)
                if n <= invalid_count:
                    invalid = _invalid_copy(engine, valid, seed)
                    engine.load_state(invalid)
                    lines.append(invalid)
    return "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines)


def _invalid_copy(engine, source: dict, seed: int) -> dict:
    """Return an invalid input made from a valid source, under its own input seed."""
    input_id = source["input_id"] + "-x"
    input_seed = make_input_seed(seed, input_id)
    state, description = engine.corrupt(source["state"], input_seed)
    copy = dict(source)
    copy.update(
        input_id=input_id,
        input_seed=input_seed,
        state=state,
        validity="invalid",
        source_input_id=source["input_id"],
        corruption=description,
    )
    return copy
