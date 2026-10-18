# Spec: docs/specs/ui.md
"""Job registry, subprocess runner, raw-file tailer, and event broadcaster. Starts the existing
scripts as subprocesses and reads results/<id>/raw/*.jsonl. Writes nothing itself.
"""

import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from ui.common import ApiError, merged_env
from ui.events import Hub, Job, Tailer
from ui.state import in_progress, slim

BUDGET_PREFIX = "error: budget reached:"
STAGE_WAIT_S = 10.0


class JobManager:
    def __init__(self, root: Path, hub: Hub) -> None:
        self.root, self.hub = root, hub
        self.lock = threading.Lock()
        self.jobs: dict[tuple[str, str], Job] = {}
        self.tailers: dict[str, Tailer] = {}
        self.tailing: set[str] = set()
        self.staging: dict[str, threading.Event] = {}

    # --- queries
    def states(self, experiment_id: str) -> dict:
        with self.lock:
            return {j.name: j.state for j in self.jobs.values() if j.experiment_id == experiment_id}

    def alive(self, experiment_id: str, run_only: bool = False) -> bool:
        with self.lock:
            return self._alive(experiment_id, run_only)

    def _alive(self, experiment_id: str, run_only: bool = False) -> bool:
        if run_only and experiment_id in self.staging:
            return True
        return any(j.state == "running" and (not run_only or j.name.startswith("run:"))
                   for j in self.jobs.values() if j.experiment_id == experiment_id)

    def alive_models(self, experiment_id: str) -> set[str]:
        with self.lock:
            return {j.name[4:] for j in self.jobs.values()
                    if j.experiment_id == experiment_id and j.state == "running" and j.name.startswith("run:")}

    # --- events
    def terminal(self, name: str, stream: str, text: str) -> None:
        self.hub.publish("terminal", {"job": name, "stream": stream, "text": text})

    def _job_event(self, job: Job) -> None:
        self.hub.publish("job", {"id": job.experiment_id, "job": job.name, "state": job.state, "code": job.code})

    def _register(self, experiment_id: str, name: str) -> Job:
        with self.lock:
            old = self.jobs.get((experiment_id, name))
            if old and old.state == "running":
                raise ApiError(409, f"job {name} of experiment {experiment_id} is already running")
            job = self.jobs[(experiment_id, name)] = Job(experiment_id, name)
        return job

    # --- subprocess jobs
    def start(self, experiment_id: str, name: str, module_args: list[str]) -> Job:
        job = self._register(experiment_id, name)
        argv = [sys.executable, "-u", "-m", *module_args]
        self.terminal(name, "cmd", shlex.join(argv))
        try:
            job.proc = subprocess.Popen(argv, cwd=self.root, env=merged_env(self.root), text=True,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, bufsize=1)
        except OSError as error:
            self.terminal(name, "stderr", str(error))
            self.finish(job, 1)
            return job
        self._job_event(job)
        readers = [threading.Thread(target=self._read, args=(job, s), daemon=True) for s in ("stdout", "stderr")]
        for reader in readers:
            reader.start()
        threading.Thread(target=self._wait, args=(job, readers), daemon=True).start()
        return job

    def _read(self, job: Job, stream: str) -> None:
        for line in getattr(job.proc, stream):
            text = line.rstrip("\r\n")
            if stream == "stderr":
                job.last_stderr = text
                if text.startswith(BUDGET_PREFIX):
                    job.budget = True
            self.terminal(job.name, stream, text)

    def _wait(self, job: Job, readers: list) -> None:
        code = job.proc.wait()
        for reader in readers:
            reader.join()
        if job.name.startswith("run:"):
            self.flush(job.experiment_id, job.name[4:])
        self.finish(job, code)

    def finish(self, job: Job, code: int) -> None:
        job.code = code if code in (0, 1) else None
        job.state = "stopped" if job.stopped else "done" if code == 0 else "budget" if (code == 1 and job.budget) else "failed"
        self._job_event(job)

    # --- inline jobs (commit)
    def begin_inline(self, experiment_id: str, name: str) -> Job:
        job = self._register(experiment_id, name)
        self._job_event(job)
        return job

    # --- run jobs
    def start_run(self, experiment_id: str, models: list[str], limit: int | None) -> None:
        with self.lock:
            if self._alive(experiment_id, run_only=True):
                raise ApiError(409, f"a run job of experiment {experiment_id} is already running")
            cancel = threading.Event()
            if len(models) > 1:  # staging counts as alive only while other models wait to start
                self.staging[experiment_id] = cancel
        self._tail(experiment_id)

        def args(model: str) -> list[str]:
            extra = ["--limit", str(limit)] if limit is not None else []
            return ["src.run.run", "--experiment", experiment_id, "--model", model, *extra]

        try:
            first = self.start(experiment_id, f"run:{models[0]}", args(models[0]))
        except BaseException:
            self.staging.pop(experiment_id, None)
            raise
        if len(models) > 1:
            threading.Thread(target=self._stage, args=(experiment_id, first, models[1:], args, cancel),
                             daemon=True).start()

    def _stage(self, experiment_id: str, first: Job, rest: list[str], args, cancel: threading.Event) -> None:
        config = self.root / "config" / "experiments" / f"{experiment_id}.toml"
        copy = self.root / "results" / experiment_id / "experiment.toml"
        deadline = time.monotonic() + STAGE_WAIT_S
        while time.monotonic() < deadline and first.state == "running" and not cancel.is_set():
            if copy.is_file() and config.is_file() and copy.read_bytes() == config.read_bytes():
                break
            time.sleep(0.05)
        try:
            for model in rest:
                if not cancel.is_set():
                    self.start(experiment_id, f"run:{model}", args(model))
        except ApiError:
            pass
        finally:
            with self.lock:
                self.staging.pop(experiment_id, None)

    # --- stop
    def stop(self, experiment_id: str) -> list[str]:
        with self.lock:
            event = self.staging.get(experiment_id)
            live = [j for j in self.jobs.values() if j.experiment_id == experiment_id
                    and j.state == "running" and j.name.startswith("run:") and j.proc]
        if event:
            event.set()
        for job in live:
            job.stopped = True
            self._signal(job, signal.SIGINT)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(j.proc.poll() is None for j in live):
            time.sleep(0.05)
        for job in live:
            if job.proc.poll() is None:
                self._signal(job, signal.SIGTERM)
        return [j.name for j in live]

    @staticmethod
    def _signal(job: Job, sig: int) -> None:
        try:
            job.proc.send_signal(sig)
        except ProcessLookupError:
            pass

    # --- live records
    def _tail(self, experiment_id: str) -> None:
        with self.lock:
            if experiment_id in self.tailing:
                return
            self.tailing.add(experiment_id)
            fresh = experiment_id not in self.tailers
            tailer = self.tailers.setdefault(experiment_id, Tailer(self.root / "results" / experiment_id / "raw"))
        if fresh:
            tailer.poll()  # records from earlier runs are in the snapshot, not events
        threading.Thread(target=self._tail_loop, args=(experiment_id, tailer), daemon=True).start()

    def _tail_loop(self, experiment_id: str, tailer: Tailer) -> None:
        while True:
            with self.lock:
                if not self._alive(experiment_id, run_only=True):
                    self.tailing.discard(experiment_id)
                    return
            self.emit_new(experiment_id, tailer)
            time.sleep(0.5)

    def emit_new(self, experiment_id: str, tailer: Tailer) -> None:
        models = set()
        for record in tailer.poll():
            self.hub.publish("record", {"id": experiment_id, "record": slim(record)})
            models.add(record.get("model"))
        for model in sorted(m for m in models if m):
            self.publish_progress(experiment_id, model)

    def publish_progress(self, experiment_id: str, model: str) -> None:
        try:
            attempt = in_progress(self.root, experiment_id, model) if model in self.alive_models(experiment_id) else None
        except (ApiError, ValueError, OSError):
            attempt = None
        self.hub.publish("in_progress", {"id": experiment_id, "model": model, "attempt": attempt})

    def flush(self, experiment_id: str, model: str) -> None:
        """After a run job exits: one last poll, then its in_progress, which is now null."""
        tailer = self.tailers.get(experiment_id)
        if tailer:
            self.emit_new(experiment_id, tailer)
        self.hub.publish("in_progress", {"id": experiment_id, "model": model, "attempt": None})
