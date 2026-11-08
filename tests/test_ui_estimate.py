# Spec: docs/specs/ui.md
"""Tests for `POST /api/estimate/live`: counts, spent from branch records, the median latency, partial timing, the
400s, and that the numbers equal those of `run --estimate`. Uses the temporary git repo of tests/test_ui.py."""

import json
import time

from src.config import parse_experiment_config
from src.release.release import load_release
from src.run.budget import estimate
from src.run.prompts import build_prompt, load_questions
from src.run.models import DECISION_PROVIDERS
from src.run.run import pending_attempts
from src.config import max_moves
from test_release import commit_all, git, repo  # noqa: F401  (fixture)
from test_ui import BUDGET, FORM, call, put_branch, server, ui_repo  # noqa: F401  (fixtures)
from ui.tomlw import dumps_config

URL = "/api/estimate/live"
LIVE = {"form": FORM, "parallel": 1}


def record(model, input_id, setup, number=1, latency=2.0, outcome="success", tokens=1000):
    return {"input_id": input_id, "setup": setup, "model": model, "attempt_number": number, "raw_response": "R",
            "stop_reason": "ok", "outcome": outcome, "input_tokens": tokens, "output_tokens": tokens,
            "retry_input_tokens": 0, "retry_output_tokens": 0, "latency_s": latency, "served_model": "x",
            "created_at": "2026-11-08T00:00:00Z"}


def raw_files(records):
    out = {}
    for r in records:
        out.setdefault(r["model"], []).append(json.dumps(r))
    return {f"results/{FORM['id']}/raw/{m}.jsonl": "\n".join(lines) + "\n" for m, lines in out.items()}


def inputs_of(server):
    release = server.root / "releases" / "1.0.0" / "inputs.jsonl"
    return [json.loads(line) for line in release.read_text().splitlines()]


def cli_numbers(root, config, only=None):
    """The estimate `run --estimate` would compute for the config, from the work tree."""
    folder = root / "releases" / config["release"]
    manifest, inputs = load_release(folder, any(m["provider"] in DECISION_PROVIDERS for m in config["models"]))
    pending = list(pending_attempts(config, inputs, root / "results" / config["experiment_id"] / "raw", None))
    prompts = {(r["input_id"], s): build_prompt(folder / "prompts", r, s) for r, _, s, _ in pending}
    caps = {p: max_moves(config, manifest["release_config"], p) for p in manifest["release_config"]["puzzles"]}
    questions = load_questions(folder / "prompts") if any(
        m["provider"] in DECISION_PROVIDERS for _, m, _, _ in pending) else None
    prices = {"example-model": {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0},
              "cloud-model": {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0},
              "deci": {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0}}
    spent = {m["name"]: 0.0 for m in config["models"]}
    return estimate(config, pending, prices, questions, None, caps, prompts,
                    bool(manifest.get("mismatch_reasons", False)), spent)


def config_of(form, server):
    from ui import forms
    from ui.common import merged_env
    text = forms.config_text(server.app.bundles, form, merged_env(server.root), keyless_ok=True)
    return parse_experiment_config(text, form["id"], "x.toml")


def test_counts_and_no_records(server):
    status, body = call(server, "POST", URL, LIVE)
    assert status == 200, body
    n = len(inputs_of(server))
    assert body["counts"] == {"inputs": n, "models": 1, "setups": 3, "attempts": 1, "planned": n * 3, "done": 0,
                              "to_run": n * 3}
    assert body["models"][0]["attempts"] == n * 3
    assert body["timing"] == "partial" and body["total"]["time_s"] is None
    assert body["models"][0]["time_s"] is None and body["models"][0]["latency_n"] == 0
    assert body["models"][0]["median_latency_s"] is None and body["models"][0]["over"] is False


