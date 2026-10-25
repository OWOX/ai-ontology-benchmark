# Spec: docs/specs/ui.md
"""Commit preview and commit with a pull request. Reads config/experiments/<id>.toml and
results/<id>/. Writes git objects, the remote branch results/<id>, and, after a push succeeds,
refs/heads/results/<id>. Never touches the work tree, the real index, or HEAD: it builds the
tree in a temporary index file.
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
    base = {k: v for k, v in merged_env(root).items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    result = subprocess.run(argv, cwd=root, env={**base, **(extra_env or {})},
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    for stream, text in (("stdout", result.stdout), ("stderr", result.stderr)):
        for line in text.splitlines():
            emit(stream, line)
    if check and result.returncode != 0:
        raise ApiError(409, f"{' '.join(argv[:2])} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def newest_mtime(folder: Path) -> float:
    return max((p.stat().st_mtime for p in folder.glob("*.jsonl")), default=0.0)


def prepare(root: Path, experiment_id: str, emit: Emit) -> dict:
    """Build the tree and return {branch, base, files, diffstat, tree, pushed}. Raises 409."""
    config_path = root / "config" / "experiments" / f"{experiment_id}.toml"
    if not config_path.is_file():
        raise ApiError(404, f"experiment {experiment_id} not found")
    release = load_experiment_config(config_path)["release"]
    report = root / "results" / experiment_id / f"{release}.md"
    if not report.is_file():
        raise ApiError(409, "no report yet; run evaluate first")
    if report.stat().st_mtime < newest_mtime(root / "results" / experiment_id / "raw"):
        raise ApiError(409, "the report is older than the raw records; evaluate again first")
    branch = f"results/{experiment_id}"
    sh(root, ["git", "fetch", "origin", "main"], emit)
    remote = f"refs/remotes/origin/{branch}"
    pushed = sh(root, ["git", "fetch", "origin", branch], emit, check=False).returncode == 0 and \
        sh(root, ["git", "rev-parse", "--verify", "-q", remote], emit, check=False).returncode == 0
    parent = sh(root, ["git", "rev-parse", "--verify", remote if pushed else "refs/remotes/origin/main"],
                emit).stdout.strip()
    # `run` commits to the local branch as it goes: build on it when it holds the remote branch.
    local = sh(root, ["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], emit, check=False).stdout.strip()
    if local and (not pushed or sh(root, ["git", "merge-base", "--is-ancestor", parent, local], emit,
                                   check=False).returncode == 0):
        parent = local
    ahead = bool(local) and parent == local and (not pushed or sh(
        root, ["git", "rev-parse", remote], emit).stdout.strip() != local)  # commits still to push
    with tempfile.TemporaryDirectory() as folder:
        index = {"GIT_INDEX_FILE": os.path.join(folder, "index")}
        sh(root, ["git", "read-tree", parent], emit, index)
        sh(root, ["git", "add", "--", f"config/experiments/{experiment_id}.toml", f"results/{experiment_id}"], emit, index)
        tree = sh(root, ["git", "write-tree"], emit, index).stdout.strip()
    files = sh(root, ["git", "diff", "--name-only", parent, tree], emit).stdout.splitlines()
    if not files and not pushed and not ahead:
        raise ApiError(409, "nothing to commit")
    diffstat = sh(root, ["git", "diff", "--stat", parent, tree], emit).stdout.rstrip()
    return {"branch": branch, "base": parent, "files": files, "diffstat": diffstat, "tree": tree, "pushed": pushed, "ahead": ahead}


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


def open_pr_url(root: Path, branch: str, emit: Emit) -> str:
    """The URL of the open pull request for the branch, or "". Closed and merged ones don't count."""
    gh = merged_env(root).get("UI_GH") or "gh"
    found = sh(root, [gh, "pr", "view", branch, "--json", "url,state"], emit, check=False)
    try:
        data = json.loads(found.stdout) if found.returncode == 0 else {}
    except ValueError:
        data = {}
    return data.get("url", "") if data.get("state") == "OPEN" else ""


def commit(root: Path, experiment_id: str, emit: Emit) -> dict:
    """Push first and move the local ref after, so a failed push or PR step can be run again."""
    info = prepare(root, experiment_id, emit)
    branch, parent = info["branch"], info["base"]
    sha = parent
    if info["files"]:
        sha = sh(root, ["git", "commit-tree", info["tree"], "-p", parent, "-m", f"Results: experiment {experiment_id}"],
                 emit).stdout.strip()
        sh(root, ["git", "push", "origin", f"{sha}:refs/heads/{branch}"], emit)
        sh(root, ["git", "update-ref", f"refs/heads/{branch}", sha], emit)
    elif info["ahead"]:  # the run's own commits are not on the remote yet
        sh(root, ["git", "push", "origin", f"{sha}:refs/heads/{branch}"], emit)
    url = open_pr_url(root, branch, emit)
    if url and not info["files"] and not info["ahead"]:
        raise ApiError(409, "nothing to commit")
    if not url:  # a retry after a failed PR step finds the branch already pushed
        config = load_experiment_config(root / "config" / "experiments" / f"{experiment_id}.toml")
        gh = merged_env(root).get("UI_GH") or "gh"
        made = sh(root, [gh, "pr", "create", "--base", "main", "--head", branch, "--title",
                         f"Results: experiment {experiment_id}", "--body", pr_body(config, experiment_id)], emit)
        url = made.stdout.strip().splitlines()[-1] if made.stdout.strip() else ""
    return {"branch": branch, "commit": sha, "pr_url": url}
