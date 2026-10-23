# Spec: docs/specs/ui.md
"""Writes the experiment config the UI saves: scalars and lists, [[models]], then [budget].
Reads a config dict and returns text; writes nothing.
"""

import json
import re


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)  # a JSON string is a valid TOML basic string
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    if isinstance(value, dict):  # model params
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }" if value else "{}"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


def _key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def _pairs(table: dict) -> list[str]:
    return [f"{_key(k)} = {_value(v)}" for k, v in table.items()]


def dumps_config(config: dict) -> str:
    lines = _pairs({k: v for k, v in config.items() if k not in ("models", "budget")})
    for model in config["models"]:
        lines += ["", "[[models]]", *_pairs(model)]
    lines += ["", "[budget]", *_pairs(config["budget"])]
    return "\n".join(lines) + "\n"
