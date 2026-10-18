# Spec: docs/specs/ui.md
"""The live snapshot of one experiment. Reads the experiment config, its release inputs, and
results/<id>/raw/*.jsonl. Writes nothing.
"""

import json
from pathlib import Path

from src.config import load_experiment_config
from src.run.prompts import SETUPS
from src.run.raw import read_raw
from src.run.run import pending_attempts
from ui.experiments import experiment_path, release_puzzles
from ui.common import ApiError


def slim(record: dict) -> dict:
    return {"model": record.get("model"), "input_id": record.get("input_id"),
            "setup": record.get("setup"), "attempt_number": record.get("attempt_number"),
            "outcome": record.get("outcome"), "mismatch": record.get("mismatch")}


def load_experiment(root: Path, experiment_id: str) -> tuple[dict, list[dict]]:
    """Return (config, inputs of the experiment's puzzles in release order)."""
    path = experiment_path(root, experiment_id)
    if not path.is_file():
        raise ApiError(404, f"experiment {experiment_id} not found")
    try:
        config = load_experiment_config(path)
    except ValueError as error:
        raise ApiError(400, str(error)) from None
    puzzles = config.get("puzzles") or release_puzzles(root, config["release"])
    lines = (root / "releases" / config["release"] / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
    inputs = [row for row in map(json.loads, (ln for ln in lines if ln.strip())) if row["puzzle"] in puzzles]
    return config, inputs


def in_progress(root: Path, experiment_id: str, model: str) -> dict | None:
    """The first pending attempt of the model: an inference, as run reports nothing."""
    config, inputs = load_experiment(root, experiment_id)
    raw_dir = root / "results" / experiment_id / "raw"
    first = next(pending_attempts(config, inputs, raw_dir, model), None)
    if first is None:
        return None
    row, _, setup, number = first
    return {"input_id": row["input_id"], "setup": setup, "attempt_number": number}


def snapshot(root: Path, experiment_id: str, job_states: dict, alive_models: set[str]) -> dict:
    config, inputs = load_experiment(root, experiment_id)
    raw_dir = root / "results" / experiment_id / "raw"
    names = [m["name"] for m in config["models"]]
    records = [slim(r) for name in names for r in read_raw(raw_dir / f"{name}.jsonl")[0]]
    report = f"results/{experiment_id}/{config['release']}.md"
    return {
        "id": experiment_id, "release": config["release"], "setups": list(SETUPS),
        "attempts": config["attempts"], "models": names,
        "inputs": [{k: row[k] for k in ("input_id", "puzzle", "scramble_depth", "validity", "state")}
                   for row in inputs],
        "records": records,
        "in_progress": {n: (in_progress(root, experiment_id, n) if n in alive_models else None) for n in names},
        "jobs": job_states,
        "report": report if (root / report).is_file() else None,
    }
