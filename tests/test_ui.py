# Spec: docs/specs/ui.md
"""Tests for the UI backend. The server runs on port 0 in a thread over a temporary git repo
holding a tiny 2x2 release, with the fake provider and no network.
"""

import http.client
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import tomllib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import EXPERIMENT_ID_PATTERN
from src.puzzles.registry import get_engine
from test_release import commit_all, git, run_release, repo  # noqa: F401  (repo is a fixture)
from ui import secrets as key_store
from ui.common import merged_env
from ui import jobs as jobs_module
from ui import server as server_module
from ui.experiments import default_id
from ui.server import STATIC_FILES, is_loopback, make_server
from ui.tomlw import dumps_config

MODELS = (
    '[[models]]\nname = "example-model"\nprovider = "fake"\napi_model_id = "ex-1"\n'
    "params = { temperature = 1.0 }\n"
    '[[models]]\nname = "cloud-model"\nprovider = "anthropic"\napi_model_id = "cl-1"\n'
    '[[models]]\nname = "unpriced"\nprovider = "fake"\napi_model_id = "up-1"\n'
)
PRICES = ("[example-model]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n"
          "[cloud-model]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n")
BUDGET = {"per_request_usd": 0.5, "per_model_usd": 5.0, "per_experiment_usd": 10.0}
CONFIG = {"release": "1.0.0", "puzzles": ["2x2"], "attempts": 1, "retry_cap": 1, "max_output_tokens": 100,
          "models": [{"name": "example-model", "provider": "fake", "api_model_id": "ex-1",
                      "params": {"temperature": 1.0}}], "budget": BUDGET}
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
    for name in STATIC_FILES[1:]:
        (static / name).parent.mkdir(exist_ok=True)
        (static / name).write_text(f"//{name}", encoding="utf-8")
    srv = make_server(ui_repo, 0, static)
    srv.root = ui_repo
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.app.jobs.stop_all()
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


