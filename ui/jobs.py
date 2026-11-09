# Spec: docs/specs/ui.md
"""Job registry and subprocess runner, with the in-memory terminal log. Starts the existing
scripts as subprocesses. Reads their output pipes; writes nothing to disk.
"""

import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from ui.common import ApiError, merged_env

BUDGET_PREFIX = "error: budget reached:"
LOG_CAP = 5000
STOP_WAIT_S = 10.0


class Job:
    def __init__(self, experiment_id: str, name: str, inline: bool = False, exclusive: bool = False) -> None:
        self.experiment_id, self.name, self.inline, self.exclusive = experiment_id, name, inline, exclusive
        self.state, self.code = "running", None
        self.proc: subprocess.Popen | None = None
        self.stopped = self.budget = False
        self.parallel = 1  # `run --parallel N`, 1 for a job not started with it
        self.followers: list["Job"] = []  # jobs that share this job's process and end with it


class Jobs:
    """Every job of this server, and the last LOG_CAP terminal lines. A job belongs to an
    experiment id; a job that belongs to none uses the id "".
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.Lock()
        self.jobs: dict[tuple[str, str], Job] = {}
        self.log: list[dict] = []
        self.seq = 0

    # --- queries
    def states(self, experiment_id: str) -> dict:
        with self.lock:
            return {j.name: j.state for j in self.jobs.values() if j.experiment_id == experiment_id}

    def parallels(self, experiment_id: str) -> dict:
        """The `--parallel` value of each running run job of the experiment, by AI model name."""
        with self.lock:
            return {j.name[len("run:"):]: j.parallel for j in self.jobs.values()
                    if j.experiment_id == experiment_id and j.state == "running" and j.name.startswith("run:")}

    def ids(self) -> set[str]:
        """Experiment ids with any job registered in this server, alive or over."""
        with self.lock:
            return {j.experiment_id for j in self.jobs.values() if j.experiment_id}

    def running_ids(self) -> set[str]:
        """Experiment ids with a run job alive."""
        with self.lock:
            return {j.experiment_id for j in self.jobs.values() if j.state == "running" and j.name.startswith("run:")}

    def alive(self, experiment_id: str) -> bool:
        return "running" in self.states(experiment_id).values()

    def last_stderr(self, experiment_id: str, name: str) -> str | None:
        """The last stderr line a job of the experiment wrote, while it is still in the log."""
        with self.lock:
            return next((line["text"] for line in reversed(self.log) if line["id"] == experiment_id
                         and line["job"] == name and line["stream"] == "stderr"), None)

    def log_since(self, after: int) -> dict:
        with self.lock:
            return {"lines": [line for line in self.log if line["seq"] > after], "last": self.seq,
                    "jobs": [{"id": j.experiment_id, "job": j.name, "state": j.state, "code": j.code}
                             for j in self.jobs.values()]}

    # --- log
    def say(self, experiment_id: str, name: str, stream: str, text: str) -> None:
        with self.lock:
            self.seq += 1
            self.log.append({"seq": self.seq, "id": experiment_id, "job": name, "stream": stream, "text": text})
            del self.log[:-LOG_CAP]

    # --- start and finish
    def register(self, experiment_id: str, names: list[str], blocked_by: tuple = (), inline: bool = False,
                 exclusive: bool = False) -> list[Job]:
        """Register running jobs. The checks and the inserts happen under one lock hold.
        An exclusive job is refused while any job of any experiment is running."""
        with self.lock:
            running = [j for j in self.jobs.values() if j.state == "running"]
            if running and (exclusive or any(j.exclusive for j in running)):
                raise ApiError(409, f"job {running[0].name} is running; wait for it or stop it first")
            mine = [j for j in self.jobs.values() if j.experiment_id == experiment_id and j.state == "running"]
            for job in mine:
                if job.name in names:
                    raise ApiError(409, f"job {job.name} of experiment {experiment_id} is already running")
                if job.name.startswith(blocked_by):
                    raise ApiError(409, f"job {job.name} of experiment {experiment_id} is alive")
            made = [Job(experiment_id, name, inline, exclusive) for name in names]
            for job in made:
                self.jobs[(experiment_id, job.name)] = job
        return made

    def start(self, experiment_id: str, items: list[tuple[str, list[str]]], blocked_by: tuple = (),
              exclusive: bool = False, stdin: str | None = None, parallel: int = 1, shared: bool = False) -> None:
        """Start one subprocess job per (name, `python -m` arguments). All register together.
        `stdin` is written to each process and closed, so a config can go in without a file.
        `parallel` is remembered on each job, so the page can tell how many attempts are in flight.
        `shared` starts one process, with the arguments of the first item, for all the names: the first job
        owns it, and the others show its state, so each AI model still has a job of its own on the page."""
        jobs = self.register(experiment_id, [n for n, _ in items], blocked_by, exclusive=exclusive)
        for job in jobs:
            job.parallel = parallel
        if shared:
            jobs[0].followers = jobs[1:]
            jobs, items = jobs[:1], items[:1]
        for job, (_, module_args) in zip(jobs, items):
            self._spawn(job, [sys.executable, "-u", "-m", *module_args], stdin)

    def _spawn(self, job: Job, argv: list[str], stdin: str | None = None) -> None:
        self.say(job.experiment_id, job.name, "cmd", shlex.join(argv))
        try:
            job.proc = subprocess.Popen(argv, cwd=self.root, env=merged_env(self.root), text=True,
                                        encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1)
        except OSError as error:
            self.say(job.experiment_id, job.name, "stderr", str(error))
            self.finish(job, 1)
            return
        if stdin is not None:
            try:
                job.proc.stdin.write(stdin)
                job.proc.stdin.close()
            except OSError:
                pass  # the process exited early; its own error and exit code say why
        if job.stopped:  # Stop arrived before the process existed
            self._signal(job, signal.SIGINT)
        readers = [threading.Thread(target=self._read, args=(job, s), daemon=True) for s in ("stdout", "stderr")]
        for reader in readers:
            reader.start()
        threading.Thread(target=self._wait, args=(job, readers), daemon=True).start()

    def _read(self, job: Job, stream: str) -> None:
        try:
            for line in getattr(job.proc, stream):
                text = line.rstrip("\r\n")
                if stream == "stderr" and text.startswith(BUDGET_PREFIX):
                    job.budget = True
                self.say(job.experiment_id, job.name, stream, text)
        except (ValueError, OSError):
            pass  # the pipe closed under us; the waiter reports the exit

    def _wait(self, job: Job, readers: list) -> None:
        code = job.proc.wait()
        for reader in readers:
            reader.join()
        self.finish(job, code)

    def finish(self, job: Job, code: int) -> None:
        with self.lock:
            for each in (job, *job.followers):
                each.code = code if code in (0, 1) else None
                each.state = ("stopped" if each.stopped else "done" if code == 0
                              else "budget" if (code == 1 and job.budget) else "failed")

    # --- stop
    def stop(self, experiment_id: str) -> list[str]:
        """Stop the live run jobs of one experiment."""
        return self._stop(lambda j: j.experiment_id == experiment_id and j.name.startswith("run:"))

    def stop_all(self) -> list[str]:
        """Stop every live subprocess job, so none outlives the server."""
        return self._stop(lambda j: not j.inline)

    def _stop(self, pick) -> list[str]:
        with self.lock:
            live = [j for j in self.jobs.values() if j.state == "running" and pick(j)]
            for job in live:
                job.stopped = True
        for job in live:
            self._signal(job, signal.SIGINT)
        deadline = time.monotonic() + STOP_WAIT_S
        while time.monotonic() < deadline and any(j.proc and j.proc.poll() is None for j in live):
            time.sleep(0.05)
        for job in live:
            if job.proc and job.proc.poll() is None:
                self._signal(job, signal.SIGTERM)
        return [j.name for j in live]

    @staticmethod
    def _signal(job: Job, sig: int) -> None:
        try:
            if job.proc:
                job.proc.send_signal(sig)
        except ProcessLookupError:
            pass
