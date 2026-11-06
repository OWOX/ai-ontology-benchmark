# Spec: docs/specs/ui.md
"""Reads the repo through git refs, never the work tree. Runs `git fetch` (throttled), `git show`,
`git ls-tree`, `git rev-parse`, `git for-each-ref`, and `git remote get-url`. Writes only the
remote-tracking refs that `git fetch` updates.
"""

import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

GIT_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
FETCH_TIMEOUT_S = 60
FETCH_INTERVAL_S = 30
REMOTE_RESULTS = "refs/remotes/origin/results/"
LOCAL_RESULTS = "refs/heads/results/"
GITHUB_URL = r"(?:https://github\.com/|git@github\.com:)([^/]+)/(.+?)(?:\.git)?/?"


class GitData:
    def __init__(self, root: Path, clock=time.monotonic) -> None:
        self.root = Path(root)
        self.clock = clock
        self.fetched_at: str | None = None
        self.fetch_error: str | None = None
        self._last_fetch: float | None = None
        self._github: str | None = None
        self._github_read = False

    def _git(self, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in GIT_VARIABLES}
        env["GIT_TERMINAL_PROMPT"] = "0"
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, env=env, timeout=timeout)

    def fetch(self, force: bool = False) -> None:
        now = self.clock()
        if not force and self._last_fetch is not None and now - self._last_fetch < FETCH_INTERVAL_S:
            return
        self._last_fetch = now
        try:
            if self._git("remote", "get-url", "origin").returncode != 0:
                self.fetch_error = "no remote origin"
                return
            done = self._git("fetch", "--prune", "origin", "main",
                             "+refs/heads/results/*:refs/remotes/origin/results/*", timeout=FETCH_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as error:
            self.fetch_error = str(error).strip() or "fetch failed"
            return
        if done.returncode != 0:
            self.fetch_error = done.stderr.strip() or "fetch failed"
            return
        self.fetch_error = None
        self.fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def main_ref(self) -> str:
        return "refs/remotes/origin/main" if self.sha("refs/remotes/origin/main") else "HEAD"

    def sha(self, ref: str) -> str | None:
        done = self._git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None

    def show(self, ref: str, path: str) -> str | None:
        done = self._git("show", f"{ref}:{path}")
        return done.stdout if done.returncode == 0 else None

    def ls(self, ref: str, path: str) -> list[str]:
        done = self._git("ls-tree", "--name-only", ref, path.rstrip("/") + "/")
        if done.returncode != 0:
            return []
        return [line.rsplit("/", 1)[-1] for line in done.stdout.splitlines() if line]

    def _ids(self, prefix: str) -> set[str]:
        done = self._git("for-each-ref", "--format=%(refname)", prefix)
        return {line[len(prefix):] for line in done.stdout.splitlines() if line.startswith(prefix)}

    def local_ids(self) -> set[str]:
        return self._ids(LOCAL_RESULTS)

    def remote_ids(self) -> set[str]:
        return self._ids(REMOTE_RESULTS)

    def results_refs(self, local_ids: set[str] = frozenset()) -> dict[str, str]:
        local = self.local_ids()
        refs = {i: REMOTE_RESULTS + i for i in self.remote_ids()}
        for i in local_ids:
            if i in local:
                refs[i] = LOCAL_RESULTS + i
        return refs

    def github(self) -> str | None:
        if not self._github_read:
            done = self._git("remote", "get-url", "origin")
            found = re.fullmatch(GITHUB_URL, done.stdout.strip()) if done.returncode == 0 else None
            self._github = f"https://github.com/{found.group(1)}/{found.group(2)}" if found else None
            self._github_read = True
        return self._github