def test_equals_run_estimate(server):
    form = {**FORM, "models": ["example-model", "cloud-model"], "attempts": 2}
    status, body = call(server, "POST", URL, {"form": form, "parallel": 3})
    assert status == 200, body  # cloud-model has no API key, which the live estimate allows
    want = cli_numbers(server.root, config_of(form, server))
    for key in ("models", "total", "per_request_usd"):
        got = body[key]
        if key == "models":
            got = [{k: m[k] for k in want["models"][0]} for m in got]
        elif key == "total":
            got = {k: got[k] for k in want["total"]}
        assert got == want[key]


def test_decision_model_equals_run_estimate(server):
    root = server.root
    models = root / "config" / "models.toml"
    models.write_text(models.read_text() + '[[models]]\nname = "deci"\nprovider = "fake_decision"\napi_model_id = "d-1"\n')
    prices = root / "config" / "prices.toml"
    prices.write_text(prices.read_text() + "[deci]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n")
    commit_all(root, "decision model")
    git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
    form = {**FORM, "models": ["deci"], "budget": {**BUDGET, "per_request_usd": 1.0}}
    status, body = call(server, "POST", URL, {"form": form})
    assert status == 200, body
    want = cli_numbers(root, config_of(form, server))
    assert body["models"][0]["worst_case_usd"] == want["models"][0]["worst_case_usd"] > 0
    assert body["models"][0]["input_tokens"] == want["models"][0]["input_tokens"]


def test_done_and_spent_from_branch_records(server):
    ids = [r["input_id"] for r in inputs_of(server)]
    records = [record("example-model", ids[0], "no_model", tokens=1_000_000),
               record("example-model", ids[1], "descriptive", tokens=1_000_000)]
    put_branch(server.root, "t1", {"results/t1/experiment.toml": dumps_config(config_of(FORM, server)),
                                  **raw_files(records)}, where="remote")
    status, body = call(server, "POST", URL, LIVE)
    assert status == 200, body
    n = len(ids)
    assert body["counts"]["done"] == 2 and body["counts"]["to_run"] == n * 3 - 2
    assert body["models"][0]["attempts"] == n * 3 - 2
    assert abs(body["models"][0]["spent_usd"] - 6.0) < 1e-9  # 2 records x (1 + 2) USD
    assert body["models"][0]["over"] is True  # 6.0 spent passes per_model_usd 5.0
    assert body["total"]["over"] is False


def test_latency_median_and_timing(server):
    ids = [r["input_id"] for r in inputs_of(server)]
    records = [record("example-model", ids[0], "no_model", latency=1.0),
               record("example-model", ids[0], "descriptive", latency=5.0),
               record("example-model", ids[0], "prescriptive", latency=3.0),
               record("example-model", ids[1], "no_model", latency=100.0, outcome="infrastructure_failure")]
    put_branch(server.root, "other", {"results/other/experiment.toml": dumps_config(config_of(FORM, server)),
                                      **{k.replace("/t1/", "/other/"): v for k, v in raw_files(records).items()}},
               where="remote")
    status, body = call(server, "POST", URL, {"form": FORM, "parallel": 2})
    assert status == 200, body
    m = body["models"][0]
    assert m["median_latency_s"] == 3.0 and m["latency_n"] == 3
    assert m["time_s"] == m["attempts"] * 3.0 / 2
    assert body["timing"] == "full" and body["total"]["time_s"] == m["time_s"]
    both = {**FORM, "models": ["example-model", "cloud-model"]}
    body = call(server, "POST", URL, {"form": both, "parallel": 2})[1]
    assert body["timing"] == "partial" and body["total"]["time_s"] is None
    assert body["models"][1]["time_s"] is None and body["models"][1]["latency_n"] == 0


