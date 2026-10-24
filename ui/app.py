# Spec: docs/specs/ui.md
"""The UI's request logic: routes GET and POST paths to experiments, jobs, and commit.
Holds the token and the job registry. Key routes go to ui.secrets. Writes only through those modules.
"""

import re
import secrets
from pathlib import Path

from ui import commit as commit_module
from ui import experiments
from ui import project
from ui import replay
from ui import secrets as key_store
from ui.common import ApiError, check_id, merged_env
from ui.jobs import Jobs

VERSION = re.compile(r"\d+\.\d+\.\d+")


class App:
    def __init__(self, root: Path, static_dir: Path) -> None:
        self.root, self.static_dir = root, static_dir
        self.token = secrets.token_urlsafe(24)
        self.jobs = Jobs(root)

    def start_simple(self, body: dict, name: str) -> dict:
        experiment_id = check_id(body.get("id"))
        experiments.load_config(self.root, experiment_id)
        args, blocked = ["src.run.run", "--experiment", experiment_id], ()
        if name == "estimate":
            args.append("--estimate")
        elif name == "dry-run":
            args.append("--dry-run")
        else:
            args, blocked = ["src.evaluate.evaluate", "--experiment", experiment_id], ("run:",)
            release = body.get("release")
            if release is not None:
                if not isinstance(release, str) or not VERSION.fullmatch(release):
                    raise ApiError(400, "field 'release' must be a version like 1.0.0, or null")
                args += ["--release", release]
        self.jobs.start(experiment_id, [(name, args)], blocked_by=blocked)
        return {"id": experiment_id, "job": name}

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
            result = project.push(self.root, lambda s, t: self.jobs.say("push", s, t))
        except BaseException as error:
            self.jobs.say("push", "stderr", getattr(error, "message", str(error)))
            self.jobs.finish(job, 1)
            raise
        self.jobs.finish(job, 0)
        return result

    def run(self, body: dict) -> dict:
        experiment_id = check_id(body.get("id"))
        limit = body.get("limit")
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            raise ApiError(400, "field 'limit' must be a whole number of at least 1, or null")
        models = [m["name"] for m in experiments.load_config(self.root, experiment_id)["models"]]
        extra = ["--limit", str(limit)] if limit is not None else []
        self.jobs.start(experiment_id, [(f"run:{m}", ["src.run.run", "--experiment", experiment_id,
                                                      "--model", m, *extra]) for m in models],
                        blocked_by=("evaluate",))
        return {"id": experiment_id, "jobs": [f"run:{m}" for m in models]}

    def guard_commit(self, experiment_id: str) -> None:
        if self.jobs.alive(experiment_id):
            raise ApiError(409, f"a job of experiment {experiment_id} is alive")

    def commit(self, body: dict) -> dict:
        experiment_id = check_id(body.get("id"))
        self.guard_commit(experiment_id)
        (job,) = self.jobs.register(experiment_id, ["commit"], inline=True)
        try:
            result = commit_module.commit(self.root, experiment_id, lambda s, t: self.jobs.say("commit", s, t))
        except BaseException as error:
            self.jobs.say("commit", "stderr", getattr(error, "message", str(error)))
            self.jobs.finish(job, 1)
            raise
        self.jobs.finish(job, 0)
        return result

    def get(self, path: str, query: dict) -> dict:
        parts = path.strip("/").split("/")
        if parts == ["api", "catalogue"]:
            return experiments.catalogue(self.root, merged_env(self.root))
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
        if len(parts) == 3 and parts[0] == "api":
            experiment_id = check_id(parts[2])
            if parts[1] == "experiment":
                return experiments.load_form(self.root, experiment_id)
            if parts[1] == "state":
                return experiments.snapshot(self.root, experiment_id, self.jobs.states(experiment_id))
            if parts[1] == "replay":
                return replay.replay(self.root, experiment_id, query)
            if parts[1] == "commit":
                self.guard_commit(experiment_id)
                return commit_module.preview(self.root, experiment_id, lambda s, t: self.jobs.say("commit", s, t))
        raise ApiError(404, "not found")

    def post(self, path: str, body: dict) -> dict:
        if path == "/api/experiment":
            experiment_id = body.get("id")
            if isinstance(experiment_id, str) and self.jobs.alive(experiment_id):
                raise ApiError(409, f"a job of experiment {experiment_id} is running; stop it first")
            return experiments.save_experiment(self.root, body, merged_env(self.root))
        if path == "/api/secrets":
            provider = body.get("provider")
            if body.get("action") == "save":
                key_store.save(self.root, provider, body.get("api_key"))
            elif body.get("action") == "clear":
                key_store.clear(self.root, provider)
            else:
                raise ApiError(400, "field 'action' must be 'save' or 'clear'")
            return key_store.inspect(self.root)
        if path == "/api/secrets/import":
            return {"saved": key_store.import_text(self.root, body.get("text"))}
        if path == "/api/estimate":
            return self.start_simple(body, "estimate")
        if path == "/api/evaluate":
            return self.start_simple(body, "evaluate")
        if path == "/api/dry-run":
            return self.start_simple(body, "dry-run")
        if path == "/api/install":
            return self.project_job("install", ["pip", "install", "-e", ".[test]"])
        if path == "/api/tests":
            return self.project_job("tests", ["pytest", "-q", "-p", "no:cacheprovider"])
        if path == "/api/release":
            return self.release(body)
        if path == "/api/push":
            return self.push()
        if path == "/api/run":
            return self.run(body)
        if path == "/api/commit":
            return self.commit(body)
        if path == "/api/stop":
            experiment_id = check_id(body.get("id"))
            return {"id": experiment_id, "stopped": self.jobs.stop(experiment_id)}
        raise ApiError(404, "not found")
