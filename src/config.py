# Spec: docs/specs/config.md
"""Loads and checks the config files. Reads config/release.toml,
config/experiments/<experiment id>.toml, and config/prices.toml, or parses experiment config
text given by the caller (run reads it from stdin). Writes nothing.
"""

import re
import tomllib
from pathlib import Path

from src.puzzles.registry import ENGINES

PROVIDERS = ("anthropic", "openai", "google", "fake")
# Settings that `models` and the run script set themselves.
FORBIDDEN_PARAMS = {
    "model", "model_id", "api_model_id", "prompt", "messages", "system", "input",
    "contents", "max_tokens", "max_output_tokens", "max_completion_tokens",
    "instructions", "system_instruction", "response_format", "response_mime_type",
    "response_schema", "tools", "tool_choice",
}
RELEASE_PATTERN = re.compile(r"\d+\.\d+\.\d+")
EXPERIMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
# Budget limits in USD; an experiment config may set any of them.
DEFAULT_PER_REQUEST_USD = 0.50
DEFAULT_PER_MODEL_USD = 5.00
DEFAULT_PER_EXPERIMENT_USD = 10.00


def _fail(path: object, field: str, problem: str) -> None:
    raise ValueError(f"{path}: field '{field}' {problem}")


def _read(path: Path) -> dict:
    path = Path(path)
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        raise ValueError(f"{path}: file not found") from None
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: not valid TOML ({error})") from None


def _get(path: object, table: dict, field: str, kind: type, where: str = "") -> object:
    """Return table[field] after checking it is present and of the given type."""
    name = where + field
    if field not in table:
        _fail(path, name, "is missing")
    value = table[field]
    if kind is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        ok = isinstance(value, kind) and not (kind is int and isinstance(value, bool))
    if not ok:
        _fail(path, name, f"must be of type {kind.__name__}")
    return value


def _check_min(path: object, field: str, value: float, minimum: int) -> None:
    if value < minimum:
        _fail(path, field, f"must be at least {minimum}")


def load_release_config(path: Path) -> dict:
    path = Path(path)
    config = _read(path)
    seed = _get(path, config, "seed", int)
    _check_min(path, "seed", seed, 1)
    puzzles = _get(path, config, "puzzles", list)
    for puzzle in puzzles:
        if not isinstance(puzzle, str):
            _fail(path, "puzzles", "must hold only strings")
        if puzzle not in ENGINES:
            known = ", ".join(ENGINES)
            _fail(path, "puzzles", f"has unknown puzzle {puzzle!r}; known puzzles: {known}")
    if not puzzles:
        _fail(path, "puzzles", "must not be empty")
    depths = _get(path, config, "scramble_depths", list)
    if not depths:
        _fail(path, "scramble_depths", "must not be empty")
    for depth in depths:
        if not isinstance(depth, int) or isinstance(depth, bool):
            _fail(path, "scramble_depths", "must hold only integers")
        _check_min(path, "scramble_depths", depth, 1)
    count = _get(path, config, "scramble_count", int)
    _check_min(path, "scramble_count", count, 1)
    split = _get(path, config, "valid_invalid_split", float)
    if not 0 <= split <= 1:
        _fail(path, "valid_invalid_split", "must be between 0 and 1")
    return config


def _check_model(path: object, model: object, index: int, seen: set[str]) -> None:
    where = f"models[{index}]."
    if not isinstance(model, dict):
        _fail(path, f"models[{index}]", "must be a table")
    name = _get(path, model, "name", str, where)
    if name in seen:
        _fail(path, where + "name", f"is not unique ({name!r})")
    seen.add(name)
    provider = _get(path, model, "provider", str, where)
    if provider not in PROVIDERS:
        _fail(path, where + "provider", f"must be one of {', '.join(PROVIDERS)}")
    _get(path, model, "api_model_id", str, where)
    if "params" in model:
        params = _get(path, model, "params", dict, where)
        for key in params:
            if key in FORBIDDEN_PARAMS:
                _fail(path, where + "params", f"must not set {key!r}; the run script sets it")


def _check_budget(path: object, config: dict) -> dict:
    """Return the budget with every default filled in; each limit must be above 0."""
    budget = {
        "per_request_usd": DEFAULT_PER_REQUEST_USD,
        "per_model_usd": DEFAULT_PER_MODEL_USD,
        "per_experiment_usd": DEFAULT_PER_EXPERIMENT_USD,
    }
    given = _get(path, config, "budget", dict) if "budget" in config else {}
    for field in given:
        if field not in budget:
            _fail(path, f"budget.{field}", "is not a known budget")
    for field in budget:
        if field in given:
            value = _get(path, given, field, float, "budget.")
            if value <= 0:
                _fail(path, f"budget.{field}", "must be above 0")
            budget[field] = value
    return budget


def _check_puzzles(path: object, config: dict) -> None:
    """An optional `puzzles` is a non-empty list of unique registry names."""
    puzzles = _get(path, config, "puzzles", list)
    if not puzzles:
        _fail(path, "puzzles", "must not be empty")
    for puzzle in puzzles:
        if not isinstance(puzzle, str):
            _fail(path, "puzzles", "must hold only strings")
        if puzzle not in ENGINES:
            known = ", ".join(ENGINES)
            _fail(path, "puzzles", f"has unknown puzzle {puzzle!r}; known puzzles: {known}")
    if len(set(puzzles)) != len(puzzles):
        _fail(path, "puzzles", "must not repeat a puzzle")


def parse_experiment_config(text: str, experiment_id: str, source: str) -> dict:
    """Return the experiment config parsed from TOML text, with `experiment_id` added. Errors name `source`."""
    path = source
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: not valid TOML ({error})") from None
    if not EXPERIMENT_ID_PATTERN.fullmatch(experiment_id):
        _fail(path, "experiment_id", "may contain only letters, digits, '-', and '_'")
    release = _get(path, config, "release", str)
    if not RELEASE_PATTERN.fullmatch(release):
        _fail(path, "release", "must look like MAJOR.MINOR.PATCH, for example 1.0.0")
    attempts = _get(path, config, "attempts", int)
    _check_min(path, "attempts", attempts, 1)
    retry_cap = _get(path, config, "retry_cap", int)
    _check_min(path, "retry_cap", retry_cap, 0)
    max_tokens = _get(path, config, "max_output_tokens", int)
    _check_min(path, "max_output_tokens", max_tokens, 1)
    if "puzzles" in config:
        _check_puzzles(path, config)
    models = _get(path, config, "models", list)
    if not models:
        _fail(path, "models", "must have at least one entry")
    seen: set[str] = set()
    for index, model in enumerate(models):
        _check_model(path, model, index, seen)
    config["budget"] = _check_budget(path, config)
    config["experiment_id"] = experiment_id
    return config


def load_experiment_config(path: Path) -> dict:
    """Return the experiment config with the file stem added as `experiment_id`."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"{path}: file not found") from None
    return parse_experiment_config(text, path.stem, str(path))


def load_prices(path: Path) -> dict:
    path = Path(path)
    prices = _read(path)
    for model_name, entry in prices.items():
        if not isinstance(entry, dict):
            _fail(path, model_name, "must be a table with the two price fields")
        for field in ("price_input_per_mtok", "price_output_per_mtok"):
            value = _get(path, entry, field, float, f"{model_name}.")
            if value < 0:
                _fail(path, f"{model_name}.{field}", "must not be negative")
    return prices
