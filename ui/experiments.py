# Spec: docs/specs/ui.md
"""Form defaults, the default experiment id, the stored config as a form, and the live snapshot.
Reads one experiment branch and the release inputs through Bundles (which read git refs). Writes nothing.
"""

import re
from datetime import datetime

from src.config import (DEFAULT_PER_EXPERIMENT_USD, DEFAULT_PER_MODEL_USD, DEFAULT_PER_REQUEST_USD,
                        parse_experiment_config)
from src.run.prompts import SETUPS
from src.run.run import experiment_inputs
from ui import expdata
from ui.catalogue import config_form
from ui.common import ApiError, check_id

BUDGET_DEFAULTS = {"per_request_usd": DEFAULT_PER_REQUEST_USD, "per_model_usd": DEFAULT_PER_MODEL_USD,
                   "per_experiment_usd": DEFAULT_PER_EXPERIMENT_USD}
DEFAULTS = {"attempts": 3, "retry_cap": 3, "max_output_tokens": 32000, "reasoning_effort": "medium", "budget": BUDGET_DEFAULTS}


def default_id(models: list[str], puzzles: list[str], now: datetime) -> str:
    def part(names: list[str], word: str) -> str:
        return f"{len(names)}-{word}" if len(names) > 3 else "-".join(names)
    raw = f"{part(models, 'models')}_{part(puzzles, 'puzzles')}_{now:%Y%m%d-%H%M}"
    return re.sub(r"[^A-Za-z0-9_-]", "-", raw)


def load_form(bundles, experiment_id: str) -> dict:
    """The config on the experiment's branch (local first, else remote) as the form. 404 when there is none."""
    text = bundles.branch_config(check_id(experiment_id))
    if text is None:
        raise ApiError(404, f"experiment {experiment_id} not found")
    try:
        config = parse_experiment_config(text, experiment_id, f"results/{experiment_id}/experiment.toml")
    except ValueError as error:
        raise ApiError(400, str(error)) from None
    return config_form(config, bundles.release_puzzles(config["release"]) or [])


def planned_inputs(bundles, config: dict) -> list[dict]:
    """The inputs an experiment plays, in release order: `experiment_inputs` over the release on `main`."""
    puzzles = config.get("puzzles") or bundles.release_puzzles(config["release"]) or []
    git = bundles.git
    return experiment_inputs({**config, "puzzles": puzzles}, expdata.read_inputs(git, git.main_ref(), config["release"]))


def snapshot(bundles, experiment_id: str, live_ids: set[str], job_states: dict, parallel: dict | None = None) -> dict:
    """Live state of one experiment: its inputs, the raw records so far, and its job states and each running job's `--parallel`."""
    exp = bundles.loaded(check_id(experiment_id), live_ids)
    config = exp["config"]
    if config is None:
        raise ApiError(400, exp["error"])
    inputs = planned_inputs(bundles, config)
    names = [m["name"] for m in config["models"]]
    keys = ("model", "input_id", "setup", "attempt_number", "outcome", "mismatch", "created_at")
    report = f"results/{experiment_id}/{exp['report_version']}.md" if exp["report_md"] is not None else None
    return {
        "id": experiment_id, "release": config["release"], "setups": list(SETUPS),
        "attempts": config["attempts"], "models": names,
        "inputs": [{k: row[k] for k in ("input_id", "puzzle", "scramble_depth", "validity", "state")}
                   for row in inputs],
        "records": [{k: r.get(k) for k in keys} for name in names for r in exp["records"].get(name, [])],
        "jobs": job_states, "parallel": parallel or {}, "report": report,
    }
