# Spec: docs/specs/ui.md
"""Tests for the UI backend. The server runs on port 0 in a thread over a temporary git repo
holding a tiny 2x2 release, with the fake provider and no network.
"""

import http.client
import json
import os
import threading
import time
import tomllib
from pathlib import Path

import pytest

from src.config import load_experiment_config
from test_release import commit_all, git, run_release, repo  # noqa: F401  (repo is a fixture)
from ui.common import merged_env, parse_env
from ui.events import Tailer
from ui.server import make_server

MODELS = (
    '[[models]]\nname = "example-model"\nprovider = "fake"\napi_model_id = "ex-1"\n'
    "params = { temperature = 1.0 }\n"
    '[[models]]\nname = "cloud-model"\nprovider = "anthropic"\napi_model_id = "cl-1"\n'
    '[[models]]\nname = "unpriced"\nprovider = "fake"\napi_model_id = "up-1"\n'
)
PRICES = ("[example-model]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n"
          "[cloud-model]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n")
BUDGET = {"per_request_usd": 0.5, "per_model_usd": 5.0, "per_experiment_usd": 10.0}
FORM = {"id": "t1", "release": "1.0.0", "puzzles": ["2x2"], "models": ["example-model"],
        "attempts": 1, "retry_cap": 1, "max_output_tokens": 100, "budget": BUDGET}


@pytest.fixture
def ui_repo(repo, tmp_path_factory, monkeypatch):  # noqa: F811
    (repo / "config" / "models.toml").write_text(MODELS, encoding="utf-8")
    (repo / "config" / "prices.toml").write_text(PRICES, encoding="utf-8")
    commit_all(repo, "config")
    assert run_release(repo, "major").returncode == 0
    origin = tmp_path_factory.mktemp("origin") / "origin.git"
    git(repo, "init", "-q", "--bare", str(origin))
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return repo


