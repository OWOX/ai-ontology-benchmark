# Spec: docs/specs/ui.md
"""The experiment form: checks it against the catalogue and releases on `main`, builds the config
text a run reads on stdin, and decides the status of a start against the experiment's branch.
Reads through Bundles and the work tree's `results/<id>/experiment.toml`. Writes nothing.
"""

import tomllib
from pathlib import Path

from src.config import parse_experiment_config
from ui.bundle import Bundles
from ui.common import ApiError, check_id
from ui.experiments import BUDGET_DEFAULTS
from ui.tomlw import dumps_config


def _number(form: dict, field: str, kind: type, minimum: float):
    value = form.get(field)
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    if not ok:
        raise ApiError(400, f"field '{field}' must be a {'whole number' if kind is int else 'number'}")
    if value < minimum:
        raise ApiError(400, f"field '{field}' must be at least {minimum}" if minimum else f"field '{field}' must be above 0")
    return value


def _names(form: dict, field: str, what: str) -> list[str]:
    names = form.get(field)
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ApiError(400, f"field '{field}' must be a non-empty list of {what}")
    return names


def build_config(bundles: Bundles, form: dict, env: dict) -> dict:
    """Check the form and build the experiment config dict. Raises ApiError(400)."""
    if not isinstance(form, dict):
        raise ApiError(400, "body must be a JSON object")
    check_id(form.get("id"))
    release = form.get("release")
    known = bundles.release_puzzles(release) if isinstance(release, str) else None
    if known is None:
        raise ApiError(400, f"field 'release' has unknown release {release!r}")
    puzzles = _names(form, "puzzles", "strings")
    for puzzle in puzzles:
        if puzzle not in known:
            raise ApiError(400, f"field 'puzzles' has {puzzle!r}, which is not in release {release}")
    catalogue, models = bundles.models(env), []
    for name in _names(form, "models", "catalogue names"):
        if name not in catalogue:
            raise ApiError(400, f"field 'models' has {name!r}, which is not in config/models.toml on main")
        entry = catalogue[name]
        if entry["disabled_reason"]:
            raise ApiError(400, f"field 'models' has {name!r}, which is disabled: {entry['disabled_reason']}")
        model = {"name": name, "provider": entry["provider"], "api_model_id": entry["api_model_id"]}
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


def config_text(bundles: Bundles, form: dict, env: dict) -> str:
    """The config TOML for a form, checked with `parse_experiment_config`."""
    text = dumps_config(build_config(bundles, form, env))
    try:
        parse_experiment_config(text, form["id"], f"{form['id']}.toml")
    except ValueError as error:
        raise ApiError(400, str(error)) from None
    return text


def _same(bundles: Bundles, existing: dict, new: dict, budget: bool) -> bool:
    """Equal configs; a missing `puzzles` counts as every puzzle of the release, and `budget` is compared only if asked."""
    existing = {**existing, "puzzles": existing.get("puzzles") or bundles.release_puzzles(existing["release"])}
    skip = () if budget else ("budget",)
    def canon(config: dict) -> dict:
        out = {k: v for k, v in config.items() if k not in skip}
        if isinstance(out.get("puzzles"), list):
            out["puzzles"] = sorted(out["puzzles"])
        if isinstance(out.get("models"), list):
            out["models"] = sorted(out["models"], key=lambda m: str(m.get("name")) if isinstance(m, dict) else str(m))
        return out
    return canon(existing) == canon(new)


def resolve_status(bundles: Bundles, root: Path, experiment_id: str, text: str) -> tuple[str, str]:
    """(status, stdin text): `created`, `unchanged`, or `budget_updated`; ApiError(409) when the branch cannot be
    resumed. A resume sends the branch's own config with only its budget replaced, so `run`'s stored-copy check
    accepts it whatever shape the branch config has. A branch with no `experiment.toml` is no experiment."""
    saved = bundles.branch_config(experiment_id)
    if saved is None:
        return "created", text
    try:
        existing = tomllib.loads(saved)
    except tomllib.TOMLDecodeError:
        existing = None
    new = tomllib.loads(text)
    if existing is not None and _same(bundles, existing, new, True):
        status = "unchanged"
    elif existing is not None and _same(bundles, existing, new, False):
        status = "budget_updated"
    else:
        raise ApiError(409, f"experiment {experiment_id} exists with a different config; load it or pick a new id")
    if not (root / "results" / experiment_id / "experiment.toml").is_file():
        raise ApiError(409, f"the results of {experiment_id} are not in this checkout; check out its branch first")
    return status, dumps_config({**existing, "budget": new["budget"]})
