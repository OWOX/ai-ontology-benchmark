# Spec: docs/specs/ui.md
"""Shared helpers for the UI: the API error type, id check, and the merged environment.
Reads <root>/secrets/ and os.environ. Writes nothing.
"""

import os
from pathlib import Path

from src.config import BATCH_PRICE_FIELDS, EXPERIMENT_ID_PATTERN
from src.run.models import ACCOUNT_VARIABLES, KEY_VARIABLES


PRICE_FIELDS = ("price_input_per_mtok", "price_output_per_mtok")


def missing_price_field(price: object, batch: bool = False) -> str | None:
    """The first price field of an AI model's entry in `config/prices.toml` that is not a number, else `None`.
    With `batch`, the batch price fields are checked too."""
    for field in PRICE_FIELDS + (BATCH_PRICE_FIELDS if batch else ()):
        value = price.get(field) if isinstance(price, dict) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return field
    return None


def timed(record: dict) -> bool:
    """True when a record's latency counts for a typical time: not an infrastructure failure, and a number."""
    latency = record.get("latency_s")
    return record.get("outcome") != "infrastructure_failure" and isinstance(latency, (int, float))


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


def merged_env(root: Path) -> dict[str, str]:
    """The saved API keys under os.environ, so a real, non-empty env var wins. Goes to subprocesses only."""
    from ui import secrets  # here, because ui.secrets imports ApiError from this module

    saved_names = {*KEY_VARIABLES.values(), *ACCOUNT_VARIABLES.values()}
    real = {name: value for name, value in os.environ.items() if value.strip() or name not in saved_names}
    return {**secrets.env(root), **real}