def wait_for(check, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def job_state(srv, name, experiment_id="t1"):
    """The state of a job from the log poll, which answers even before the experiment has a branch."""
    jobs = call(srv, "GET", "/api/log")[1]["jobs"]
    return next((j["state"] for j in jobs if j["job"] == name and j["id"] == experiment_id), None)


def put_branch(repo, experiment_id, files, where="both"):
    """Commit `files` onto results/<id> (on its tip, else HEAD) with plumbing only, never touching the work tree.
    `where` is "both", "local" (nothing pushed), or "remote" (pushed, then the local branch dropped)."""
    index = repo / ".git" / f"index-{experiment_id}"
    env = dict(os.environ, GIT_INDEX_FILE=str(index))
    ref = f"refs/heads/results/{experiment_id}"

    def run(*args, stdin=None, check=True):
        done = subprocess.run(["git", *args], cwd=repo, env=env, input=stdin, check=check,
                              capture_output=True, text=True)
        return done.stdout.strip()

    tip = run("rev-parse", "--verify", "-q", ref, check=False)
    try:
        run("read-tree", tip or "HEAD")
        for path, text in files.items():
            blob = run("hash-object", "-w", "--stdin", stdin=text)
            run("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
        commit = run("commit-tree", run("write-tree"), "-p", tip or "HEAD", "-m", f"results {experiment_id}")
    finally:
        index.unlink(missing_ok=True)
    run("update-ref", ref, commit)
    if where != "local":
        run("push", "-q", "origin", f"{commit}:refs/heads/results/{experiment_id}")
    if where == "remote":
        run("update-ref", "-d", ref)


def wait_job(srv, name, state="done", experiment_id="t1"):
    wait_for(lambda: job_state(srv, name, experiment_id) == state)


def slow_fake(srv, seconds=0.4):
    """Slow the fake provider so a run stays alive for a while."""
    models = srv.root / "src" / "run" / "models.py"
    models.write_text(models.read_text().replace(
        "def _fake() -> Reply:\n", f"def _fake() -> Reply:\n    import time; time.sleep({seconds})\n"))


KEY = "sk-test-0123456789abcdef"


def test_secret_files_and_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key_store.save(tmp_path, "anthropic", f"  {KEY}\n")
    folder, path = tmp_path / "secrets", tmp_path / "secrets" / "anthropic.json"
    assert json.loads(path.read_text()) == {"api_key": KEY}
    assert folder.stat().st_mode & 0o777 == 0o700 and path.stat().st_mode & 0o777 == 0o600
    key_store.save(tmp_path, "anthropic", "second-key")
    assert [p.name for p in folder.iterdir()] == ["anthropic.json"]
    assert merged_env(tmp_path)["ANTHROPIC_API_KEY"] == "second-key"
    info = key_store.inspect(tmp_path)["anthropic"]
    assert info == {"variable": "ANTHROPIC_API_KEY", "configured": True, "tail": "-key", "source": "file",
                    "location": "secrets/anthropic.json"}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env-9999")
    assert merged_env(tmp_path)["ANTHROPIC_API_KEY"] == "from-env-9999"
    info = key_store.inspect(tmp_path)["anthropic"]
    assert info["source"] == "env" and info["tail"] == "9999"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    key_store.clear(tmp_path, "anthropic")
    assert list(folder.iterdir()) == []
    assert key_store.inspect(tmp_path)["anthropic"]["source"] == "missing"
    for bad in ("", "  ", "two words", None):
        with pytest.raises(key_store.ApiError, match="api_key"):
            key_store.save(tmp_path, "openai", bad)
    with pytest.raises(key_store.ApiError, match="provider"):
        key_store.save(tmp_path, "nope", KEY)


def test_empty_env_var_does_not_hide_a_saved_key(tmp_path, monkeypatch):
    key_store.save(tmp_path, "anthropic", KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert merged_env(tmp_path)["ANTHROPIC_API_KEY"] == KEY
    assert key_store.inspect(tmp_path)["anthropic"]["source"] == "file"


def test_secret_routes(server, monkeypatch):
    for variable in ("OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    body = {"provider": "anthropic", "action": "save", "api_key": KEY}
    for method, path, payload in (("GET", "/api/secrets", None), ("POST", "/api/secrets", body)):
        assert call(server, method, path, payload, token=False)[0] == 403
    assert not (server.root / "secrets").exists()
    for path in ("/api/secrets/", "//api/secrets", "/api/secrets//"):
        assert call(server, "GET", path, token=False)[0] == 403, path
    assert call(server, "GET", "/api/commit/t1/", token=False)[0] == 403
    status, data = call(server, "POST", "/api/secrets", body)
    assert status == 200 and data["anthropic"]["tail"] == KEY[-4:]
    assert call(server, "POST", "/api/secrets", {**body, "provider": "openai"})[0] == 200
    assert call(server, "POST", "/api/secrets", {**body, "action": "wipe"})[0] == 400
    assert call(server, "POST", "/api/secrets", {**body, "api_key": "a b"})[0] == 400
    for path in ("/api/secrets", "/api/bundle", "/", "/api/log?after=0"):
        assert KEY not in json.dumps(call(server, "GET", path)[1])
    status, data = call(server, "GET", "/api/secrets")
    assert status == 200 and data["openai"]["source"] == "file" and data["google"]["source"] == "missing"
    _, bundle = call(server, "GET", "/api/bundle")
    assert {m["name"]: m["disabled_reason"] for p in bundle["providers"] for m in p["models"]}["cloud-model"] is None
    assert call(server, "POST", "/api/secrets", {"provider": "anthropic", "action": "clear"})[1]["anthropic"]["source"] == "missing"


def test_bundle_disabled_reasons_and_defaults(server):
    status, data = call(server, "GET", "/api/bundle")
    assert status == 200
    reasons = {m["name"]: m["disabled_reason"] for p in data["providers"] for m in p["models"]}
    assert reasons == {"example-model": None, "cloud-model": "no API key: add it under Models",
                       "unpriced": "no price in config/prices.toml"}
    assert data["release"] == "1.0.0" and data["releases"] == ["1.0.0"]
    assert data["defaults"]["budget"] == BUDGET and data["defaults"]["attempts"] == 3


def test_bundle_needs_token(server):
    assert call(server, "GET", "/api/bundle", token=False)[0] == 403
    assert call(server, "GET", "/api/bundle?release=9.9.9")[0] == 400


def config_files(root):
    return sorted(str(p.relative_to(root)) for p in (root / "config").rglob("*") if p.is_file())


def test_run_from_form_writes_no_config_file(server):
    before = config_files(server.root)
    assert call(server, "POST", "/api/run", FORM) == (200, {"id": "t1", "status": "created", "jobs": ["run:example-model"]})
    wait_job(server, "run:example-model")
    assert config_files(server.root) == before and not (server.root / "config" / "experiments").exists()
    saved = git(server.root, "show", "refs/heads/results/t1:results/t1/experiment.toml")
    assert tomllib.loads(saved)["puzzles"] == ["2x2"]
    assert (server.root / "results" / "t1" / "experiment.toml").read_text() == saved + "\n"
    # the form may also come under a `form` key, with the limit beside it
    assert call(server, "POST", "/api/estimate", {"form": FORM})[1]["status"] == "unchanged"


def test_statuses(server):
    before = config_files(server.root)

    def post(form):
        found = call(server, "POST", "/api/run", form)
        assert config_files(server.root) == before and not (server.root / "config" / "experiments").exists()
        return found

    assert post(FORM)[1]["status"] == "created"
    wait_job(server, "run:example-model")
    assert post(FORM)[1]["status"] == "unchanged"
    wait_job(server, "run:example-model")
    raised = dict(FORM, budget=dict(BUDGET, per_experiment_usd=20.0))
    assert post(raised)[1]["status"] == "budget_updated"
    wait_job(server, "run:example-model")
    assert tomllib.loads((server.root / "results" / "t1" / "experiment.toml").read_text())["budget"]["per_experiment_usd"] == 20.0
    log = call(server, "GET", "/api/log")[1]
    status, data = post(dict(FORM, attempts=2))
    assert status == 409 and "exists with a different config" in data["error"]
    assert call(server, "GET", "/api/log")[1]["last"] == log["last"]  # no job started, nothing logged
    for bad in (dict(FORM, models=["cloud-model"]), dict(FORM, models=["unpriced"]), dict(FORM, models=["nope"]),
                dict(FORM, release="9.9.9"), dict(FORM, puzzles=["3x3"]), dict(FORM, attempts=0)):
        status, data = post(dict(bad, id="bad"))
        assert status == 400 and "field" in data["error"]
    assert call(server, "GET", "/api/log")[1]["last"] == log["last"]
    assert not (server.root / "results" / "bad").exists()


def test_models_come_from_main_not_the_work_tree(server):
    path = server.root / "config" / "models.toml"
    path.write_text(path.read_text().replace('"unpriced"', '"fresh"'), encoding="utf-8")
    assert call(server, "POST", "/api/dry-run", dict(FORM, models=["fresh"]))[0] == 400
    assert call(server, "POST", "/api/dry-run", dict(FORM, models=["example-model"]))[0] == 200


def test_missing_puzzles_in_the_branch_config_means_every_puzzle(server):
    cli = dumps_config(CONFIG).replace('puzzles = ["2x2"]\n', "")
    assert "puzzles" not in cli
    put_branch(server.root, "t1", {"results/t1/experiment.toml": cli})
    results = server.root / "results" / "t1"
    results.mkdir(parents=True)
    (results / "experiment.toml").write_text(cli, encoding="utf-8")
    # the resumed job gets the branch's own shape (no `puzzles`), so run's stored-copy check accepts it
    assert call(server, "POST", "/api/run", FORM)[1]["status"] == "unchanged"
    wait_job(server, "run:example-model")
    raised = dict(FORM, budget=dict(BUDGET, per_model_usd=9.0))
    assert call(server, "POST", "/api/run", raised)[1]["status"] == "budget_updated"
    wait_job(server, "run:example-model")
    assert call(server, "POST", "/api/run", dict(FORM, attempts=3))[0] == 409


def test_config_route_without_puzzles_returns_every_puzzle_of_the_release(server):
    cli = dumps_config(CONFIG).replace('puzzles = ["2x2"]\n', "")
    put_branch(server.root, "t1", {"results/t1/experiment.toml": cli})
    status, form = call(server, "GET", "/api/experiment/t1/config")
    assert status == 200 and form["puzzles"] == ["2x2"]


def test_estimate_and_dry_run_refuse_only_their_own_repeat(server, spawned):
    jobs = server.app.jobs
    (job,) = jobs.register("t1", ["run:example-model"])
    assert call(server, "POST", "/api/estimate", FORM)[0] == 200
    assert call(server, "POST", "/api/dry-run", FORM)[0] == 200
    assert call(server, "POST", "/api/run", FORM)[0] == 409
    jobs.finish(job, 0)


def test_resume_without_local_results_is_refused(server):
    put_branch(server.root, "t1", {"results/t1/experiment.toml": dumps_config(CONFIG)}, where="remote")
    assert not (server.root / "results" / "t1").exists()
    log = call(server, "GET", "/api/log")[1]["last"]
    status, data = call(server, "POST", "/api/run", FORM)
    assert status == 409 and data["error"] == "the results of t1 are not in this checkout; check out its branch first"
    assert call(server, "GET", "/api/log")[1]["last"] == log


def test_start_refused_while_a_run_or_evaluate_job_of_the_experiment_is_alive(server):
    (job,) = server.app.jobs.register("t1", ["run:example-model"])
    status, data = call(server, "POST", "/api/run", dict(FORM, attempts=2))
    assert status == 409 and data["error"] == "a job of experiment t1 is running; stop it first"
    server.app.jobs.finish(job, 0)
    (job,) = server.app.jobs.register("t1", ["evaluate"])
    assert call(server, "POST", "/api/run", FORM)[0] == 409
    server.app.jobs.finish(job, 0)
    assert call(server, "POST", "/api/run", FORM)[0] == 200


def test_default_id():
    now = datetime(2026, 10, 25, 10, 12)
    assert default_id(["a.b", "c"], ["2x2"], now) == "a-b-c_2x2_20261025-1012"
    assert default_id(list("abcd"), ["2x2", "3x3"], now) == "4-models_2x2-3x3_20261025-1012"
    assert default_id(["a"], ["p1", "p2", "p3", "p4"], now) == "a_4-puzzles_20261025-1012"
    assert EXPERIMENT_ID_PATTERN.fullmatch(default_id(["a b/c"], [], now))


def test_default_id_route(server):
    status, data = call(server, "GET", "/api/default-id?models=a,b&puzzles=2x2")
    assert status == 200 and re.fullmatch(r"a-b_2x2_\d{8}-\d{4}", data["id"])


def test_branches_and_config_route(server):
    assert call(server, "GET", "/api/branches")[1] == []
    other = dict(CONFIG, attempts=2)
    put_branch(server.root, "loc", {"results/loc/experiment.toml": dumps_config(CONFIG)}, where="local")
    put_branch(server.root, "rem", {"results/rem/experiment.toml": dumps_config(CONFIG)}, where="remote")
    put_branch(server.root, "both", {"results/both/experiment.toml": dumps_config(other)})
    put_branch(server.root, "none", {"x.txt": "no experiment here"})
    assert call(server, "GET", "/api/branches")[1] == [
        {"id": "both", "release": "1.0.0", "local": True, "remote": True},
        {"id": "loc", "release": "1.0.0", "local": True, "remote": False},
        {"id": "rem", "release": "1.0.0", "local": False, "remote": True}]
    status, form = call(server, "GET", "/api/experiment/rem/config")
    assert status == 200 and form == dict(FORM, id="rem")
    assert call(server, "GET", "/api/experiment/loc/config")[1]["id"] == "loc"
    # the local branch wins over the remote one
    put_branch(server.root, "both", {"results/both/experiment.toml": dumps_config(dict(CONFIG, attempts=5))}, where="local")
    assert call(server, "GET", "/api/experiment/both/config")[1]["attempts"] == 5
    assert call(server, "GET", "/api/experiment/nope/config")[0] == 404
    assert call(server, "GET", "/api/experiment/none/config")[0] == 404


def test_inputs_route(server):
    lines = (server.root / "releases" / "1.0.0" / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
    ids = [r["input_id"] for r in map(json.loads, lines) if r["puzzle"] == "2x2"]
    status, rows = call(server, "GET", "/api/inputs?release=1.0.0&puzzle=2x2")
    assert status == 200 and [r["input_id"] for r in rows] == ids
    assert set(rows[0]) == {"input_id", "scramble_depth", "validity", "state", "scramble", "source_input_id", "corruption"}
    status, data = call(server, "GET", "/api/inputs?release=1.0.0&puzzle=9x9")
    assert status == 400 and "puzzle" in data["error"]
    assert "release" in call(server, "GET", "/api/inputs?release=9.9.9&puzzle=2x2")[1]["error"]


def test_experiment_detail_route(server):
    put_branch(server.root, "t1", {"results/t1/experiment.toml": dumps_config(CONFIG)})
    status, data = call(server, "GET", "/api/experiments/t1")
    assert status == 200 and data["id"] == "t1" and data["config"] == FORM and data["pushed"] is True
    assert call(server, "GET", "/api/experiments/nope")[0] == 404


def test_security(server):
    assert call(server, "POST", "/api/run", FORM, token=False)[0] == 403
    assert call(server, "POST", "/api/run", FORM, host="evil.example:80")[0] == 403
    assert call(server, "GET", "/api/project", host="evil.example:80")[0] == 403
    assert call(server, "GET", "/api/commit/t1", token=False)[0] == 403
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/api/run", "{}", {"X-Token": server.app.token, "Content-Length": "-5"})
    assert conn.getresponse().status == 400
    assert call(server, "GET", "/api/project", host=f"localhost:{port}")[0] == 200
    key_store.save(server.root, "openai", KEY)
    assert call(server, "GET", "/secrets/openai.json")[0] == 404
    assert call(server, "GET", "/static/../secrets/openai.json")[0] == 404
    assert call(server, "GET", "/api/catalogue")[0] == 404 and call(server, "POST", "/api/experiment", FORM)[0] == 404
    status, page = call(server, "GET", "/")
    assert status == 200 and server.app.token in page and "{{UI_TOKEN}}" not in page
    assert call(server, "GET", "/static/router.js")[0] == 200
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/api/run", "x" * 70000, {"X-Token": server.app.token})
    assert conn.getresponse().status == 400


def test_default_mode_host_check(server, ui_repo, tmp_path):
    port = server.server_address[1]
    for host in (f"8.8.8.8:{port}", f"10.1.2.3:{port}", f"localhost:{port}", f"[::1]:{port}", "10.0.0.11", "10.0.0.11:443",
                 f"8.8.8.8:{port + 1}", "[::1]"):
        assert call(server, "GET", "/api/project", host=host)[0] == 200, host
    for host in ("aiohr.dorland.keenetic.pro", f"aiohr.dorland.keenetic.pro:{port}", "evil.example", f"evil.example:{port}",
                 "localhost", f"localhost:{port + 1}", "[evil.example]"):
        assert call(server, "GET", "/api/project", host=host)[0] == 403, host
    srv = make_server(ui_repo, 0, tmp_path, allow_hosts=("AIOHR.dorland.keenetic.pro.",))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        for host in ("aiohr.dorland.keenetic.pro", "aiohr.dorland.keenetic.pro:443", "aiohr.dorland.keenetic.pro:80",
                     f"Aiohr.dorland.keenetic.pro:{port}", f"aiohr.dorland.keenetic.pro.:{port}"):
            assert call(srv, "GET", "/api/project", host=host)[0] == 200, host
        for host in ("evil.example", "evil.example:443", f"evil.example:{port}", f"localhost:{port + 1}"):
            assert call(srv, "GET", "/api/project", host=host)[0] == 403, host
        status, body = call(srv, "GET", "/api/project", host="evil.example:443")
        assert "'evil.example:443'" in body["error"] and "--allow-host" in body["error"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_is_loopback():
    assert is_loopback("::ffff:127.0.0.1") and not is_loopback("not-an-ip")


def test_default_mode_accepts_every_peer(server):
    for peer in ("8.8.8.8", "172.16.0.1", "10.0.0.5", "::1"):
        assert server.verify_request(None, (peer, 1234)) is True, peer
    sent = []
    fake = SimpleNamespace(client_address=("8.8.8.8", 1), server=server, path="/api/project",
                           headers={"Host": f"8.8.8.8:{server.server_address[1]}"}, send_json=lambda status, data: sent.append((status, data)))
    fake.host_ok = lambda: server_module.Handler.host_ok(fake)
    server_module.Handler.handle_request(fake, "GET")
    assert not sent or sent[0][0] != 403 or "client address" not in sent[0][1]["error"]


def test_no_lan_refuses_other_peers_and_hosts(ui_repo, tmp_path):
    srv = make_server(ui_repo, 0, tmp_path, lan=False)
    try:
        assert srv.verify_request(None, ("127.0.0.1", 1)) is True
        for peer in ("10.0.0.5", "192.168.1.5", "8.8.8.8"):
            assert srv.verify_request(None, (peer, 1)) is False
        port = srv.server_address[1]
        for host, ok in ((f"localhost:{port}", True), (f"127.0.0.1:{port}", True), (f"127.1.2.3:{port}", True),
                         (f"10.0.0.5:{port}", False), (f"evil.example:{port}", False), (f"localhost:{port + 1}", False)):
            fake = SimpleNamespace(server=srv, headers={"Host": host})
            assert server_module.Handler.host_ok(fake) is ok, host
        sent = []
        fake = SimpleNamespace(client_address=("10.0.0.5", 1), server=srv, path="/api/project", headers={},
                               send_json=lambda status, data: sent.append((status, data)))
        server_module.Handler.handle_request(fake, "GET")
        assert sent and sent[0][0] == 403 and "client address" in sent[0][1]["error"]
    finally:
        srv.server_close()


def test_main_no_lan_binds_loopback(ui_repo, monkeypatch):
    seen = {}

    def fake_make_server(root, port, static_dir=None, host="x", lan=True, allow_hosts=()):
        seen.update(host=host, lan=lan)
        raise OSError(0, "stop here")

    monkeypatch.setattr(server_module, "make_server", fake_make_server)
    assert server_module.main(["--root", str(ui_repo), "--port", "0", "--no-lan"]) == 1
    assert seen == {"host": "127.0.0.1", "lan": False}


def test_main_prints_the_open_warning_and_allowed_hosts(ui_repo, monkeypatch, capsys):
    monkeypatch.setattr(server_module.UiServer, "serve_forever", lambda self: None)
    assert server_module.main(["--root", str(ui_repo), "--port", "0", "--allow-host", "Aiohr.Example."]) == 0
    out = capsys.readouterr().out
    assert "Open to every client: anyone who can reach this port can run experiments on your API keys (use --no-lan for this machine only)" in out
    assert "Allowed Host names: aiohr.example" in out


def test_main_binds_all_interfaces(ui_repo, monkeypatch):
    seen = {}

    def fake_make_server(root, port, static_dir=None, host="127.0.0.1", lan=True, allow_hosts=()):
        seen["host"] = host
        raise OSError(0, "stop here")

    monkeypatch.setattr(server_module, "make_server", fake_make_server)
    assert server_module.main(["--root", str(ui_repo), "--port", "0"]) == 1
    assert seen["host"] == "0.0.0.0"


def test_log_keeps_the_newest_lines_and_serves_after(server, monkeypatch):
    monkeypatch.setattr(jobs_module, "LOG_CAP", 3)
    for n in range(5):
        server.app.jobs.say("j", "stdout", f"line {n}")
    status, data = call(server, "GET", "/api/log?after=0")
    assert status == 200 and [l["text"] for l in data["lines"]] == ["line 2", "line 3", "line 4"]
    assert data["last"] == 5 and data["lines"][0] == {"seq": 3, "job": "j", "stream": "stdout", "text": "line 2"}
    assert [l["seq"] for l in call(server, "GET", "/api/log?after=4")[1]["lines"]] == [5]
    assert call(server, "GET", "/api/log?after=x")[0] == 400


def snapshot_when_ready(srv, experiment_id="t1"):
    """The run commits its branch just after it starts; until then the experiment is unknown (404)."""
    return wait_for(lambda: (lambda r: r[1] if r[0] == 200 else None)(call(srv, "GET", f"/api/state/{experiment_id}")))


def test_full_run_through_api(server):
    assert call(server, "POST", "/api/estimate", FORM)[0] == 200
    wait_job(server, "estimate")
    cmds = [l for l in call(server, "GET", "/api/log")[1]["lines"] if l["stream"] == "cmd"]
    assert "src.run.run" in cmds[0]["text"] and "--config -" in cmds[0]["text"] and "--estimate" in cmds[0]["text"]
    assert not (server.root / "results" / "t1").exists()  # an estimate writes nothing
    slow_fake(server)
    assert call(server, "POST", "/api/run", FORM)[0] == 200
    assert call(server, "POST", "/api/run", FORM)[0] == 409  # already running
    snap = snapshot_when_ready(server)
    assert snap["jobs"]["run:example-model"] == "running" and "in_progress" not in snap
    assert snap["setups"] == ["no_model", "descriptive", "prescriptive"] and snap["attempts"] == 1
    wait_for(lambda: call(server, "GET", "/api/state/t1")[1]["records"])
    assert job_state(server, "run:example-model") == "running"  # records arrive live, not in a burst
    row = next(r for r in call(server, "GET", "/api/bundle")[1]["experiments"] if r["id"] == "t1")
    assert row["running"] is True and row["pushed"] is False
    wait_job(server, "run:example-model")
    status, snap = call(server, "GET", "/api/state/t1")
    assert status == 200 and len(snap["records"]) == 9 and len(snap["inputs"]) == 3  # 3 inputs x 3 setups x 1
    assert len({(r["input_id"], r["setup"]) for r in snap["records"]}) == 9
    assert snap["jobs"]["run:example-model"] == "done" and snap["report"] is None
    assert not list((server.root / "results" / "t1").glob(".*tmp"))  # the atomic copy leaves no temp file
    row = next(r for r in call(server, "GET", "/api/bundle")[1]["experiments"] if r["id"] == "t1")
    assert row["running"] is False and row["pushed"] is True  # run pushes its branch when it ends
    assert (server.root / "results" / "t1" / "experiment.toml").read_text() == dumps_config(CONFIG)


def test_run_and_evaluate_exclude_each_other(server):
    jobs = server.app.jobs
    results = server.root / "results" / "t1"
    results.mkdir(parents=True)
    (results / "experiment.toml").write_text(dumps_config(CONFIG), encoding="utf-8")
    (job,) = jobs.register("t1", ["evaluate"])
    status, data = call(server, "POST", "/api/run", FORM)
    assert status == 409 and "is running" in data["error"]
    jobs.finish(job, 0)
    (job,) = jobs.register("t1", ["run:example-model"])
    assert call(server, "POST", "/api/evaluate", {"id": "t1"})[0] == 409
    jobs.finish(job, 0)
    (server.root / "results" / "t1" / "experiment.toml").unlink()
    status, data = call(server, "POST", "/api/evaluate", {"id": "t1"})
    assert status == 409 and data["error"] == "experiment t1 has no results in this checkout"


def test_stop_and_stop_all(server):
    slow_fake(server, 0.5)
    call(server, "POST", "/api/run", FORM)
    snapshot_when_ready(server)
    wait_for(lambda: call(server, "GET", "/api/state/t1")[1]["records"])
    status, data = call(server, "POST", "/api/stop", {"id": "t1"})
    assert status == 200 and data["stopped"] == ["run:example-model"]
    wait_job(server, "run:example-model", "stopped")
    assert call(server, "POST", "/api/run", FORM)[1]["status"] == "unchanged"  # resumes
    wait_job(server, "run:example-model", "running")
    assert server.app.jobs.stop_all() == ["run:example-model"]
    wait_job(server, "run:example-model", "stopped")


def test_server_stops_its_jobs_on_sigterm(ui_repo):
    slow_fake(SimpleNamespace(root=ui_repo), 0.5)
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.Popen([sys.executable, "-m", "ui.server", "--port", "0", "--root", str(ui_repo)], cwd=root,
                            stdout=subprocess.PIPE, text=True)
    try:
        port = int(re.search(r":(\d+)/", proc.stdout.readline()).group(1))

        def request(method, path, body=None, token=""):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": token})
            return conn.getresponse().read().decode()

        token = re.search(r'name="ui-token" content="([^"]+)"', request("GET", "/")).group(1)
        assert "run:example-model" in request("POST", "/api/run", FORM, token)
        raw = ui_repo / "results" / "t1" / "raw" / "example-model.jsonl"
        wait_for(lambda: raw.is_file() and raw.read_text())
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0
        count = len(raw.read_text().splitlines())
        time.sleep(1.5)
        assert len(raw.read_text().splitlines()) == count < 9  # the run died with the server
    finally:
        if proc.poll() is None:
            proc.kill()


GH_STUB = """#!/bin/sh
echo "$@" >> {dir}/gh.log
if [ "$2" = view ]; then [ -f {dir}/view.json ] && cat {dir}/view.json && exit 0; exit 1; fi
[ -f {dir}/fail_create ] && exit 1
echo '{{"url": "https://example.test/pr/1", "state": "OPEN"}}' > {dir}/view.json
echo https://example.test/pr/1
"""


@pytest.fixture
def gh(tmp_path_factory, monkeypatch):
    folder = tmp_path_factory.mktemp("gh")
    stub = folder / "gh"
    stub.write_text(GH_STUB.format(dir=folder), encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("UI_GH", str(stub))
    return folder


def evaluated(server):
    call(server, "POST", "/api/run", FORM)
    wait_job(server, "run:example-model")
    assert call(server, "POST", "/api/evaluate", {"id": "t1"})[0] == 200
    wait_job(server, "evaluate")


def test_commit_refused_when_report_is_older_than_raw(server, gh):
    evaluated(server)
    assert call(server, "GET", "/api/commit/t1")[0] == 200
    raw = server.root / "results" / "t1" / "raw" / "example-model.jsonl"
    report = server.root / "results" / "t1" / "1.0.0.md"
    os.utime(raw, (report.stat().st_mtime + 5, report.stat().st_mtime + 5))
    for status, data in (call(server, "GET", "/api/commit/t1"), call(server, "POST", "/api/commit", {"id": "t1"})):
        assert status == 409 and "evaluate again first" in data["error"]


def test_failed_push_and_failed_pr_can_be_retried(server, gh):
    repo = server.root
    evaluated(server)
    good = git(repo, "remote", "get-url", "origin")
    run_tip = git(repo, "rev-parse", "refs/heads/results/t1")  # the run's own commits
    git(repo, "remote", "set-url", "--push", "origin", good + ".missing")  # fetch works, push fails
    status, data = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 409 and "git push failed" in data["error"]
    assert git(repo, "rev-parse", "refs/heads/results/t1") == run_tip  # the local ref moves only after the push
    git(repo, "remote", "set-url", "--push", "origin", good)
    (gh / "fail_create").write_text("")
    status, data = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 409 and "/gh pr failed" in data["error"]
    assert git(repo, "ls-remote", "origin", "refs/heads/results/t1")  # pushed, no pull request yet
    (gh / "fail_create").unlink()
    status, result = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 200 and result["pr_url"] == "https://example.test/pr/1"
    assert git(repo, "ls-remote", "origin", "refs/heads/results/t1").split()[0] == result["commit"]


def test_local_commits_not_on_the_remote_are_pushed_even_with_an_empty_diff(server, gh):
    repo = server.root
    evaluated(server)
    status, result = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 200
    tree = git(repo, "rev-parse", "refs/heads/results/t1^{tree}")
    ahead = git(repo, "commit-tree", tree, "-p", "refs/heads/results/t1", "-m", "Results: more")
    git(repo, "update-ref", "refs/heads/results/t1", ahead)
    (gh / "view.json").write_text('{"url": "https://example.test/pr/9", "state": "OPEN"}')
    status, data = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 200 and data["commit"] == ahead
    assert git(repo, "ls-remote", "origin", "refs/heads/results/t1").split()[0] == ahead
    status, data = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 409 and "nothing to commit" in data["error"]


def test_a_stale_local_branch_is_fast_forwarded_to_the_remote(server, gh):
    repo = server.root
    evaluated(server)
    tip = git(repo, "rev-parse", "refs/heads/results/t1")
    git(repo, "push", "origin", "refs/heads/results/t1:refs/heads/results/t1")
    git(repo, "update-ref", "refs/heads/results/t1", "refs/heads/results/t1~1")
    status, preview = call(server, "GET", "/api/commit/t1")
    assert status == 200 and preview["base"] == tip
    assert git(repo, "rev-parse", "refs/heads/results/t1") == tip


def test_only_an_open_pull_request_counts(server, gh):
    evaluated(server)
    (gh / "view.json").write_text('{"url": "https://example.test/pr/9", "state": "CLOSED"}')
    status, result = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 200 and result["pr_url"] == "https://example.test/pr/1"
    (gh / "view.json").write_text('{"url": "https://example.test/pr/9", "state": "OPEN"}')
    status, data = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 409 and "nothing to commit" in data["error"]


def test_commit_to_remote(server, gh):
    log = gh / "gh.log"
    repo = server.root
    assert call(server, "GET", "/api/commit/t1")[0] == 404  # nothing run yet
    call(server, "POST", "/api/run", FORM)
    wait_job(server, "run:example-model")
    assert call(server, "POST", "/api/evaluate", {"id": "t1"})[0] == 200
    wait_job(server, "evaluate")
    head, status_before = git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")
    status, preview = call(server, "GET", "/api/commit/t1")
    assert status == 200 and preview["branch"] == "results/t1"
    assert "results/t1/1.0.0.md" in preview["files"]  # the run already committed config and raw records
    assert preview["base"] == git(repo, "rev-parse", "refs/heads/results/t1")
    status, result = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 200 and result["pr_url"] == "https://example.test/pr/1"
    remote = git(repo, "ls-remote", "origin", "refs/heads/results/t1").split()[0]
    assert remote == result["commit"]
    changed = git(repo, "diff", "--name-only", "refs/remotes/origin/main", result["commit"]).splitlines()
    assert "results/t1/experiment.toml" in changed and "results/t1/raw/example-model.jsonl" in changed
    assert all(p.startswith("results/t1/") for p in changed)  # only results/<id> is added
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain") == status_before
    assert git(repo, "diff", "--cached", "--name-only") == ""
    args = log.read_text()
    assert "pr create --base main --head results/t1" in args and "Generated" not in args
    assert any(l["job"] == "commit" for l in call(server, "GET", "/api/log")[1]["lines"])
    assert job_state(server, "commit") == "done"
    status, data = call(server, "POST", "/api/commit", {"id": "t1"})
    assert status == 409 and "nothing to commit" in data["error"]


@pytest.fixture
def spawned(monkeypatch):
    """Record the argv of each spawned job instead of starting it."""
    seen = []
    monkeypatch.setattr(jobs_module.Jobs, "stdins", [], raising=False)

    def fake(self, job, argv, stdin=None):
        seen.append(argv)
        self.stdins.append(stdin)
        self.say(job.name, "cmd", " ".join(argv))
        self.finish(job, 0)

    monkeypatch.setattr(jobs_module.Jobs, "_spawn", fake)
    return seen


def on_branch(srv, name):
    git(srv.root, "checkout", "-q", "-B", name)


def test_project_info_shape(server):
    on_branch(server, "feat")
    status, data = call(server, "GET", "/api/project", token=False)
    assert status == 200 and data["branch"] == "feat" and data["clean"] is True
    assert data["latest_release"] == "1.0.0" and data["python"] == sys.version.split()[0]
    assert set(data["packages"]) == {"anthropic", "openai", "google-genai", "pytest"}
    assert data["packages"]["pytest"] is True and isinstance(data["gh"], bool)
    (server.root / "stray.txt").write_text("x")
    assert call(server, "GET", "/api/project", token=False)[1]["clean"] is False


def test_project_job_argv(server, spawned):
    on_branch(server, "feat")
    py = sys.executable
    assert call(server, "POST", "/api/install", {})[0] == 200
    assert spawned[-1] == [py, "-u", "-m", "pip", "install", "-e", ".[test]"]
    assert call(server, "POST", "/api/tests", {})[0] == 200
    assert spawned[-1] == [py, "-u", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    assert call(server, "POST", "/api/release", {"bump": "minor", "note": " why "})[0] == 200
    assert spawned[-1] == [py, "-u", "-m", "src.release.release", "--bump", "minor", "--note", "why"]
    assert call(server, "POST", "/api/dry-run", FORM)[0] == 200
    assert spawned[-1] == [py, "-u", "-m", "src.run.run", "--experiment", "t1", "--config", "-", "--dry-run"]
    assert jobs_module.Jobs.stdins[-1] == dumps_config(CONFIG)  # the config goes on stdin, never to disk
    assert call(server, "POST", "/api/run", dict(FORM, limit=2))[0] == 200
    assert spawned[-1] == [py, "-u", "-m", "src.run.run", "--experiment", "t1", "--config", "-",
                           "--model", "example-model", "--limit", "2"]
    assert call(server, "POST", "/api/run", dict(FORM, limit=0))[0] == 400
    (server.root / "results" / "t1").mkdir(parents=True)
    (server.root / "results" / "t1" / "experiment.toml").write_text("x")
    assert call(server, "POST", "/api/evaluate", {"id": "t1", "release": "1.0.0"})[0] == 200
    assert spawned[-1][-2:] == ["--release", "1.0.0"]
    assert call(server, "POST", "/api/evaluate", {"id": "t1", "release": "x"})[0] == 400
    assert call(server, "POST", "/api/install", {})[0] == 200  # earlier jobs are over
    jobs = call(server, "GET", "/api/log")[1]["jobs"]
    assert {"id": "", "job": "install", "state": "done", "code": 0} in jobs


def test_release_refusals(server, spawned):
    on_branch(server, "main")
    assert call(server, "POST", "/api/release", {"bump": "patch", "note": "x"})[0] == 409
    assert call(server, "POST", "/api/push", {})[0] == 409
    on_branch(server, "feat")
    assert call(server, "POST", "/api/release", {"bump": "patch", "note": "  "})[0] == 400
    assert call(server, "POST", "/api/release", {"bump": "huge", "note": "x"})[0] == 400
    git(server.root, "checkout", "-q", "--detach")
    assert call(server, "POST", "/api/release", {"bump": "patch", "note": "x"})[0] == 409
    assert spawned == []


def test_mutating_jobs_wait_for_any_job(server, spawned):
    on_branch(server, "feat")
    jobs = server.app.jobs
    jobs.register("t1", ["run:example-model"])
    for path, body in (("/api/install", {}), ("/api/release", {"bump": "patch", "note": "x"}),
                       ("/api/push", {})):
        assert call(server, "POST", path, body)[0] == 409
    assert call(server, "POST", "/api/tests", {})[0] == 200  # not mutating
    jobs.jobs[("t1", "run:example-model")].state = "done"
    jobs.register("", ["tests"])
    assert call(server, "POST", "/api/tests", {})[0] == 409  # the same job is running


def test_push_creates_then_reuses_pull_request(server, gh):
    on_branch(server, "feat")
    git(server.root, "tag", "v-test")
    git(server.root, "tag", "release-9.9.9")  # reachable from HEAD
    git(server.root, "checkout", "-q", "-b", "other", "main")
    (server.root / "o.txt").write_text("o")
    commit_all(server.root, "other")
    git(server.root, "tag", "release-8.8.8")  # on another branch only
    git(server.root, "checkout", "-q", "feat")
    status, result = call(server, "POST", "/api/push", {})
    assert status == 200 and result == {"branch": "feat", "pr_url": "https://example.test/pr/1"}
    assert git(server.root, "ls-remote", "origin", "refs/heads/feat")
    tags = git(server.root, "ls-remote", "--tags", "origin")
    assert "release-9.9.9" in tags and "v-test" not in tags and "release-8.8.8" not in tags
    log = (gh / "gh.log").read_text()
    assert "pr create --base main --head feat --fill" in log and "Generated" not in log
    assert job_state_of(server, "push") == "done"
    before = log.count("pr create")
    assert call(server, "POST", "/api/push", {})[1]["pr_url"] == "https://example.test/pr/1"
    assert (gh / "gh.log").read_text().count("pr create") == before


def job_state_of(srv, name):
    return next(j["state"] for j in call(srv, "GET", "/api/log")[1]["jobs"] if j["job"] == name)


def test_exclusive_job_blocks_everything_and_release_needs_clean_tree(server, spawned):
    on_branch(server, "feat")
    (server.root / "stray.txt").write_text("x")
    status, data = call(server, "POST", "/api/release", {"bump": "patch", "note": "x"})
    assert status == 409 and "stray.txt" in data["error"] and spawned == []
    (server.root / "stray.txt").unlink()
    jobs = server.app.jobs
    jobs.register("", ["install"], exclusive=True)
    (server.root / "results" / "t1").mkdir(parents=True)
    (server.root / "results" / "t1" / "experiment.toml").write_text(dumps_config(CONFIG), encoding="utf-8")
    for path, body in (("/api/run", FORM), ("/api/estimate", FORM), ("/api/evaluate", {"id": "t1"}),
                       ("/api/dry-run", FORM), ("/api/tests", {})):
        assert call(server, "POST", path, body)[0] == 409, path


def put_raw(srv, drop=(), torn=None, **fields):
    """Add one raw record to the experiment's branch by hand (local and remote), so a replay test needs no run."""
    record = {"model": "example-model", "input_id": srv.first["input_id"], "setup": "no_model",
              "attempt_number": 1, "outcome": "success", "parsed_moves": [], "raw_response": "", "stop_reason": "ok",
              "input_tokens": 1, "output_tokens": 1, "retry_input_tokens": 0, "retry_output_tokens": 0,
              "latency_s": 0.1, "served_model": "s", "created_at": "2026-10-25T00:00:00Z", **fields}
    for key in drop:
        del record[key]
    srv.raw = getattr(srv, "raw", "") + json.dumps(record) + "\n"
    put_branch(srv.root, "t1", {"results/t1/experiment.toml": dumps_config(CONFIG),
                                "results/t1/raw/example-model.jsonl": srv.raw + (torn or "")})


REPLAY = "/api/replay/t1?model=example-model&input_id=ID&setup=no_model&attempt=1"


def url(srv, text=REPLAY):
    return text.replace("ID", srv.first["input_id"])


def start_state(srv):
    lines = (srv.root / "releases" / "1.0.0" / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
    row = next(r for r in map(json.loads, lines) if r["puzzle"] == "2x2" and r["validity"] == "valid")
    srv.first = row  # the test inputs differ from the real release
    return row["state"]


def test_replay_frames_follow_apply_move(server):
    state = start_state(server)
    moves = ["R", "U'", "F2"]
    put_raw(server, parsed_moves=moves, outcome="failure")
    status, data = call(server, "GET", url(server))
    engine, expected = get_engine("2x2"), [state]
    for move in moves:
        expected.append(engine.apply_move(expected[-1], move))
    assert status == 200 and data["frames"] == expected and data["moves"] == moves
    assert data["stopped_at"] is None and data["solved"] is False and data["outcome"] == "failure"
    assert data["puzzle"] == "2x2" and data["input_id"] == server.first["input_id"]


def test_replay_stops_at_an_impossible_move(server):
    start_state(server)
    put_raw(server, parsed_moves=["R", "X", "U"], outcome="hallucination")
    status, data = call(server, "GET", url(server))
    assert status == 200 and data["stopped_at"] == 1 and len(data["frames"]) == 2
    assert data["moves"] == ["R", "X", "U"] and data["solved"] is False and data["outcome"] == "hallucination"
    put_raw(server, attempt_number=2, parsed_moves=["r"], outcome="hallucination")  # exact match only
    assert call(server, "GET", url(server, REPLAY.replace("attempt=1", "attempt=2")))[1]["stopped_at"] == 0


def test_replay_solved_flag_and_malformed_output(server):
    state = start_state(server)
    scramble = server.first["scramble"]
    inverse = [m[0] + {"": "'", "'": "", "2": "2"}[m[1:]] for m in reversed(scramble)]
    put_raw(server, parsed_moves=inverse)
    assert call(server, "GET", url(server))[1]["solved"] is True
    put_raw(server, attempt_number=2, outcome="malformed_output", parsed_moves=None)
    status, data = call(server, "GET", url(server, REPLAY.replace("attempt=1", "attempt=2")))
    assert status == 200 and data["frames"] == [state] and data["moves"] == [] and data["solved"] is False


def test_replay_survives_a_torn_line_and_a_record_without_parsed_moves(server):
    state = start_state(server)
    put_raw(server, drop=("parsed_moves",), outcome="infrastructure_failure")
    put_raw(server, attempt_number=3, torn='{"model": "example-model", "input_id": "tor')  # a stopped write leaves a torn last line
    status, data = call(server, "GET", url(server))
    assert status == 200 and data["frames"] == [state] and data["moves"] == [] and data["outcome"] == "infrastructure_failure"
    assert call(server, "GET", url(server, REPLAY.replace("attempt=1", "attempt=2")))[0] == 404


def test_replay_errors(server):
    start_state(server)
    put_raw(server)
    assert call(server, "GET", REPLAY.replace("ID", "nope"))[0] == 404
    assert call(server, "GET", url(server, REPLAY.replace("attempt=1", "attempt=2")))[0] == 404
    assert call(server, "GET", url(server, REPLAY.replace("model=example-model", "model=other")))[0] == 404
    assert call(server, "GET", "/api/replay/nope?model=a&input_id=b&setup=no_model&attempt=1")[0] == 404
    for bad in ("attempt=0", "attempt=x", "attempt=-1", "attempt=", "setup=bogus"):
        name = bad.split("=")[0]
        status, data = call(server, "GET", url(server, REPLAY.replace(f"{name}={'1' if name == 'attempt' else 'no_model'}", bad)))
        assert status == 400 and name in data["error"], bad
    assert call(server, "GET", "/api/replay/t1?model=example-model&input_id=x&setup=no_model")[0] == 400


def spec_static_files():
    files = (Path(__file__).resolve().parent.parent / "docs" / "specs" / "ui.md").read_text(encoding="utf-8")
    line = next(l for l in files.splitlines() if l.startswith("Files:"))
    return re.findall(r"`ui/static/([\w/.]+)`", line)


def test_every_static_file_of_the_spec_is_served_and_nothing_else(server):
    names = spec_static_files()
    assert "pages/models.js" in names and sorted(names) == sorted(STATIC_FILES)
    for name in names:
        status, body = call(server, "GET", f"/static/{name}", token=False)
        assert status == 200, name
        assert body.startswith("//") or name in ("index.html", "style.css") or "ui-token" in body
    assert call(server, "GET", "/static/pages/models.js", token=False)[1] == "//pages/models.js"
    for path in ("/static/other.js", "/static/app.js", "/static/pages/other.js", "/static/../secrets/x",
                 "/static/pages/../index.html", "/static/pages", "/static/"):
        assert call(server, "GET", path, token=False)[0] == 404, path


def test_dropped_connection_prints_no_traceback(server, capsys):
    """A browser that resets an idle socket (a preconnect it never used) causes no traceback."""
    port = server.server_address[1]
    dropped = socket.create_connection(("127.0.0.1", port))
    dropped.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))  # close with RST
    dropped.send(b"GET / HT")
    dropped.close()
    time.sleep(0.3)
    assert "Traceback" not in capsys.readouterr().err


def test_main_refuses_a_port_another_server_answers_on(ui_repo, capsys):
    """On macOS a --no-lan bind can share a port with a --lan server; main must refuse it."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    port = holder.getsockname()[1]
    try:
        assert server_module.main(["--port", str(port), "--root", str(ui_repo), "--no-lan"]) == 1
        assert "another server is listening" in capsys.readouterr().err
    finally:
        holder.close()


def test_failed_dry_run_logs_its_error_line(server):
    """A dry run that fails leaves its stderr line in the log under its job name, so the banner can show it."""
    validator = server.root / "src" / "validator.py"
    validator.write_text(validator.read_text() + "\n# changed after the release\n", encoding="utf-8")
    assert call(server, "POST", "/api/dry-run", FORM)[0] == 200
    wait_job(server, "dry-run", "failed")
    lines = call(server, "GET", "/api/log?after=0")[1]["lines"]
    errors = [l for l in lines if l["job"] == "dry-run" and l["stream"] == "stderr"]
    assert errors and errors[-1]["text"].startswith("error:")
