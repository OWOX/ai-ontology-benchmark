# Spec: docs/specs/ui.md
"""Project-level facts and the push job. Reads git state, the releases folder, and the
installed packages (find_spec, no import). Writes by running git push and gh pr create.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

from src.release.release import latest_version
from ui.commit import Emit, create_pr, gh_binary, open_pr_url, sh
from ui.common import ApiError

PACKAGES = {"anthropic": "anthropic", "openai": "openai", "google-genai": "google.genai", "pytest": "pytest"}


def current_branch(root: Path) -> str:
    out = sh(root, ["git", "rev-parse", "--abbrev-ref", "HEAD"], lambda s, t: None, check=False)
    return out.stdout.strip() if out.returncode == 0 else ""


def check_branch(root: Path) -> str:
    """The branch a release or push may use. 409 on main or a detached HEAD."""
    branch = current_branch(root)
    if branch in ("main", "HEAD", ""):
        raise ApiError(409, f"release and push need a branch other than main (now: {branch or 'none'})")
    return branch


def check_clean(root: Path) -> None:
    """409 naming the changed paths, because release commits and fails on a dirty tree."""
    out = sh(root, ["git", "status", "--porcelain"], lambda s, t: None)
    paths = [line[3:] for line in out.stdout.splitlines()]
    if paths:
        more = f", and {len(paths) - 10} more" if len(paths) > 10 else ""
        raise ApiError(409, f"commit or remove these first: {', '.join(paths[:10])}{more}")


def installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def info(root: Path) -> dict:
    quiet = lambda s, t: None  # noqa: E731
    status = sh(root, ["git", "status", "--porcelain"], quiet, check=False)
    return {"branch": current_branch(root), "clean": status.returncode == 0 and not status.stdout.strip(),
            "latest_release": latest_version(root / "releases"), "python": sys.version.split()[0],
            "packages": {name: installed(module) for name, module in PACKAGES.items()},
            "gh": shutil.which(gh_binary(root)) is not None}


def push(root: Path, emit: Emit) -> dict:
    """Push the branch and the tags, then return the open pull request or make one."""
    branch = check_branch(root)
    sh(root, ["git", "push", "-u", "origin", branch], emit)
    tags = sh(root, ["git", "tag", "--merged", branch, "--list", "release-*"], emit).stdout.split()
    if tags:
        sh(root, ["git", "push", "origin", *tags], emit)
    url = open_pr_url(root, branch, emit)
    if not url:
        url = create_pr(root, emit, "--head", branch, "--fill")
    return {"branch": branch, "pr_url": url}
