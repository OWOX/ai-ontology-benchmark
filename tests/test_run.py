# Spec: docs/specs/run.md
"""Tests for run. Each test builds a tiny release in a temporary git repo (the helper from
test_release), then calls run's main() in-process from inside that repo with the fake provider.
"""

import json

import pytest

from src.run import models, run as run_module
from src.run.models import InfrastructureError, Reply
from test_release import edit, release_ok, repo  # noqa: F401  (repo is a fixture)

EXPERIMENT = (
    'release = "1.0.0"\nattempts = 2\nretry_cap = 3\nmax_output_tokens = 100\n'
    '[[models]]\nname = "A"\nprovider = "fake"\napi_model_id = "a-1"\n'
    '[[models]]\nname = "B"\nprovider = "fake"\napi_model_id = "b-1"\n'
)
PRICES = ("[A]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n"
          "[B]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n")
FIELDS = {
    "experiment_id", "release_version", "input_id", "input_set_id", "puzzle", "scramble_depth",
    "validity", "setup", "prompt_version", "model", "seed", "input_seed", "attempt_number",
    "raw_response", "parsed_moves", "outcome", "hallucination", "mismatch", "move_count",
    "input_tokens", "output_tokens", "retry_input_tokens", "retry_output_tokens", "latency_s",
    "stop_reason", "served_model", "created_at",
}


@pytest.fixture
def exp(repo, monkeypatch):
    release_ok(repo, "major")
    (repo / "config" / "experiments").mkdir()
    (repo / "config" / "experiments" / "exp.toml").write_text(EXPERIMENT, encoding="utf-8")
    (repo / "config" / "prices.toml").write_text(PRICES, encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(models, "FAKE_REPLIES", [])
    return repo


def go(*extra):
    return run_module.main(["--experiment", "exp", *extra])


def records(repo, name):
    path = repo / "results" / "exp" / "raw" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def input_count(repo):
    return len((repo / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines())


def stable(rows):
    return [{k: v for k, v in r.items() if k not in ("created_at", "latency_s")} for r in rows]


def test_full_run_count(exp, capsys):
    assert go() == 0
    expected = input_count(exp) * 3 * 2
    assert len(records(exp, "A")) == expected and len(records(exp, "B")) == expected
    assert (exp / "results/exp/experiment.toml").read_text() == EXPERIMENT
    assert "new attempts" in capsys.readouterr().out


def test_second_run_adds_nothing(exp):
    go()
    before = (exp / "results/exp/raw/A.jsonl").read_bytes()
    assert go() == 0
    assert (exp / "results/exp/raw/A.jsonl").read_bytes() == before


def test_limit_then_resume_equals_full_run(exp):
    assert go("--limit", "5") == 0
    assert len(records(exp, "A")) == 5
    go()
    resumed = {n: stable(records(exp, n)) for n in "AB"}
    (exp / "results/exp/raw/A.jsonl").unlink()
    (exp / "results/exp/raw/B.jsonl").unlink()
    go()
    assert {n: stable(records(exp, n)) for n in "AB"} == resumed


def test_model_flag_writes_one_file(exp):
    assert go("--model", "A") == 0
    assert sorted(p.name for p in (exp / "results/exp/raw").iterdir()) == ["A.jsonl"]


def test_infrastructure_failure_after_cap(exp):
    models.FAKE_REPLIES[:] = [InfrastructureError("x", 7, 2) for _ in range(5)]
    assert go("--model", "A", "--limit", "1") == 0
    (row,) = records(exp, "A")
    assert row["outcome"] == "infrastructure_failure" and row["raw_response"] == ""
    assert row["stop_reason"] == "infrastructure_failure" and row["latency_s"] is None
    assert row["retry_input_tokens"] == 28 and row["retry_output_tokens"] == 8
    assert (row["input_tokens"], row["output_tokens"], row["served_model"]) == (0, 0, "")
    assert len(models.FAKE_REPLIES) == 1  # 4 calls made


def test_retry_then_success_sums_retry_tokens(exp):
    models.FAKE_REPLIES[:] = [InfrastructureError("x", 5, 1), Reply("{}", "ok", "s", 10, 3, 0.5)]
    go("--model", "A", "--limit", "1")
    (row,) = records(exp, "A")
    assert (row["retry_input_tokens"], row["retry_output_tokens"], row["input_tokens"]) == (5, 1, 10)


def test_malformed_output_not_retried(exp):
    models.FAKE_REPLIES[:] = [Reply("not json", "ok", "s", 1, 1, 0.1), Reply("x", "ok", "s", 1, 1, 0.1)]
    go("--model", "A", "--limit", "1")
    (row,) = records(exp, "A")
    assert row["outcome"] == "malformed_output" and len(models.FAKE_REPLIES) == 1


def refused_before_call(exp, capsys):
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go() == 1
    assert len(models.FAKE_REPLIES) == 1
    assert not (exp / "results/exp/raw").exists()
    assert capsys.readouterr().err.startswith("error:")


def test_changed_inputs_refused(exp, capsys):
    path = exp / "releases/1.0.0/inputs.jsonl"
    path.chmod(0o644)
    path.write_bytes(path.read_bytes().replace(b"2x2", b"2x3", 1))
    refused_before_call(exp, capsys)


def test_changed_validator_refused(exp, capsys):
    path = exp / "src/validator.py"
    path.write_text(path.read_text() + "\n# x\n")
    refused_before_call(exp, capsys)


def test_changed_render_refused(exp, capsys, monkeypatch):
    from src.puzzles.registry import get_engine
    # Patch the instance: an earlier test can leave a shadowing attribute on it.
    monkeypatch.setattr(get_engine("2x2"), "render", lambda state: "changed " + state)
    refused_before_call(exp, capsys)


def test_changed_experiment_refused(exp, capsys):
    go("--limit", "1")
    path = exp / "config/experiments/exp.toml"
    path.write_text(path.read_text().replace("attempts = 2", "attempts = 3"))
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go() == 1
    assert len(models.FAKE_REPLIES) == 1


def test_record_fields(exp):
    go("--limit", "3")
    for row in records(exp, "A"):
        assert set(row) == FIELDS
    assert row["release_version"] == "1.0.0" and row["seed"] == 7 and row["input_set_id"] == "1"


def test_dry_run_and_estimate_write_and_call_nothing(exp, capsys):
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go("--dry-run") == 0
    assert not (exp / "results").exists()
    capsys.readouterr()
    assert go("--estimate") == 0
    out = capsys.readouterr().out
    assert not (exp / "results").exists() and len(models.FAKE_REPLIES) == 1
    full = input_count(exp) * 3 * 2
    assert f"total: {2 * full} attempts" in out and f"A: {full} attempts" in out
