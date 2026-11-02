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


QUESTION_KEYS = ("next_move", "done", "mismatch")


def _questions_path(templates_dir: Path) -> Path:
    return Path(templates_dir) / "decision" / "questions.txt"


def load_questions(templates_dir: Path) -> dict[str, str]:
    """Return {"next_move": ..., "done": ..., "mismatch": ...} from decision/questions.txt, one
    `key: text` per line. Raise ValueError naming the file if it is missing or lacks a key."""
    path = _questions_path(templates_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"{path}: file not found") from None
    questions: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in QUESTION_KEYS:
            questions[key.strip()] = value.strip()
    for key in QUESTION_KEYS:
        if not questions.get(key):
            raise ValueError(f"{path}: key '{key}' is missing")
    return questions


def decision_state(prompt: str, moves: list[str]) -> str:
    """Return the state text a decision model gets: the prompt, then the moves chosen so far."""
    return prompt + "\n\nMoves so far: " + (" ".join(moves) or "none")


def decision_questions(questions: dict, legal: list[str]) -> dict:
    """Return the request's questions object. A move's option id is move_<n>, its position in
    legal from 1, because a move string may hold characters an id may not."""
    criteria = {f"move_{n}": move for n, move in enumerate(legal, start=1)}
    criteria["done"] = questions["done"]
    return {
        "next_move": {"type": "choice", "instructions": questions["next_move"], "criteria": criteria},
        "mismatch": {"type": "noul", "instructions": questions["mismatch"]},
    }


def decision_prompt_versions(templates_dir: Path, inputs: list[dict]) -> dict[str, dict[str, str]]:
    """Return {setup: {puzzle: version}} for decision models: sha256 over the questions file's
    bytes, then every prompt for that setup and puzzle in input order, each followed by a newline."""
    path = _questions_path(templates_dir)
    load_questions(templates_dir)  # validate the file
    questions_bytes = path.read_bytes()
    puzzles = list(dict.fromkeys(row["puzzle"] for row in inputs))
    versions: dict[str, dict[str, str]] = {}
    for setup in SETUPS:
        versions[setup] = {}
        for puzzle in puzzles:
            digest = hashlib.sha256(questions_bytes)
            _read_template(templates_dir, setup, puzzle)
            for row in inputs:
                if row["puzzle"] == puzzle:
                    digest.update((build_prompt(templates_dir, row, setup) + "\n").encode())
            versions[setup][puzzle] = digest.hexdigest()[:12]
    return versions