def test_errors(server):
    bad = [({"form": {**FORM, "models": ["unpriced"]}}, "unpriced"),
           ({"form": {**FORM, "release": "9.9.9"}}, "release"),
           ({"form": {**FORM, "puzzles": ["7x7"]}}, "puzzles"),
           ({"form": {**FORM, "attempts": 0}}, "attempts"),
           ({"form": {**FORM, "models": ["nope"]}}, "nope"),
           ({"form": {**FORM, "id": "bad id"}}, "id"),
           ({"form": FORM, "parallel": 0}, "parallel"),
           ({"form": FORM, "parallel": 17}, "parallel"),
           ({"form": FORM, "parallel": True}, "parallel"),
           ({"form": "x"}, "form")]
    for body, word in bad:
        status, reply = call(server, "POST", URL, body)
        assert status == 400 and word in reply["error"], (body, reply)
    assert call(server, "POST", URL, LIVE, token=False)[0] in (401, 403)


def test_warm_call_is_fast(server):
    form = {**FORM, "models": ["example-model", "cloud-model"], "attempts": 2}
    assert call(server, "POST", URL, {"form": form})[0] == 200
    start = time.perf_counter()
    assert call(server, "POST", URL, {"form": {**form, "attempts": 3}})[0] == 200
    assert time.perf_counter() - start < 0.5


def test_done_and_spent_equal_the_run_path(server, tmp_path):
    import tomllib
    from src.run.budget import spent_by_model
    from src.run.models import DECISION_PROVIDERS  # noqa: F401
    ids = [r["input_id"] for r in inputs_of(server)]
    records = [record("example-model", ids[0], "no_model", tokens=300_000),
               record("example-model", ids[0], "descriptive", tokens=123_456),
               record("example-model", ids[1], "prescriptive", number=2, tokens=7),
               {**record("example-model", ids[1], "no_model"), "retry_input_tokens": 5000, "retry_output_tokens": 900}]
    form = {**FORM, "attempts": 2}
    put_branch(server.root, "t1", {"results/t1/experiment.toml": dumps_config(config_of(form, server)),
                                   **raw_files(records)}, where="local")
    status, body = call(server, "POST", URL, {"form": form})
    assert status == 200, body
    config = config_of(form, server)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for path, text in raw_files(records).items():
        (raw_dir / path.rsplit("/", 1)[1]).write_text(text)
    prices = tomllib.loads((server.root / "config" / "prices.toml").read_text())
    pending = list(pending_attempts(config, [r for r in inputs_of(server)], raw_dir, None))
    assert body["counts"]["to_run"] == len(pending)
    assert body["counts"]["done"] == body["counts"]["planned"] - len(pending) == 4
    assert abs(body["models"][0]["spent_usd"] - spent_by_model(config, prices, raw_dir)["example-model"]) < 1e-9
    assert "raw_response" not in repr(server.app.live_estimate._experiments)


def test_unreadable_branch_is_400(server):
    bad = record("example-model", "x", "no_model")
    del bad["latency_s"]
    put_branch(server.root, "t1", {"results/t1/experiment.toml": dumps_config(config_of(FORM, server)),
                                   **raw_files([bad])}, where="local")
    status, body = call(server, "POST", URL, LIVE)
    assert status == 400 and "latency_s" in body["error"]


def test_price_missing_a_field_is_400(server):
    root = server.root
    (root / "config" / "prices.toml").write_text("[example-model]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = \"free\"\n")
    commit_all(root, "partial price")
    git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
    status, body = call(server, "POST", URL, LIVE)
    assert status == 400 and "example-model" in body["error"] and "price_output_per_mtok" in body["error"]


def test_a_push_to_main_outside_the_release_keeps_the_prompts(server):
    est = server.app.live_estimate
    assert call(server, "POST", URL, LIVE)[0] == 200
    held = next(iter(est._releases.values()))
    count = len(held["prompts"])
    assert count
    (server.root / "docs.txt").write_text("a docs change")
    commit_all(server.root, "docs")
    git(server.root, "push", "-q", "origin", "HEAD:refs/heads/main")
    assert call(server, "POST", URL, LIVE)[0] == 200
    assert len(est._releases) == 1 and next(iter(est._releases.values())) is held
