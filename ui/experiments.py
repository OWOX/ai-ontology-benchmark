# Spec: docs/specs/ui.md
"""Catalogue and experiment config handling. Reads releases/, config/models.toml,
config/prices.toml, and config/experiments/<id>.toml. Writes only config/experiments/<id>.toml.
"""

import json
import os
import tempfile
import tomllib
from pathlib import Path

from src.config import (DEFAULT_PER_EXPERIMENT_USD, DEFAULT_PER_MODEL_USD, DEFAULT_PER_REQUEST_USD,
                        RELEASE_PATTERN, load_experiment_config, load_prices)
from src.release.release import latest_version, parse_version
from src.run.models import KEY_VARIABLES
from ui.common import ApiError, check_id
from ui.tomlw import dumps_config

BUDGET_DEFAULTS = {"per_request_usd": DEFAULT_PER_REQUEST_USD, "per_model_usd": DEFAULT_PER_MODEL_USD,
                   "per_experiment_usd": DEFAULT_PER_EXPERIMENT_USD}
DEFAULTS = {"attempts": 3, "retry_cap": 3, "max_output_tokens": 4096, "budget": BUDGET_DEFAULTS}


def release_puzzles(root: Path, version: str) -> list[str]:
    manifest = json.loads((root / "releases" / version / "manifest.json").read_text(encoding="utf-8"))
    return list(manifest["release_config"]["puzzles"])


def list_releases(root: Path) -> list[dict]:
    folder = root / "releases"
    versions = [p.name for p in folder.iterdir()
                if RELEASE_PATTERN.fullmatch(p.name) and (p / "manifest.json").is_file()]
    out = []
    for version in sorted(versions, key=parse_version):
        lines = (folder / version / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
        puzzles = release_puzzles(root, version)
        counts = dict.fromkeys(puzzles, 0)
        for line in lines:
            if line.strip():
                puzzle = json.loads(line)["puzzle"]
                counts[puzzle] = counts.get(puzzle, 0) + 1
        out.append({"version": version, "puzzles": puzzles, "input_count": sum(counts.values()),
                    "input_counts": counts})
    return out


def catalogue_models(root: Path, env: dict) -> list[dict]:
    path = root / "config" / "models.toml"
    entries = tomllib.loads(path.read_text(encoding="utf-8")).get("models", []) if path.is_file() else []
    prices_path = root / "config" / "prices.toml"
    prices = load_prices(prices_path) if prices_path.is_file() else {}
    models = []
    for entry in entries:
        reason = None
        variable = KEY_VARIABLES.get(entry["provider"])
        if entry["name"] not in prices:
            reason = "no price in config/prices.toml"
        elif variable and not env.get(variable):
            reason = f"no API key: set {variable}"
        models.append({"name": entry["name"], "provider": entry["provider"],
                       "api_model_id": entry["api_model_id"], "params": entry.get("params", {}),
                       "disabled_reason": reason})
    return models


def catalogue(root: Path, env: dict) -> dict:
    return {"releases": list_releases(root), "latest": latest_version(root / "releases"),
            "models": catalogue_models(root, env), "defaults": DEFAULTS}


def _number(form: dict, field: str, kind: type, minimum: float, where: dict | None = None):
    table = form if where is None else where
    value = table.get(field)
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    if not ok:
        raise ApiError(400, f"field '{field}' must be a {'whole number' if kind is int else 'number'}")
    if value < minimum:
        raise ApiError(400, f"field '{field}' must be at least {minimum}" if minimum else f"field '{field}' must be above 0")
    return value


def build_config(root: Path, form: dict, env: dict) -> dict:
    """Check the form and build the experiment config dict. Raises ApiError(400)."""
    if not isinstance(form, dict):
        raise ApiError(400, "body must be a JSON object")
    check_id(form.get("id"))
    release = form.get("release")
    known = {r["version"]: r for r in list_releases(root)}
    if release not in known:
        raise ApiError(400, f"field 'release' has unknown release {release!r}")
    puzzles = form.get("puzzles")
    if not isinstance(puzzles, list) or not puzzles or not all(isinstance(p, str) for p in puzzles):
        raise ApiError(400, "field 'puzzles' must be a non-empty list of strings")
    for puzzle in puzzles:
        if puzzle not in known[release]["puzzles"]:
            raise ApiError(400, f"field 'puzzles' has {puzzle!r}, which is not in release {release}")
    names = form.get("models")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ApiError(400, "field 'models' must be a non-empty list of catalogue names")
    by_name = {m["name"]: m for m in catalogue_models(root, env)}
    models = []
    for name in names:
        if name not in by_name:
            raise ApiError(400, f"field 'models' has {name!r}, which is not in config/models.toml")
        if by_name[name]["disabled_reason"]:
            raise ApiError(400, f"field 'models' has {name!r}, which is disabled: {by_name[name]['disabled_reason']}")
        entry = by_name[name]
        model = {k: entry[k] for k in ("name", "provider", "api_model_id")}
        if entry["params"]:
            model["params"] = entry["params"]
        models.append(model)
    budget_form = form.get("budget")
    if not isinstance(budget_form, dict):
        raise ApiError(400, "field 'budget' must be an object")
    budget = {k: float(_number(budget_form, k, float, 0)) for k in BUDGET_DEFAULTS}
    return {"release": release, "puzzles": puzzles, "attempts": _number(form, "attempts", int, 1),
            "retry_cap": _number(form, "retry_cap", int, 0),
            "max_output_tokens": _number(form, "max_output_tokens", int, 1),
            "models": models, "budget": budget}


def _check_loadable(experiment_id: str, text: str) -> None:
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / f"{experiment_id}.toml"
        copy.write_text(text, encoding="utf-8")
        try:
            load_experiment_config(copy)
        except ValueError as error:
            raise ApiError(400, str(error).replace(str(copy), f"{experiment_id}.toml")) from None


def _without_budget(config: dict) -> dict:
    return {k: v for k, v in config.items() if k != "budget"}


def save_experiment(root: Path, form: dict, env: dict) -> dict:
    config = build_config(root, form, env)
    experiment_id = form["id"]
    text = dumps_config(config)
    _check_loadable(experiment_id, text)
    path = root / "config" / "experiments" / f"{experiment_id}.toml"
    if path.exists():
        existing = tomllib.loads(path.read_text(encoding="utf-8"))
        new = tomllib.loads(text)
        if existing == new:
            return {"id": experiment_id, "status": "unchanged"}
        if _without_budget(existing) != _without_budget(new):
            raise ApiError(409, f"experiment {experiment_id} exists with a different config; "
                                "load it or pick a new id")
        status = "budget_updated"
    else:
        status = "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)  # atomic: a running script never reads half a file
    return {"id": experiment_id, "status": status}


def experiment_path(root: Path, experiment_id: str) -> Path:
    return root / "config" / "experiments" / f"{check_id(experiment_id)}.toml"


def load_form(root: Path, experiment_id: str) -> dict:
    """The existing config as the form JSON. Raises ApiError(404) when there is no file."""
    path = experiment_path(root, experiment_id)
    if not path.is_file():
        raise ApiError(404, f"experiment {experiment_id} not found")
    try:
        config = load_experiment_config(path)
    except ValueError as error:
        raise ApiError(400, str(error)) from None
    return {"id": experiment_id, "release": config["release"],
            "puzzles": config.get("puzzles") or release_puzzles(root, config["release"]),
            "models": [m["name"] for m in config["models"]], "attempts": config["attempts"],
            "retry_cap": config["retry_cap"], "max_output_tokens": config["max_output_tokens"],
            "budget": config["budget"]}
