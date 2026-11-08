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

    def tree_sha(self, ref: str, path: str) -> str | None:
        """The sha of a folder at a ref, so a cache can outlive pushes that leave the folder alone."""
        done = self._git("rev-parse", "--verify", "--quiet", f"{ref}:{path}")
        return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None

    def ls(self, ref: str, path: str) -> list[str]:
        done = self._git("ls-tree", "--name-only", ref, path.rstrip("/") + "/")
        if done.returncode != 0:
            return []
        return [line.rsplit("/", 1)[-1] for line in done.stdout.splitlines() if line]

    def _ids(self, prefix: str) -> set[str]:
        done = self._git("for-each-ref", "--format=%(refname)", prefix)
        return {line[len(prefix):] for line in done.stdout.splitlines() if line.startswith(prefix)}

    def results_state(self) -> tuple[str | None, dict[str, str], dict[str, tuple[str, str]]]:
        """(main sha, local result shas by experiment id, pushed experiments), from one `git for-each-ref`, plus two
        `git ls-tree` calls for the folders on main. The main sha is that of `main_ref()`, which takes a second call
        only when the repo has no `origin/main`. The pushed experiments are `{id: (ref, key)}`: a `results/<id>`
        folder on main (key: the sha of the folder), overridden by an `origin/results/<id>` branch (key: its sha)."""
        done = self._git("for-each-ref", "--format=%(objectname) %(refname)", LOCAL_RESULTS, REMOTE_RESULTS,
                         "refs/remotes/origin/main")
        local, remote, main = {}, {}, None
        for line in done.stdout.splitlines():
            sha, _, name = line.partition(" ")
            if name == "refs/remotes/origin/main":
                main = sha
            elif name.startswith(REMOTE_RESULTS):
                remote[name[len(REMOTE_RESULTS):]] = sha
            elif name.startswith(LOCAL_RESULTS):
                local[name[len(LOCAL_RESULTS):]] = sha
        main_ref = "refs/remotes/origin/main" if main else "HEAD"
        pushed = {i: (main_ref, key) for i, key in self.main_results(main_ref).items()}
        pushed.update({i: (REMOTE_RESULTS + i, sha) for i, sha in remote.items()})
        return main or self.sha("HEAD"), local, pushed

    def main_results(self, ref: str | None = None) -> dict[str, str]:
        """The experiments on main: the sha of each `results/<id>` folder that holds an `experiment.toml`, by id."""
        ref = ref or self.main_ref()
        folders = self._git("ls-tree", ref, "results/")
        if folders.returncode != 0:
            return {}
        trees = {}
        for line in folders.stdout.splitlines():
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) == 3 and parts[1] == "tree":
                trees[path.rsplit("/", 1)[-1]] = parts[2]
        if not trees:
            return {}
        names = self._git("ls-tree", "-r", "--name-only", ref, "results/").stdout.splitlines()
        held = {n.split("/")[1] for n in names if n.count("/") == 2 and n.endswith("/experiment.toml")}
        return {i: sha for i, sha in trees.items() if i in held}

    def local_ids(self) -> set[str]:
        return self._ids(LOCAL_RESULTS)

    def remote_ids(self) -> set[str]:
        return self._ids(REMOTE_RESULTS)

    def pushed_ids(self) -> set[str]:
        """The ids of the experiments on origin: branches and folders on main."""
        return self.remote_ids() | set(self.main_results())

    def results_index(self, local_ids: set[str] = frozenset()) -> dict[str, tuple[str, str]]:
        """`{id: (ref, key)}` of the pushed experiments, with a local branch in place of the pushed one for each id in
        `local_ids` that has one. The key is the sha that changes when the experiment does."""
        _, local, index = self.results_state()
        for i in local_ids:
            if i in local:
                index[i] = (LOCAL_RESULTS + i, local[i])
        return index

    def results_refs(self, local_ids: set[str] = frozenset()) -> dict[str, str]:
        return {i: ref for i, (ref, _) in self.results_index(local_ids).items()}

    def github(self) -> str | None:
        if not self._github_read:
            done = self._git("remote", "get-url", "origin")
            found = re.fullmatch(GITHUB_URL, done.stdout.strip()) if done.returncode == 0 else None
            self._github = f"https://github.com/{found.group(1)}/{found.group(2)}" if found else None
            self._github_read = True
        return self._github
