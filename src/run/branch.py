# Spec: docs/specs/run.md
"""Commits the experiment's config and raw records to the local branch results/<ID> while `run`
works, and pushes that branch once at exit. Reads the config file (none when the config came from stdin) and results/<ID>/. Writes git
objects, refs/heads/results/<ID>, and a lock file in the git common dir. Never touches the work
tree, the real index, or HEAD: it builds each tree in a temporary index file.
"""

import fcntl
import os
import subprocess
import tempfile
from pathlib import Path

GIT_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
NETWORK_TIMEOUT_S = 60  # a credential prompt or a hung network must not block the run or its exit


class BranchError(Exception):
    """A checked error. The message says what git refused."""


class ResultsBranch:
    def __init__(self, config_path: Path | None, results_dir: Path, experiment_id: str):
        self.branch = f"results/{experiment_id}"
        self.ref = f"refs/heads/{self.branch}"
        self.env = {k: v for k, v in os.environ.items() if k not in GIT_VARIABLES}
        found = self.git(["rev-parse", "--show-toplevel"], cwd=Path.cwd(), check=False)
        if found.returncode != 0:
            raise BranchError("run needs a git work tree, because results always go to a branch "
                              f"(results/{experiment_id}); use --no-commit to skip it")
        self.root = Path(found.stdout.strip()).resolve()
        self.paths = ([self.relative(config_path)] if config_path else []) + [self.relative(results_dir)]
        common = self.git(["rev-parse", "--git-common-dir"]).stdout.strip()
        self.lock_path = (self.root / common) / f"results-{experiment_id}.lock"
        self.exclude = f":(exclude){self.paths[-1]}/.experiment.toml.*.tmp"  # a run's temporary copy
        self.sync()

    def relative(self, path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.root))
        except ValueError:
            raise BranchError(f"{path}: is outside the git work tree {self.root}") from None

    def git(self, argv: list[str], cwd: Path | None = None, env: dict | None = None, check: bool = True,
            timeout: float | None = None):
        extra = {"GIT_TERMINAL_PROMPT": "0"} if timeout else {}
        try:
            result = subprocess.run(["git", *argv], cwd=cwd or self.root, env={**self.env, **extra, **(env or {})},
                                    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(argv, 124, "", f"timed out after {timeout} s")
        if check and result.returncode != 0:
            raise BranchError(f"git {argv[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
        return result

    def resolve(self, ref: str) -> str | None:
        found = self.git(["rev-parse", "--verify", "-q", ref], check=False)
        return found.stdout.strip() if found.returncode == 0 else None

    def is_ancestor(self, old: str, new: str) -> bool:
        return self.git(["merge-base", "--is-ancestor", old, new], check=False).returncode == 0

    def sync(self) -> None:
        """Fetch origin's branch, then bring the local branch level with it. Diverged is an error."""
        remote_ref = f"refs/remotes/origin/{self.branch}"
        with open(self.lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.git(["fetch", "origin", f"+refs/heads/{self.branch}:{remote_ref}"], check=False,
                     timeout=NETWORK_TIMEOUT_S)  # fails quietly: no origin, or no branch there yet
            local, remote = self.resolve(self.ref), self.resolve(remote_ref)
            if not (local and remote) or local == remote or self.is_ancestor(remote, local):
                return  # a missing local branch builds on the remote one in commit()
            if self.is_ancestor(local, remote):
                self.git(["update-ref", self.ref, remote, local])
                return
            raise BranchError(f"{self.ref} and {remote_ref} have diverged; reconcile them before running")

    def commit(self, message: str) -> None:
        """Add the config and results to the branch as one commit. Does nothing if nothing changed."""
        with open(self.lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # parallel --model processes share the branch
            old = self.resolve(self.ref)
            parent = old or self.resolve(f"refs/remotes/origin/{self.branch}") \
                or self.resolve("refs/remotes/origin/main") or self.resolve("HEAD")
            if parent is None:
                raise BranchError("git has no commit to start the branch from")
            with tempfile.TemporaryDirectory() as folder:
                index = {"GIT_INDEX_FILE": os.path.join(folder, "index")}
                self.git(["read-tree", parent], env=index)
                self.git(["add", "--ignore-removal", "--", *self.paths, self.exclude], env=index)
                tree = self.git(["write-tree"], env=index).stdout.strip()
            if tree == self.git(["rev-parse", f"{parent}^{{tree}}"]).stdout.strip():
                return
            new = self.git(["commit-tree", tree, "-p", parent, "-m", message]).stdout.strip()
            self.git(["update-ref", self.ref, new, old or ""])

    def push(self) -> str | None:
        """Push the branch tip to origin, under the lock. Return None on success, else the reason. Never raises."""
        try:
            with open(self.lock_path, "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if self.git(["remote", "get-url", "origin"], check=False).returncode != 0:
                    return "no remote origin"
                tip = self.resolve(self.ref)
                if tip is None:
                    return None
                pushed = self.git(["push", "origin", f"{tip}:refs/heads/{self.branch}"], check=False,
                                  timeout=NETWORK_TIMEOUT_S)
                if pushed.returncode != 0:
                    return pushed.stderr.strip() or pushed.stdout.strip() or "git push failed"
        except (OSError, BranchError) as error:
            return str(error)
        return None

    def gc(self) -> None:
        self.git(["gc", "--auto", "--quiet"], check=False)
