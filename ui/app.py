# Spec: docs/specs/ui.md
"""The UI's request logic: routes GET and POST paths to the bundle, experiments, jobs, and commit.
Holds the token, the job registry, and the in-memory bundles. A run gets its config on stdin, so
nothing here writes a config file. Key routes go to ui.secrets. Writes only through those modules.
"""

import re
import secrets
import time
from datetime import datetime
from pathlib import Path

from ui import commit as commit_module
from ui import experiments, forms
from ui import project
from ui import replay
from ui import secrets as key_store
from ui.bundle import Bundles
from ui.common import ApiError, check_id, merged_env
from ui.gitdata import GitData
from ui.jobs import Jobs

VERSION = re.compile(r"\d+\.\d+\.\d+")
BRANCH_WAIT_S = 30  # how long POST /api/run waits for `run` to create results/<id>


class App:
    def __init__(self, root: Path, static_dir: Path) -> None:
        self.root, self.static_dir = root, static_dir
        self.token = secrets.token_urlsafe(24)
        self.jobs = Jobs(root)
        self.bundles = Bundles(root, GitData(root))

    def evaluate(self, body: dict) -> dict:
        experiment_id = check_id(body.get("id"))
        args = ["src.evaluate.evaluate", "--experiment", experiment_id]
        release = body.get("release")
        if release is not None:
            if not isinstance(release, str) or not VERSION.fullmatch(release):
                raise ApiError(400, "field 'release' must be a version like 1.0.0, or null")
            args += ["--release", release]
        if not (self.root / "results" / experiment_id / "experiment.toml").is_file():
            raise ApiError(409, f"experiment {experiment_id} has no results in this checkout")
        self.jobs.start(experiment_id, [("evaluate", args)], blocked_by=("run:",))
        return {"id": experiment_id, "job": "evaluate"}

    def start_form(self, body: dict, name: str) -> dict:
        """estimate, dry-run, and run: the form (the body, or its `form` key) becomes the config on each job's stdin."""
        form = body["form"] if isinstance(body.get("form"), dict) else body
        experiment_id = check_id(form.get("id"))
        busy = any(state == "running" and (n.startswith("run:") or n == "evaluate")
                   for n, state in self.jobs.states(experiment_id).items())
        if name == "run" and busy:  # estimate and dry-run only read, so they refuse just their own repeat
            raise ApiError(409, f"a job of experiment {experiment_id} is running; stop it first")
        limit = body.get("limit") if name == "run" else None
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            raise ApiError(400, "field 'limit' must be a whole number of at least 1, or null")
        text = forms.config_text(self.bundles, form, merged_env(self.root))
        # The menu offers releases from main, but `run` reads the release from this checkout.
        release = form.get("release")
        if not (self.root / "releases" / str(release) / "manifest.json").is_file():
            raise ApiError(409, f"release {release} is on main but not in this checkout (releases/{release}/): "
                                "merge main into the checked-out branch, then restart the UI")
        status, text = forms.resolve_status(self.bundles, self.root, experiment_id, text)
        base = ["src.run.run", "--experiment", experiment_id, "--config", "-"]
        if name == "run":
            models = form["models"]
            names = [f"run:{m}" for m in models]
            extra = ["--limit", str(limit)] if limit is not None else []
            items = [(n, [*base, "--model", m, *extra]) for n, m in zip(names, models)]
        else:
            names, items = [name], [(name, [*base, "--estimate" if name == "estimate" else "--dry-run"])]
        self.jobs.start(experiment_id, items, blocked_by=("evaluate",) if name == "run" else (), stdin=text)
        if name == "run":
            self.wait_for_branch(experiment_id, names)
        return {"id": experiment_id, "status": status, "jobs": names}

    def wait_for_branch(self, experiment_id: str, names: list[str]) -> None:
        """Return once results/<id> exists, so the page it opens next can read it: a new experiment's comes from
        `run`'s first commit, and a resumed one may exist only on origin until `run` commits a record. When every
        run job ends first without any branch, the run failed before its first commit: report its last stderr line."""
        git = self.bundles.git
        exists = lambda: experiment_id in git.local_ids() or experiment_id in git.remote_ids()
        deadline = time.monotonic() + BRANCH_WAIT_S
        while time.monotonic() < deadline:
            if exists():
                return
            states = self.jobs.states(experiment_id)
            if not any(states.get(n) == "running" for n in names):
                if exists():
                    return
                line = next((t for t in (self.jobs.last_stderr(experiment_id, n) for n in names) if t), "no output")
                raise ApiError(409, f"run stopped before creating results/{experiment_id}: {line}")
            time.sleep(0.2)

    def project_job(self, name: str, args: list[str]) -> dict:
        """A job of no experiment. install, release, and push also refuse while any job is alive."""
        self.jobs.start("", [(name, args)], exclusive=name in ("install", "release"))
        return {"job": name}

    def release(self, body: dict) -> dict:
        bump, note = body.get("bump"), body.get("note")
        if bump not in ("major", "minor", "patch"):
            raise ApiError(400, "field 'bump' must be 'major', 'minor', or 'patch'")
        if not isinstance(note, str) or not note.strip():
            raise ApiError(400, "field 'note' must not be blank")
        project.check_branch(self.root)
        project.check_clean(self.root)
        return self.project_job("release", ["src.release.release", "--bump", bump, "--note", note.strip()])

    def push(self) -> dict:
        project.check_branch(self.root)
        (job,) = self.jobs.register("", ["push"], inline=True, exclusive=True)
        try:
            result = project.push(self.root, lambda s, t: self.jobs.say("", "push", s, t))
        except BaseException as error:
            self.jobs.say("", "push", "stderr", getattr(error, "message", str(error)))
            self.jobs.finish(job, 1)
            raise
        self.jobs.finish(job, 0)
        return result

    def guard_commit(self, experiment_id: str) -> None:
        if self.jobs.alive(experiment_id):
            raise ApiError(409, f"a job of experiment {experiment_id} is alive")

    def commit(self, body: dict) -> dict:
        experiment_id = check_id(body.get("id"))
        self.guard_commit(experiment_id)
        (job,) = self.jobs.register(experiment_id, ["commit"], inline=True)
        try:
            result = commit_module.commit(self.root, experiment_id, lambda s, t: self.jobs.say(experiment_id, "commit", s, t))
        except BaseException as error:
            self.jobs.say(experiment_id, "commit", "stderr", getattr(error, "message", str(error)))
            self.jobs.finish(job, 1)
            raise
        self.jobs.finish(job, 0)
        return result

    def get(self, path: str, query: dict) -> dict:
        parts = path.strip("/").split("/")
        live = self.jobs.ids()  # ids with any job here: read from the local branch
        if parts == ["api", "bundle"]:
            release = query.get("release", [None])[0]
            return self.bundles.get(release, query.get("refresh", ["0"])[0] == "1", live, merged_env(self.root),
                                    self.jobs.running_ids())
        if parts == ["api", "inputs"]:
            return self.bundles.inputs(query.get("release", [""])[0], query.get("puzzle", [""])[0])
        if parts == ["api", "branches"]:
            return self.bundles.branches()
        if parts == ["api", "default-id"]:
            names = {k: [n for n in query.get(k, [""])[0].split(",") if n] for k in ("models", "puzzles")}
            return {"id": experiments.default_id(names["models"], names["puzzles"], datetime.now())}
        if parts == ["api", "log"]:
            try:
                after = int(query.get("after", ["0"])[0])
            except ValueError:
                raise ApiError(400, "query 'after' must be a whole number") from None
            return self.jobs.log_since(after)
        if parts == ["api", "project"]:
            return project.info(self.root)
        if parts == ["api", "secrets"]:
            return key_store.inspect(self.root)
        if len(parts) == 4 and parts[:2] == ["api", "experiment"] and parts[3] == "config":
            return experiments.load_form(self.bundles, check_id(parts[2]))
        if len(parts) == 3 and parts[0] == "api":
            experiment_id = check_id(parts[2])
            if parts[1] == "experiments":
                return self.bundles.experiment(experiment_id, live, self.jobs.running_ids())
            if parts[1] == "state":
                return experiments.snapshot(self.bundles, experiment_id, live, self.jobs.states(experiment_id))
            if parts[1] == "replay":
                return replay.replay(self.bundles, experiment_id, live, query)
            if parts[1] == "commit":
                self.guard_commit(experiment_id)
                return commit_module.preview(self.root, experiment_id, lambda s, t: self.jobs.say(experiment_id, "commit", s, t))
        raise ApiError(404, "not found")

    def post(self, path: str, body: dict) -> dict:
        if path == "/api/secrets":
            provider = body.get("provider")
            if body.get("action") == "save":
                key_store.save(self.root, provider, body.get("api_key"))
            elif body.get("action") == "clear":
                key_store.clear(self.root, provider)
            else:
                raise ApiError(400, "field 'action' must be 'save' or 'clear'")
            return key_store.inspect(self.root)
        if path in ("/api/estimate", "/api/dry-run", "/api/run"):
            return self.start_form(body, path[len("/api/"):])
        if path == "/api/evaluate":
            return self.evaluate(body)
        if path == "/api/install":
            return self.project_job("install", ["pip", "install", "-e", ".[test]"])
        if path == "/api/tests":
            return self.project_job("tests", ["pytest", "-q", "-p", "no:cacheprovider"])
        if path == "/api/release":
            return self.release(body)
        if path == "/api/push":
            return self.push()
        if path == "/api/commit":
            return self.commit(body)
        if path == "/api/stop":
            experiment_id = check_id(body.get("id"))
            return {"id": experiment_id, "stopped": self.jobs.stop(experiment_id)}
        raise ApiError(404, "not found")
