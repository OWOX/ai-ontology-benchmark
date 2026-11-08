# Spec: docs/specs/prompts.md
"""Builds prompts and prompt versions. Reads templates from <templates_dir>/<setup>/<puzzle>.txt
and writes nothing.
"""

import hashlib
import json
import re
from pathlib import Path

from src.puzzles.registry import get_engine
from src.validator import offered_reasons

SETUPS = ("no_model", "descriptive", "prescriptive")
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


_TEMPLATES: dict[tuple, str] = {}


def _read_template(templates_dir: Path, setup: str, puzzle: str) -> str:
    """Return the template text, or raise ValueError if it is missing, has an unknown placeholder,
    or lacks a required one ({state} always, {legal_moves} for the prescriptive setup).
    Each file is read once per process: the cache key holds the resolved path, the file's mtime,
    size, inode and ctime, and the setup, so an edited or replaced file is read again."""
    path = Path(templates_dir) / setup / f"{puzzle}.txt"
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise ValueError(f"{path}: template not found") from None
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns, setup)
    if key in _TEMPLATES:
        return _TEMPLATES[key]
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"{path}: template not found") from None
    required = {"{state}"}
    if setup == "prescriptive":
        required.add("{legal_moves}")
    allowed = required | {"{mismatch_reasons}"}
    for name in PLACEHOLDER.findall(text):
        if name not in allowed:
            raise ValueError(f"{path}: unknown placeholder {name}")
    for name in sorted(required):
        if name not in text:
            raise ValueError(f"{path}: placeholder {name} is missing")
    _TEMPLATES[key] = text
    return text


def fill_template(template: str, input: dict, setup: str) -> str:
    """Return the prompt text for one input under one setup, from the template text."""
    engine = get_engine(input["puzzle"])
    text = template.replace("{state}", engine.render(input["state"]))
    if setup == "prescriptive":
        text = text.replace("{legal_moves}", " ".join(engine.legal_moves()))
    return text.replace("{mismatch_reasons}", ", ".join(f"`{r}`" for r in offered_reasons(engine)))


def build_prompt(templates_dir: Path, input: dict, setup: str) -> str:
    """Return the prompt text for one input under one setup."""
    return fill_template(_read_template(templates_dir, setup, input["puzzle"]), input, setup)


def _versions(templates_dir: Path, inputs: list[dict], questions: dict | None) -> tuple[dict, dict | None]:
    """Build each prompt once and feed two digests: a plain one and, when `questions` is given, one
    seeded with the questions file's bytes that takes, per input, the state a decision model is sent
    first (`decision_state(prompt, [])`) and its request's questions object. Return (plain, decision),
    decision being None without `questions`."""
    with_reasons = questions is not None and uses_mismatch_reasons(templates_dir)
    questions_bytes = _questions_path(templates_dir).read_bytes() if questions is not None else None
    puzzles = list(dict.fromkeys(row["puzzle"] for row in inputs))
    plain: dict[str, dict[str, str]] = {}
    decision: dict[str, dict[str, str]] | None = {} if questions_bytes is not None else None
    for setup in SETUPS:
        plain[setup] = {}
        if decision is not None:
            decision[setup] = {}
        for puzzle in puzzles:
            digest = hashlib.sha256()
            decision_digest = hashlib.sha256(questions_bytes) if questions_bytes is not None else None
            # Check the template even when no input uses it.
            _read_template(templates_dir, setup, puzzle)
            engine = get_engine(puzzle)
            legal = engine.legal_moves()
            reasons = offered_reasons(engine) if with_reasons else None
            for row in inputs:
                if row["puzzle"] == puzzle:
                    prompt = build_prompt(templates_dir, row, setup)
                    digest.update((prompt + "\n").encode())
                    if decision_digest is not None:
                        asked = json.dumps(decision_questions(questions, legal, reasons), sort_keys=True)
                        decision_digest.update((decision_state(prompt, []) + "\n" + asked + "\n").encode())
            plain[setup][puzzle] = digest.hexdigest()[:12]
            if decision is not None:
                decision[setup][puzzle] = decision_digest.hexdigest()[:12]
    return plain, decision


def uses_mismatch_reasons(templates_dir: Path) -> bool:
    """True when every LLM template holds {mismatch_reasons}, false when none does. Raise
    ValueError naming the templates that differ when only some do."""
    held: dict[str, bool] = {}
    for setup in SETUPS:
        for path in sorted((Path(templates_dir) / setup).glob("*.txt")):
            held[f"{setup}/{path.name}"] = "{mismatch_reasons}" in path.read_text(encoding="utf-8")
    if all(held.values()):
        return bool(held)
    if not any(held.values()):
        return False
    missing = ", ".join(name for name, has in held.items() if not has)
    raise ValueError(f"{templates_dir}: {{mismatch_reasons}} is missing from {missing} but held by others")


def prompt_versions(templates_dir: Path, inputs: list[dict]) -> dict[str, dict[str, str]]:
    """Return {setup: {puzzle: version}} for every setup and every puzzle in inputs."""
    return _versions(templates_dir, inputs, None)[0]


QUESTION_KEYS = ("next_move", "done", "mismatch")


def _questions_path(templates_dir: Path) -> Path:
    return Path(templates_dir) / "decision" / "questions.txt"


def parse_questions(text: str, source: object) -> dict[str, str]:
    """Return {"next_move": ..., "done": ..., "mismatch": ...} from the text of questions.txt, one
    `key: text` per line. Raise ValueError naming `source` if a key is missing."""
    questions: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in QUESTION_KEYS:
            questions[key.strip()] = value.strip()
    for key in QUESTION_KEYS:
        if not questions.get(key):
            raise ValueError(f"{source}: key '{key}' is missing")
    return questions


def load_questions(templates_dir: Path) -> dict[str, str]:
    """Return the questions from decision/questions.txt. Raise ValueError naming the file if it
    is missing or lacks a key."""
    path = _questions_path(templates_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"{path}: file not found") from None
    return parse_questions(text, path)


def decision_state(prompt: str, moves: list[str]) -> str:
    """Return the state text a decision model gets: the prompt, then the moves chosen so far."""
    return prompt + "\n\nMoves so far: " + (" ".join(moves) or "none")


def decision_questions(questions: dict, legal: list[str], reasons: list[str] | None = None) -> dict:
    """Return the request's questions object. A move's option id is move_<n>, its position in
    legal from 1, because a move string may hold characters an id may not. With reasons, option
    mismatch_<n> per reason (position from 1) replaces mismatch."""
    criteria = {f"move_{n}": move for n, move in enumerate(legal, start=1)}
    criteria["done"] = questions["done"]
    if reasons is None:
        criteria["mismatch"] = questions["mismatch"]
    else:
        for n, reason in enumerate(reasons, start=1):
            criteria[f"mismatch_{n}"] = f"{questions['mismatch']} Reason: {reason}."
    return {"next_move": {"type": "choice", "instructions": questions["next_move"], "criteria": criteria}}


def both_prompt_versions(templates_dir: Path, inputs: list[dict]) -> tuple[dict, dict]:
    """Return (prompt_versions, decision_prompt_versions), rendering every prompt once."""
    plain, decision = _versions(templates_dir, inputs, load_questions(templates_dir))  # validates the file
    return plain, decision


def decision_prompt_versions(templates_dir: Path, inputs: list[dict]) -> dict[str, dict[str, str]]:
    """Return {setup: {puzzle: version}} for decision models: sha256 over the questions file's
    bytes, then for every input in order its decision state and its request's questions object."""
    return both_prompt_versions(templates_dir, inputs)[1]
