# Spec: docs/specs/ui.md
"""Event broadcaster, raw-file tailer, and job record for the UI. Reads results/<id>/raw/*.jsonl.
Writes nothing.
"""

import json
import queue
import subprocess
import threading
from pathlib import Path


class Hub:
    """One queue per SSE client. publish() puts an event on every queue."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.clients: list[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        client: queue.Queue = queue.Queue()
        with self.lock:
            self.clients.append(client)
        return client

    def unsubscribe(self, client: queue.Queue) -> None:
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def publish(self, event: str, data: dict) -> None:
        with self.lock:
            for client in self.clients:
                client.put((event, data))


class Tailer:
    """Reads new complete lines of every *.jsonl in a folder; each record comes out once."""

    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir
        self.offsets: dict[Path, int] = {}
        self.lock = threading.Lock()

    def poll(self) -> list[dict]:
        records: list[dict] = []
        with self.lock:
            for path in sorted(self.raw_dir.glob("*.jsonl")):
                start = self.offsets.get(path, 0)
                with open(path, "rb") as handle:
                    handle.seek(start)
                    data = handle.read()
                end = data.rfind(b"\n") + 1
                self.offsets[path] = start + end
                for line in data[:end].decode("utf-8", errors="replace").splitlines():
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict):
                        records.append(record)
        return records


class Job:
    def __init__(self, experiment_id: str, name: str) -> None:
        self.experiment_id, self.name = experiment_id, name
        self.state, self.code = "running", None
        self.proc: subprocess.Popen | None = None
        self.stopped = self.budget = False
        self.last_stderr = ""
