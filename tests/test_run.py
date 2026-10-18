# Spec: docs/specs/run.md
"""Tests for run. Each test builds a tiny release in a temporary git repo (the helper from
test_release), then calls run's main() in-process from inside that repo with the fake provider.
"""

import json

import pytest

from src.run import models, run as run_module
from src.run.models import InfrastructureError, Reply
from src.run.raw import read_raw
from test_release import release_ok, repo  # noqa: F401  (repo is a fixture)

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
    assert not (exp / "results/exp").exists()
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


def test_torn_last_line_resumes(exp):
    go("--model", "A", "--limit", "2")
    path = exp / "results/exp/raw/A.jsonl"
    with open(path, "ab") as handle:
        handle.write(b'{"input_id": "torn')
    assert go("--model", "A", "--limit", "1") == 0
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[2] == '{"input_id": "torn' and len(lines) == 4
    assert json.loads(lines[3])["setup"] == "descriptive"
    assert go("--model", "A") == 0  # the fragment does not block later runs


def test_torn_middle_line_ending_in_brace_resumes(exp):
    go("--model", "A", "--limit", "2")
    path = exp / "results/exp/raw/A.jsonl"
    first, second = path.read_text(encoding="utf-8").splitlines()
    path.write_text(first + '\n{"input_id": "x", "n": {"a": 1}\n' + second + "\n", encoding="utf-8")
    assert go("--model", "A", "--limit", "1") == 0
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4 and lines[1].startswith('{"input_id": "x"')
    assert json.loads(lines[3])["setup"] == "descriptive"


def test_read_raw_skips_and_counts_unparseable_lines(tmp_path):
    path = tmp_path / "A.jsonl"
    path.write_text('{"a": 1}\nnot json\n[1]\n{"b": {"c": 2}\n{"d": 3}\n', encoding="utf-8")
    assert read_raw(path) == ([{"a": 1}, {"d": 3}], 3)
    assert read_raw(tmp_path / "missing.jsonl") == ([], 0)


@pytest.mark.parametrize("field", ["files", "assessment_sha256", "prompt_versions", "input_set_id", "release_config"])
def test_missing_manifest_field_refused(exp, capsys, field):
    path = exp / "releases/1.0.0/manifest.json"
    path.chmod(0o644)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest[field]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go() == 1
    err = capsys.readouterr().err
    assert "manifest.json" in err and field in err
    assert len(models.FAKE_REPLIES) == 1 and not (exp / "results/exp").exists()


# Budgets. Price 0 for input and 100 USD per million output tokens, with max_output_tokens = 100,
# make every worst-case request cost 0.01 USD, and a reply of 100 output tokens cost 0.01 USD.
CENT_PRICES = "".join(f"[{n}]\nprice_input_per_mtok = 0.0\nprice_output_per_mtok = 100.0\n" for n in "AB")


def cent_replies():
    return [Reply('{"moves": [], "mismatch": false}', "ok", "s", 0, 100, 0.1) for _ in range(200)]


def with_budget(repo, **limits):
    path = repo / "config" / "experiments" / "exp.toml"
    text = EXPERIMENT + "[budget]\n" + "".join(f"{k} = {v}\n" for k, v in limits.items())
    path.write_text(text, encoding="utf-8")
    (repo / "config" / "prices.toml").write_text(CENT_PRICES, encoding="utf-8")
    models.FAKE_REPLIES[:] = cent_replies()
    return text


def test_model_budget_stops_then_a_higher_budget_resumes(exp, capsys):
    with_budget(exp, per_model_usd=0.035)
    assert go() == 1
    assert len(records(exp, "A")) == 3 and len(models.FAKE_REPLIES) == 197
    err = capsys.readouterr().err
    assert "per_model_usd 0.035 for model A" in err
    assert "spent 0.0300, next request up to 0.0100" in err and f"{input_count(exp) * 12 - 3} attempts left" in err
    text = with_budget(exp, per_model_usd=1.00)
    models.FAKE_REPLIES[:] = cent_replies()
    assert go() == 0
    expected = input_count(exp) * 3 * 2
    assert len(records(exp, "A")) == expected and len(records(exp, "B")) == expected
    assert (exp / "results/exp/experiment.toml").read_text() == text


def test_experiment_budget_is_shared_between_models(exp, capsys):
    with_budget(exp, per_experiment_usd=0.045)
    assert go("--model", "B", "--limit", "2") == 0
    assert go() == 1
    assert len(records(exp, "A")) == 2 and len(records(exp, "B")) == 2  # 4 calls in total
    assert "per_experiment_usd 0.045" in capsys.readouterr().err


def test_experiment_budget_stops_with_two_models_in_one_run(exp, capsys):
    with_budget(exp, per_experiment_usd=0.045)
    assert go() == 1
    assert len(models.FAKE_REPLIES) == 196
    assert "per_experiment_usd" in capsys.readouterr().err


def test_request_budget_refused_before_any_call(exp, capsys):
    with_budget(exp, per_request_usd=0.005)
    assert go() == 1
    assert len(models.FAKE_REPLIES) == 200 and not (exp / "results/exp").exists()
    err = capsys.readouterr().err
    assert "'A'" in err and "per_request_usd" in err


def test_default_budget_and_a_budget_only_change(exp):
    assert go("--limit", "1") == 0  # no [budget] table: defaults apply
    text = with_budget(exp, per_experiment_usd=20)
    assert go("--limit", "1") == 0
    assert (exp / "results/exp/experiment.toml").read_text() == text
    path = exp / "config/experiments/exp.toml"
    path.write_text(text.replace("attempts = 2", "attempts = 3"))
    assert go() == 1  # a change outside [budget] is still refused


def test_dry_run_leaves_the_experiment_copy_alone(exp):
    go("--limit", "1")
    with_budget(exp, per_experiment_usd=20)
    assert go("--dry-run") == 0
    assert (exp / "results/exp/experiment.toml").read_text() == EXPERIMENT


def test_model_without_a_price_refused_before_any_call(exp, capsys):
    (exp / "config/prices.toml").write_text(PRICES.split("[B]")[0], encoding="utf-8")
    models.FAKE_REPLIES[:] = cent_replies()
    assert go() == 1
    assert len(models.FAKE_REPLIES) == 200 and not (exp / "results/exp").exists()
    assert "'B'" in capsys.readouterr().err


def test_estimate_shows_spent_against_budgets(exp, capsys):
    with_budget(exp, per_model_usd=1.0)
    go("--model", "A", "--limit", "3")
    capsys.readouterr()
    assert go("--estimate") == 0
    out = capsys.readouterr().out
    assert "spent $0.0300 of per_model_usd 1.0" in out
    assert "spent $0.0300 of per_experiment_usd 10.0" in out


def test_budget_checked_before_each_retry(exp, capsys):
    # Each failed call carries 100 output tokens (0.01 USD). Room for one request only.
    with_budget(exp, per_model_usd=0.015)
    models.FAKE_REPLIES[:] = [InfrastructureError("x", 0, 100) for _ in range(10)]
    assert go("--model", "A") == 1
    (row,) = records(exp, "A")
    assert row["outcome"] == "infrastructure_failure" and row["raw_response"] == ""
    assert (row["retry_input_tokens"], row["retry_output_tokens"]) == (0, 100)
    assert len(models.FAKE_REPLIES) == 9  # one call made, no retry
    assert "per_model_usd" in capsys.readouterr().err
