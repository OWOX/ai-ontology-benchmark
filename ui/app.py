# Spec: docs/specs/ui.md
"""The UI's request logic: routes GET and POST paths to experiments, state, jobs, and commit.
Holds the token, the event hub, and the job manager. Writes only through those modules.
"""

import secrets
from pathlib import Path

from ui import commit as commit_module
from ui import experiments, state
from ui.common import ApiError, check_id, merged_env
from ui.jobs import Hub, JobManager


class App:
    def __init__(self, root: Path, static_dir: Path) -> None:
        self.root, self.static_dir = root, static_dir
        self.token = secrets.token_urlsafe(24)
        self.hub = Hub()
        self.jobs = JobManager(root, self.hub)

    def experiment_config(self, experiment_id: str) -> dict:
        return state.load_experiment(self.root, check_id(experiment_id))[0]

    def start_simple(self, body: dict, name: str, flag: list[str]) -> dict:
        experiment_id = check_id(body.get("id"))
        experiments.load_form(self.root, experiment_id)
        args = ["src.run.run", "--experiment", experiment_id, *flag] if name == "estimate" else \
            ["src.evaluate.evaluate", "--experiment", experiment_id]
        self.jobs.start(experiment_id, name, args, no_run=name == "evaluate")
        return {"id": experiment_id, "job": name}

    def run(self, body: dict) -> dict:
        experiment_id = check_id(body.get("id"))
        limit = body.get("limit")
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            raise ApiError(400, "field 'limit' must be a whole number of at least 1, or null")
        experiments.load_form(self.root, experiment_id)
        models = [m["name"] for m in self.experiment_config(experiment_id)["models"]]
        self.jobs.start_run(experiment_id, models, limit)
        return {"id": experiment_id, "jobs": [f"run:{m}" for m in models]}

    def guard_commit(self, experiment_id: str) -> None:
        if self.jobs.alive(experiment_id):
            raise ApiError(409, f"a job of experiment {experiment_id} is alive")

    def emitter(self, name: str):
        return lambda stream, text: self.jobs.terminal(name, stream, text)

    def commit(self, body: dict) -> dict:
        experiment_id = check_id(body.get("id"))
        self.guard_commit(experiment_id)
        job = self.jobs.begin_inline(experiment_id, "commit")
        try:
            result = commit_module.commit(self.root, experiment_id, self.emitter("commit"))
        except BaseException as error:
            self.jobs.terminal("commit", "stderr", getattr(error, "message", str(error)))
            self.jobs.finish(job, 1)
            raise
        self.jobs.finish(job, 0)
        return result

    def get(self, path: str) -> dict:
        parts = path.strip("/").split("/")
        if parts[:2] == ["api", "catalogue"] and len(parts) == 2:
            return experiments.catalogue(self.root, merged_env(self.root))
        if len(parts) == 3 and parts[0] == "api":
            experiment_id = check_id(parts[2])
            if parts[1] == "experiment":
                return experiments.load_form(self.root, experiment_id)
            if parts[1] == "state":
                return state.snapshot(self.root, experiment_id, self.jobs.states(experiment_id),
                                      self.jobs.alive_models(experiment_id))
            if parts[1] == "commit":
                self.guard_commit(experiment_id)
                return commit_module.preview(self.root, experiment_id, self.emitter("commit"))
        raise ApiError(404, "not found")

    def post(self, path: str, body: dict) -> dict:
        if path == "/api/experiment":
            return experiments.save_experiment(self.root, body, merged_env(self.root))
        if path == "/api/estimate":
            return self.start_simple(body, "estimate", ["--estimate"])
        if path == "/api/evaluate":
            return self.start_simple(body, "evaluate", [])
        if path == "/api/run":
            return self.run(body)
        if path == "/api/commit":
            return self.commit(body)
        if path == "/api/stop":
            experiment_id = check_id(body.get("id"))
            return {"id": experiment_id, "stopped": self.jobs.stop(experiment_id)}
        raise ApiError(404, "not found")
