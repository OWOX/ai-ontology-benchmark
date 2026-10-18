# Spec: docs/specs/ui.md
"""Shared helpers for the UI: the API error type, id check, and the merged environment.
Reads <root>/.env and os.environ. Writes nothing.
"""

import os
from pathlib import Path

from src.config import EXPERIMENT_ID_PATTERN


class ApiError(Exception):
    """An error that becomes a JSON {"error": message} reply with the given status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def check_id(experiment_id: object) -> str:
    if not isinstance(experiment_id, str) or not EXPERIMENT_ID_PATTERN.fullmatch(experiment_id):
        raise ApiError(400, "field 'id' may contain only letters, digits, '-', and '_'")
    return experiment_id


def parse_env(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines; skip blanks and # comments; strip one pair of surrounding quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def merged_env(root: Path) -> dict[str, str]:
    """The .env values under os.environ, so a real env var wins. Goes to subprocesses only."""
    return {**parse_env(root / ".env"), **os.environ}
