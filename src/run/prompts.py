# Spec: docs/specs/prompts.md
"""Builds prompts and prompt versions. Reads templates from <templates_dir>/<setup>/<puzzle>.txt
and writes nothing.
"""

import hashlib
import re
from pathlib import Path

from src.puzzles.registry import get_engine

SETUPS = ("no_model", "descriptive", "prescriptive")
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _read_template(templates_dir: Path, setup: str, puzzle: str) -> str:
    """Return the template text, or raise ValueError if it is missing, has an unknown placeholder,
    or lacks a required one ({state} always, {legal_moves} for the prescriptive setup)."""
    path = Path(templates_dir) / setup / f"{puzzle}.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"{path}: template not found") from None
    allowed = {"{state}"}
    if setup == "prescriptive":
        allowed.add("{legal_moves}")
    for name in PLACEHOLDER.findall(text):
        if name not in allowed:
            raise ValueError(f"{path}: unknown placeholder {name}")
    for name in sorted(allowed):
        if name not in text:
            raise ValueError(f"{path}: placeholder {name} is missing")
    return text


def build_prompt(templates_dir: Path, input: dict, setup: str) -> str:
    """Return the prompt text for one input under one setup."""
    puzzle = input["puzzle"]
    engine = get_engine(puzzle)
    text = _read_template(templates_dir, setup, puzzle)
    text = text.replace("{state}", engine.render(input["state"]))
    if setup == "prescriptive":
        text = text.replace("{legal_moves}", " ".join(engine.legal_moves()))
    return text


def prompt_versions(templates_dir: Path, inputs: list[dict]) -> dict[str, dict[str, str]]:
    """Return {setup: {puzzle: version}} for every setup and every puzzle in inputs."""
    puzzles = list(dict.fromkeys(row["puzzle"] for row in inputs))
    versions: dict[str, dict[str, str]] = {}
    for setup in SETUPS:
        versions[setup] = {}
        for puzzle in puzzles:
            digest = hashlib.sha256()
            # Check the template even when no input uses it.
            _read_template(templates_dir, setup, puzzle)
            for row in inputs:
                if row["puzzle"] == puzzle:
                    digest.update((build_prompt(templates_dir, row, setup) + "\n").encode())
            versions[setup][puzzle] = digest.hexdigest()[:12]
    return versions
