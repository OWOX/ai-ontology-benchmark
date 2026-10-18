# Spec: docs/specs/ui.md
"""Commit preview and commit with a pull request. Reads config/experiments/<id>.toml and
results/<id>/. Writes git objects, refs/heads/results/<id>, and the remote branch. Never touches
the work tree, the real index, or HEAD: it builds the tree in a temporary index file.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from src.config import load_experiment_config
from ui.common import ApiError, merged_env

Emit = Callable[[str, str], None]  # (stream, text)


def sh(root: Path, argv: list[str], emit: Emit, extra_env: dict | None = None, check: bool = True):
    """Run one command in the root, echo it and its output, and return the result."""
    emit("cmd", " ".join(argv))
    result = subprocess.run(argv, cwd=root, env={**merged_env(root), **(extra_env or {})},
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    for stream, text in (("stdout", result.stdout), ("stderr", result.stderr)):
        for line in text.splitlines():
            emit(stream, line)
    if check and result.returncode != 0:
        raise ApiError(409, f"{' '.join(argv[:2])} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def prepare(root: Path, experiment_id: str, emit: Emit) -> dict:
    """Build the tree and return {branch, base, files, diffstat, tree, parent}. Raises 409."""
    config_path = root / "config" / "experiments" / f"{experiment_id}.toml"
    if not config_path.is_file():
        raise ApiError(404, f"experiment {experiment_id} not found")
    release = load_experiment_config(config_path)["release"]
    if not (root / "results" / experiment_id / f"{release}.md").is_file():
        raise ApiError(409, "no report yet; run evaluate first")
    branch = f"results/{experiment_id}"
    sh(root, ["git", "fetch", "origin", "main"], emit)
    local = sh(root, ["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], emit, check=False)
    parent = local.stdout.strip() if local.returncode == 0 else \
        sh(root, ["git", "rev-parse", "--verify", "refs/remotes/origin/main"], emit).stdout.strip()
    with tempfile.TemporaryDirectory() as folder:
        index = {"GIT_INDEX_FILE": os.path.join(folder, "index")}
        sh(root, ["git", "read-tree", parent], emit, index)
        sh(root, ["git", "add", "--", f"config/experiments/{experiment_id}.toml", f"results/{experiment_id}"], emit, index)
        tree = sh(root, ["git", "write-tree"], emit, index).stdout.strip()
    files = sh(root, ["git", "diff", "--name-only", parent, tree], emit).stdout.split()
    if not files:
        raise ApiError(409, "nothing to commit")
    diffstat = sh(root, ["git", "diff", "--stat", parent, tree], emit).stdout.rstrip()
    return {"branch": branch, "base": parent, "files": files, "diffstat": diffstat, "tree": tree}


def preview(root: Path, experiment_id: str, emit: Emit) -> dict:
    info = prepare(root, experiment_id, emit)
    return {k: info[k] for k in ("branch", "base", "files", "diffstat")}


def pr_body(config: dict, experiment_id: str) -> str:
    puzzles = config.get("puzzles") or "every puzzle in the release"
    if isinstance(puzzles, list):
        puzzles = ", ".join(puzzles)
    models = ", ".join(m["name"] for m in config["models"])
    return (f"Results of experiment {experiment_id}.\n\nRelease: {config['release']}\nPuzzles: {puzzles}\n"
            f"AI models: {models}\nAttempts per input and setup: {config['attempts']}\n"
            f"Report: results/{experiment_id}/{config['release']}.md\n")


def commit(root: Path, experiment_id: str, emit: Emit) -> dict:
    info = prepare(root, experiment_id, emit)
    branch, parent = info["branch"], info["base"]
    sha = sh(root, ["git", "commit-tree", info["tree"], "-p", parent, "-m", f"Results: experiment {experiment_id}"],
             emit).stdout.strip()
    sh(root, ["git", "update-ref", f"refs/heads/{branch}", sha], emit)
    sh(root, ["git", "push", "-u", "origin", branch], emit)
    gh = merged_env(root).get("UI_GH") or "gh"
    found = sh(root, [gh, "pr", "view", branch, "--json", "url"], emit, check=False)
    url = ""
    if found.returncode == 0:
        try:
            url = json.loads(found.stdout).get("url", "")
        except ValueError:
            url = ""
    if not url:
        config = load_experiment_config(root / "config" / "experiments" / f"{experiment_id}.toml")
        made = sh(root, [gh, "pr", "create", "--base", "main", "--head", branch, "--title",
                         f"Results: experiment {experiment_id}", "--body", pr_body(config, experiment_id)], emit)
        url = made.stdout.strip().splitlines()[-1] if made.stdout.strip() else ""
    return {"branch": branch, "commit": sha, "pr_url": url}