@pytest.fixture
def server(ui_repo, tmp_path_factory):
    static = tmp_path_factory.mktemp("static")
    (static / "index.html").write_text('<meta name="ui-token" content="{{UI_TOKEN}}">', encoding="utf-8")
    (static / "app.js").write_text("//js", encoding="utf-8")
    (static / "style.css").write_text("/*css*/", encoding="utf-8")
    srv = make_server(ui_repo, 0, static)
    srv.root = ui_repo
    srv.keepalive_s = 0.2
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def call(srv, method, path, body=None, token=True, host=None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if token:
        headers["X-Token"] = srv.app.token
    data = json.dumps(body) if body is not None else None
    conn.request(method, path, data, headers)
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    try:
        return response.status, json.loads(raw)
    except ValueError:
        return response.status, raw.decode()


class Events:
    """Reads the SSE stream in a thread and keeps every event."""

    def __init__(self, srv):
        self.items, self.lock = [], threading.Lock()
        self.conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=60)
        self.conn.request("GET", "/api/events")
        self.response = self.conn.getresponse()
        self.comments = []
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        event = None
        for raw in self.response:
            line = raw.decode().rstrip("\n")
            if line.startswith(":"):
                self.comments.append(line)
            elif line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                with self.lock:
                    self.items.append((event, json.loads(line[6:])))

    def of(self, kind):
        with self.lock:
            return [d for e, d in self.items if e == kind]

    def wait(self, check, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if check():
                return
            time.sleep(0.05)
        raise AssertionError(f"timed out; events: {self.items[-5:]}")


def job_state(events, name):
    states = [d["state"] for d in events.of("job") if d["job"] == name]
    return states[-1] if states else None


def test_env_parsing(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('# comment\n\nA=1\nB="two words"\nC=\'x\'\nD = spaced\nREAL=file\n', encoding="utf-8")
    assert parse_env(tmp_path / ".env") == {"A": "1", "B": "two words", "C": "x", "D": "spaced", "REAL": "file"}
    monkeypatch.setenv("REAL", "env")
    merged = merged_env(tmp_path)
    assert merged["REAL"] == "env" and merged["A"] == "1"
    assert parse_env(tmp_path / "missing") == {}


def test_catalogue_disabled_reasons(server):
    status, data = call(server, "GET", "/api/catalogue")
    assert status == 200
    reasons = {m["name"]: m["disabled_reason"] for m in data["models"]}
    assert reasons == {"example-model": None, "cloud-model": "no API key: set ANTHROPIC_API_KEY",
                       "unpriced": "no price in config/prices.toml"}
    assert data["latest"] == "1.0.0"
    assert data["releases"] == [{"version": "1.0.0", "puzzles": ["2x2"], "input_count": 3,
                               "input_counts": {"2x2": 3}}]
    assert data["defaults"]["budget"] == BUDGET and data["defaults"]["attempts"] == 3
    (server.root / ".env").write_text("ANTHROPIC_API_KEY=k\n", encoding="utf-8")
    _, data = call(server, "GET", "/api/catalogue")
    assert {m["name"]: m["disabled_reason"] for m in data["models"]}["cloud-model"] is None


def test_experiment_statuses(server):
    path = server.root / "config" / "experiments" / "t1.toml"
    assert call(server, "POST", "/api/experiment", FORM) == (200, {"id": "t1", "status": "created"})
    written = path.read_bytes()
    assert call(server, "POST", "/api/experiment", FORM) == (200, {"id": "t1", "status": "unchanged"})
    assert path.read_bytes() == written
    raised = dict(FORM, budget=dict(BUDGET, per_experiment_usd=20.0))
    assert call(server, "POST", "/api/experiment", raised) == (200, {"id": "t1", "status": "budget_updated"})
    assert tomllib.loads(path.read_text())["budget"]["per_experiment_usd"] == 20.0
    before = path.read_bytes()
    status, data = call(server, "POST", "/api/experiment", dict(FORM, attempts=2))
    assert status == 409 and "exists with a different config" in data["error"]
    assert path.read_bytes() == before
    for bad in (dict(FORM, models=["cloud-model"]), dict(FORM, models=["unpriced"]),
                dict(FORM, release="9.9.9"), dict(FORM, puzzles=["3x3"]), dict(FORM, attempts=0)):
        status, data = call(server, "POST", "/api/experiment", dict(bad, id="bad"))
        assert status == 400 and "field" in data["error"]
    assert not (server.root / "config" / "experiments" / "bad.toml").exists()


def test_written_config_loads_with_puzzles(server):
    call(server, "POST", "/api/experiment", FORM)
    path = server.root / "config" / "experiments" / "t1.toml"
    config = load_experiment_config(path)
    assert config["puzzles"] == ["2x2"]
    assert config["models"] == [{"name": "example-model", "provider": "fake", "api_model_id": "ex-1",
                                 "params": {"temperature": 1.0}}]
    status, form = call(server, "GET", "/api/experiment/t1")
    assert status == 200 and form == dict(FORM, budget=BUDGET)
    assert call(server, "GET", "/api/experiment/nope")[0] == 404


def test_security(server):
    assert call(server, "POST", "/api/experiment", FORM, token=False)[0] == 403
    assert call(server, "POST", "/api/experiment", FORM, host="evil.example:80")[0] == 403
    assert call(server, "GET", "/api/catalogue", host="evil.example:80")[0] == 403
    assert call(server, "GET", "/api/commit/t1", token=False)[0] == 403
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/api/experiment", "{}", {"X-Token": server.app.token, "Content-Length": "-5"})
    assert conn.getresponse().status == 400
    port = server.server_address[1]
    assert call(server, "GET", "/api/catalogue", host=f"localhost:{port}")[0] == 200
    (server.root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    assert call(server, "GET", "/.env")[0] == 404
    assert call(server, "GET", "/static/../.env")[0] == 404
    status, page = call(server, "GET", "/")
    assert status == 200 and server.app.token in page and "{{UI_TOKEN}}" not in page
    assert call(server, "GET", "/static/app.js")[0] == 200
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/api/experiment", "x" * 70000, {"X-Token": server.app.token})
    assert conn.getresponse().status == 400


def test_tailer_reads_torn_lines_once(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    file = raw / "m.jsonl"
    tailer = Tailer(raw)
    assert tailer.poll() == []
    file.write_text('{"a": 1}\n{"a": 2', encoding="utf-8")
    assert tailer.poll() == [{"a": 1}]
    with open(file, "a", encoding="utf-8") as handle:
        handle.write('}\nnot json\n[3]\n{"a": 4}\n')
    assert tailer.poll() == [{"a": 2}, {"a": 4}]
    assert tailer.poll() == []


def test_full_run_through_api(server):
    events = Events(server)
    assert call(server, "POST", "/api/experiment", FORM)[0] == 200
    assert call(server, "POST", "/api/estimate", {"id": "t1"})[0] == 200
    events.wait(lambda: job_state(events, "estimate") == "done")
    cmd = [d for d in events.of("terminal") if d["stream"] == "cmd"][0]
    assert "src.run.run" in cmd["text"] and "--estimate" in cmd["text"]
    models = server.root / "src" / "run" / "models.py"  # slow the fake provider so the run stays alive
    models.write_text(models.read_text().replace("def _fake() -> Reply:\n", "def _fake() -> Reply:\n    import time; time.sleep(0.4)\n"))
    assert call(server, "POST", "/api/run", {"id": "t1", "limit": None})[0] == 200
    events.wait(lambda: any(d["attempt"] for d in events.of("in_progress")))  # amber before any record
    assert not events.of("record") and job_state(events, "run:example-model") == "running"
    events.wait(lambda: events.of("record"))
    assert job_state(events, "run:example-model") == "running"  # live, not a burst at the end
    events.wait(lambda: job_state(events, "run:example-model") == "done")
    records = events.of("record")
    assert len(records) == 9  # 3 inputs x 3 setups x 1 attempt
    assert len({(r["record"]["input_id"], r["record"]["setup"]) for r in records}) == 9
    progress = [d for d in events.of("in_progress") if d["model"] == "example-model"]
    assert progress[-1]["attempt"] is None and any(d["attempt"] for d in progress[:-1])
    status, snap = call(server, "GET", "/api/state/t1")
    assert status == 200 and len(snap["records"]) == 9 and len(snap["inputs"]) == 3
    assert snap["in_progress"] == {"example-model": None}
    assert snap["jobs"]["run:example-model"] == "done" and snap["report"] is None
    assert events.comments  # keep-alive or connected line arrived


def test_commit_to_remote(server, tmp_path_factory, monkeypatch):
    tmp_path = tmp_path_factory.mktemp("gh")
    stub = tmp_path / "gh"
    log = tmp_path / "gh.log"
    stub.write_text(f'#!/bin/sh\necho "$@" >> {log}\n[ "$2" = view ] && exit 1\n'
                    'echo https://example.test/pr/1\n', encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("UI_GH", str(stub))
    repo = server.root
    events = Events(server)
    call(server, "POST", "/api/experiment", FORM)
    assert call(server, "GET", "/api/commit/t1")[0] == 409  # no report yet
    call(server, "POST", "/api/run", {"id": "t1"})
    events.wait(lambda: job_state(events, "run:example-model") == "done")
    assert call(server, "POST", "/api/evaluate", {"id": "t1"})[0] == 200
    events.wait(lambda: job_state(events, "evaluate") == "done")
    head, status_before = git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")
    status, preview = call(server, "GET", "/api/commit/t1")
    assert status == 200 and preview["branch"] == "results/t1"
    assert "config/experiments/t1.toml" in preview["files"] and "results/t1/1.0.0.md" in preview["files"]
    status, result = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 200 and result["pr_url"] == "https://example.test/pr/1"
    remote = git(repo, "ls-remote", "origin", "refs/heads/results/t1").split()[0]
    assert remote == result["commit"]
    changed = git(repo, "diff", "--name-only", "refs/remotes/origin/main", result["commit"]).splitlines()
    assert changed and all(p == "config/experiments/t1.toml" or p.startswith("results/t1/") for p in changed)
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain") == status_before
    assert git(repo, "diff", "--cached", "--name-only") == ""
    args = log.read_text()
    assert "pr create --base main --head results/t1" in args and "Generated" not in args
    assert any(d["job"] == "commit" for d in events.of("terminal"))
    assert job_state(events, "commit") == "done"
    status, data = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 409 and "nothing to commit" in data["error"]
