# Spec: docs/specs/run.md
"""Tests for run. Each test builds a tiny release in a temporary git repo (the helper from
test_release), then calls run's main() in-process from inside that repo with the fake provider.
"""

import csv
import io
import json
import shutil
import sys
import threading
import time

import pytest

from src.evaluate import evaluate as evaluate_module
from src.puzzles.registry import get_engine
from src.release import release as release_module
from src.run import budget as budget_module, models, run as run_module
from src.run.models import InfrastructureError, Reply
from src.run.budget import worst_request, worst_state
from src.run.prompts import build_prompt, load_questions
from src.run.raw import read_raw
from src.validator import offered_reasons
from test_release import commit_all, edit_template, git, release_ok, repo  # noqa: F401  (repo is a fixture)

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
    "stop_reason", "served_model", "decision", "requested_model", "mismatch_reason", "created_at", "batch",
}


@pytest.fixture
def exp(repo, monkeypatch):
    release_ok(repo, "major")
    (repo / "config" / "experiments").mkdir()
    (repo / "config" / "experiments" / "exp.toml").write_text(EXPERIMENT, encoding="utf-8")
    (repo / "config" / "prices.toml").write_text(PRICES, encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(release_module, "REPO_ROOT", repo)  # the assessment is the copy's, not this checkout's
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
    git(exp, "update-ref", "-d", BRANCH)  # a branch holding the records would refuse the empty work tree
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
    assert row["decision"] is False and row["requested_model"] == "a-1"
    assert len(models.FAKE_REPLIES) == 1  # 4 calls made


def test_infrastructure_errors_are_logged_to_stderr_only(exp, capsys):
    models.FAKE_REPLIES[:] = [InfrastructureError("boom " + "z" * 400), InfrastructureError("again"),
                              Reply("U", "ok", "s", 10, 3, 0.5)]
    go("--model", "A", "--limit", "1")
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.startswith("infrastructure error:")]
    assert len(lines) == 2 and len(lines[0]) == 300
    assert lines[0].startswith("infrastructure error: A ") and " no_model attempt 1 call 1: boom" in lines[0]
    assert lines[1].endswith(" call 2: again")
    assert "infrastructure error" not in captured.out


def test_request_error_stops_the_run_with_one_line(exp, capsys):
    message = "anthropic: HTTP 400: You have reached your specified API usage limits."
    models.FAKE_REPLIES[:] = [models.RequestError(message), Reply("U", "ok", "s", 1, 1, 0.1)]
    assert go("--model", "A", "--limit", "1") == 1
    captured = capsys.readouterr()
    assert captured.err.splitlines()[-1] == f"error: {message}"
    assert "Traceback" not in captured.err
    assert len(models.FAKE_REPLIES) == 1  # never retried
    assert not (exp / "results/exp/raw/A.jsonl").exists() or records(exp, "A") == []


def test_retry_then_success_sums_retry_tokens(exp):
    models.FAKE_REPLIES[:] = [InfrastructureError("x", 5, 1), Reply("U", "ok", "s", 10, 3, 0.5)]
    go("--model", "A", "--limit", "1")
    (row,) = records(exp, "A")
    assert (row["retry_input_tokens"], row["retry_output_tokens"], row["input_tokens"]) == (5, 1, 10)


def test_malformed_output_not_retried(exp):
    models.FAKE_REPLIES[:] = [Reply("", "ok", "s", 1, 1, 0.1), Reply("x", "ok", "s", 1, 1, 0.1)]
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
        assert row["decision"] is False and row["requested_model"] == "a-1" and row["batch"] is False
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


@pytest.mark.parametrize("extra", [("--dry-run",), ("--estimate",), ()])
def test_each_prompt_is_rendered_once(exp, monkeypatch, extra):
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)] * 1000
    rendered = []

    def counting(templates, row, setup):
        rendered.append((row["input_id"], setup))
        return build_prompt(templates, row, setup)

    monkeypatch.setattr(run_module, "build_prompt", counting)
    assert go(*extra) == 0
    rows = [json.loads(x) for x in (exp / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = {(row["input_id"], setup) for row in rows for setup in run_module.SETUPS}  # a fresh run: everything is pending
    assert rendered and len(rendered) == len(set(rendered)) and set(rendered) == expected  # two AI models and attempts share one rendering


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
    git(exp, "update-ref", "-d", BRANCH)  # the hand edit is not an append, so drop the branch it would fail against
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


def drop_manifest_field(repo, field):
    path = repo / "releases/1.0.0/manifest.json"
    path.chmod(0o644)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest[field]
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_old_release_without_decision_versions_still_runs_llms(exp):
    drop_manifest_field(exp, "decision_prompt_versions")
    models.FAKE_REPLIES[:] = [Reply("U", "ok", "s", 1, 1, 0.1)] * 200
    assert go() == 0
    assert records(exp, "A")


def test_old_release_refuses_a_decision_model(exp, capsys):
    drop_manifest_field(exp, "decision_prompt_versions")
    config = exp / "config" / "experiments" / "exp.toml"
    config.write_text(EXPERIMENT + '[[models]]\nname = "D"\nprovider = "fake_decision"\napi_model_id = "d-1"\n',
                      encoding="utf-8")
    assert go() == 1
    err = capsys.readouterr().err
    assert "manifest.json" in err and "decision_prompt_versions" in err and "cut after" in err
    assert not (exp / "results/exp").exists()


def test_changed_decision_versions_refused(exp, capsys):
    path = exp / "releases/1.0.0/manifest.json"
    path.chmod(0o644)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["decision_prompt_versions"]["no_model"]["2x2"] = "0" * 12
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert go() == 1
    assert "decision_prompt_versions" in capsys.readouterr().err


# Budgets. Price 0 for input and 100 USD per million output tokens, with max_output_tokens = 100,
# make every worst-case request cost 0.01 USD, and a reply of 100 output tokens cost 0.01 USD.
CENT_PRICES = "".join(f"[{n}]\nprice_input_per_mtok = 0.0\nprice_output_per_mtok = 100.0\n" for n in "AB")


def cent_replies():
    return [Reply("U", "ok", "s", 0, 100, 0.1) for _ in range(200)]


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
    assert "spent $0.0300 of per_experiment_usd 50.0" in out


def test_estimate_dict_takes_spent_and_no_raw_dir():
    config = {"max_output_tokens": 100, "budget": {"per_model_usd": 5.0, "per_experiment_usd": 9.0,
                                                   "per_request_usd": 2.0},
              "models": [{"name": "A", "provider": "openai"}, {"name": "B", "provider": "openai"}]}
    prices = {n: {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0} for n in "AB"}
    a = {"name": "A", "provider": "openai"}
    pending = [({"input_id": "i1", "puzzle": "3x3"}, a, "none", 1),
               ({"input_id": "i2", "puzzle": "3x3"}, a, "none", 1)]
    prompts = {("i1", "none"): "x" * 400, ("i2", "none"): "x" * 40}
    got = budget_module.estimate(config, pending, prices, None, None, {}, prompts, spent={"A": 0.5, "B": 0.25})
    first, second = (100 * 1.0 + 100 * 2.0) / 1e6, (10 * 1.0 + 100 * 2.0) / 1e6
    assert got["models"] == [
        {"name": "A", "attempts": 2, "input_tokens": 110, "worst_case_usd": pytest.approx(first + second),
         "spent_usd": 0.5, "per_model_usd": 5.0, "max_request_usd": pytest.approx(first)},
        {"name": "B", "attempts": 0, "input_tokens": 0, "worst_case_usd": 0, "spent_usd": 0.25,
         "per_model_usd": 5.0, "max_request_usd": 0}]
    assert got["total"] == {"attempts": 2, "worst_case_usd": pytest.approx(first + second),
                            "spent_usd": 0.75, "per_experiment_usd": 9.0}
    assert got["per_request_usd"] == 2.0


def test_estimate_of_a_decision_model_counts_one_call_as_the_largest_request():
    cap, max_output = 5, 100
    config = {"max_output_tokens": max_output,
              "budget": {"per_model_usd": 5.0, "per_experiment_usd": 9.0, "per_request_usd": 2.0},
              "models": [{"name": "D", "provider": "fake_decision"}]}
    prices = {"D": {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0}}
    d = config["models"][0]
    pending = [({"input_id": "i1", "puzzle": "2x2"}, d, "no_model", 1)]
    prompt = "x" * 400
    questions = load_questions(budget_module.Path(__file__).resolve().parent.parent / "prompts")
    got = budget_module.estimate(config, pending, prices, questions, None, {"2x2": cap}, {("i1", "no_model"): prompt},
                                 spent={})
    one_call = budget_module.worst_case_request_cost(
        worst_request(prompt, get_engine("2x2").legal_moves(), cap, questions), max_output, prices["D"])
    (model,) = got["models"]
    assert model["max_request_usd"] == pytest.approx(one_call)
    assert model["worst_case_usd"] == pytest.approx(cap * model["max_request_usd"])
    assert model["spent_usd"] == 0.0 and got["total"]["spent_usd"] == 0.0


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


# Puzzle filter. The release holds 2x2 and 3x3; the experiment may name a subset.

def two_puzzle_exp(repo, monkeypatch, extra=""):
    release = repo / "config" / "release.toml"
    release.write_text(release.read_text(encoding="utf-8").replace('["2x2"]', '["2x2", "3x3"]'), encoding="utf-8")
    from test_release import commit_all
    commit_all(repo, "two puzzles")
    release_ok(repo, "major")
    (repo / "config" / "experiments").mkdir()
    text = EXPERIMENT.replace("attempts = 2\n", "attempts = 2\n" + extra)
    (repo / "config" / "experiments" / "exp.toml").write_text(text, encoding="utf-8")
    (repo / "config" / "prices.toml").write_text(PRICES, encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(models, "FAKE_REPLIES", [])


def test_puzzles_filter_writes_only_those_puzzles(repo, monkeypatch):
    two_puzzle_exp(repo, monkeypatch, 'puzzles = ["2x2"]\n')
    assert go() == 0
    rows = records(repo, "A")
    assert rows and {r["puzzle"] for r in rows} == {"2x2"}
    inputs = [json.loads(x) for x in (repo / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["puzzle"] for r in inputs} == {"2x2", "3x3"}
    assert len(rows) == sum(r["puzzle"] == "2x2" for r in inputs) * 3 * 2


def group(puzzle, depth, valid, invalid):
    rows = [{"input_id": f"{puzzle}-{depth}-v{i}", "puzzle": puzzle, "scramble_depth": depth, "validity": "valid"}
            for i in range(valid)]
    return rows + [{"input_id": f"{puzzle}-{depth}-x{i}", "puzzle": puzzle, "scramble_depth": depth,
                    "validity": "invalid", "source_input_id": f"{puzzle}-{depth}-v{i}"} for i in range(invalid)]


def counts(rows):
    return sum(r["validity"] == "valid" for r in rows), sum(r["validity"] == "invalid" for r in rows)


@pytest.mark.parametrize("k, expected", [(1, (1, 1)), (4, (4, 1)), (5, (5, 2)), (8, (8, 2)), (40, (40, 10)), (100, (40, 10))])
def test_inputs_per_depth_keeps_the_invalid_share_rounded_up(k, expected):
    rows = group("2x2", 5, 40, 10)
    kept = run_module.experiment_inputs({"inputs_per_depth": k}, rows)
    assert counts(kept) == expected
    assert kept == [r for r in rows if r in kept]  # release order
    assert [r["input_id"] for r in kept if r["validity"] == "valid"] == [f"2x2-5-v{i}" for i in range(expected[0])]


def test_inputs_per_depth_with_no_invalid_inputs_keeps_k_valid():
    assert counts(run_module.experiment_inputs({"inputs_per_depth": 3}, group("2x2", 5, 40, 0))) == (3, 0)


def test_no_inputs_per_depth_keeps_everything():
    rows = group("2x2", 5, 4, 1)
    assert run_module.experiment_inputs({}, rows) == rows


def test_puzzles_and_inputs_per_depth_together():
    rows = group("2x2", 5, 8, 2) + group("2x2", 10, 8, 2) + group("3x3", 5, 8, 2)
    kept = run_module.experiment_inputs({"puzzles": ["2x2"], "inputs_per_depth": 4}, rows)
    assert {r["puzzle"] for r in kept} == {"2x2"}
    assert [counts([r for r in kept if r["scramble_depth"] == d]) for d in (5, 10)] == [(4, 1), (4, 1)]
    assert kept == [r for r in rows if r in kept]


def test_interleaved_unsorted_input_keeps_the_first_k_per_depth_in_release_order():
    five, ten = group("2x2", 5, 8, 2), group("2x2", 10, 8, 2)
    rows = [r for pair in zip(reversed(five), reversed(ten)) for r in pair]  # depths alternate, and ids run backwards
    kept = run_module.experiment_inputs({"inputs_per_depth": 4}, rows)
    assert [counts([r for r in kept if r["scramble_depth"] == d]) for d in (5, 10)] == [(4, 1), (4, 1)]
    assert kept == [r for r in rows if r in kept]
    # the first four valid rows of each depth, as they appear: the backwards ids v7 to v4
    assert [r["input_id"] for r in kept if r["validity"] == "valid" and r["scramble_depth"] == 5] == [f"2x2-5-v{i}" for i in (7, 6, 5, 4)]


def test_inputs_per_depth_limits_the_attempts_run(repo, monkeypatch):
    two_puzzle_exp(repo, monkeypatch, "inputs_per_depth = 1\n")
    assert go() == 0
    inputs = [json.loads(x) for x in (repo / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = run_module.experiment_inputs({"inputs_per_depth": 1}, inputs)
    assert {r["input_id"] for r in records(repo, "A")} == {r["input_id"] for r in expected}
    assert len(expected) < len(inputs)


def test_no_puzzles_runs_every_puzzle(repo, monkeypatch):
    two_puzzle_exp(repo, monkeypatch)
    assert go() == 0
    assert {r["puzzle"] for r in records(repo, "A")} == {"2x2", "3x3"}


def test_puzzle_not_in_release_refused_before_any_call(exp, capsys):
    path = exp / "config/experiments/exp.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("attempts = 2\n", 'attempts = 2\npuzzles = ["3x3"]\n'), encoding="utf-8")
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go() == 1
    err = capsys.readouterr().err
    assert "exp.toml" in err and "puzzles" in err
    assert len(models.FAKE_REPLIES) == 1 and not (exp / "results/exp").exists()


# Results branch. Every record is committed to refs/heads/results/exp without touching the work tree.

BRANCH = "refs/heads/results/exp"


def with_remote(repo, tmp_path_factory):
    remote = tmp_path_factory.mktemp("remote")
    git(remote, "init", "-q", "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    return remote


def test_records_are_committed_to_the_results_branch(exp, capsys):
    head, status = git(exp, "rev-parse", "HEAD"), git(exp, "status", "--porcelain", "--untracked-files=no")
    index = git(exp, "ls-files", "--stage")
    assert go() == 0
    for name in "AB":
        shown = git(exp, "show", f"{BRANCH}:results/exp/raw/{name}.jsonl")
        assert shown + "\n" == (exp / "results/exp/raw" / f"{name}.jsonl").read_text(encoding="utf-8")
    assert git(exp, "show", f"{BRANCH}:config/experiments/exp.toml") == EXPERIMENT.strip()
    assert git(exp, "rev-parse", "HEAD") == head
    assert git(exp, "status", "--porcelain", "--untracked-files=no") == status
    assert git(exp, "ls-files", "--stage") == index
    assert "warning: push of results/exp failed: no remote origin" in capsys.readouterr().err


def test_one_commit_per_attempt_plus_the_start(exp):
    assert go() == 0
    attempts = len(records(exp, "A")) + len(records(exp, "B"))
    assert int(git(exp, "rev-list", "--count", f"HEAD..{BRANCH}")) == attempts + 1
    assert git(exp, "log", "-1", "--format=%s", f"{BRANCH}~{attempts}") == "Results: experiment exp, start"


def test_branch_is_pushed_at_exit(exp, tmp_path_factory):
    remote = with_remote(exp, tmp_path_factory)
    assert go() == 0
    assert git(remote, "rev-parse", BRANCH) == git(exp, "rev-parse", BRANCH)
    assert go() == 0  # nothing new: the branch stays as it is
    assert git(remote, "rev-parse", BRANCH) == git(exp, "rev-parse", BRANCH)


def test_run_without_a_remote_still_succeeds(exp, capsys):
    assert go("--limit", "2") == 0
    assert capsys.readouterr().err.strip() == "warning: push of results/exp failed: no remote origin"


def test_budget_stop_commits_and_pushes(exp, capsys, tmp_path_factory):
    remote = with_remote(exp, tmp_path_factory)
    with_budget(exp, per_model_usd=0.035)
    assert go() == 1
    assert len(records(exp, "A")) == 3
    assert git(exp, "show", f"{BRANCH}:results/exp/raw/A.jsonl") + "\n" == \
        (exp / "results/exp/raw/A.jsonl").read_text(encoding="utf-8")
    assert git(remote, "rev-parse", BRANCH) == git(exp, "rev-parse", BRANCH)
    assert capsys.readouterr().err.strip().splitlines()[-1].startswith("error: budget reached:")


def test_budget_error_stays_the_last_line_when_the_push_fails(exp, capsys):
    with_budget(exp, per_model_usd=0.035)
    assert go() == 1
    lines = capsys.readouterr().err.strip().splitlines()
    assert lines[-2].startswith("warning: push of results/exp failed")
    assert lines[-1].startswith("error: budget reached:")


def test_no_commit_dry_run_and_estimate_make_no_branch(exp):
    assert go("--no-commit", "--limit", "2") == 0
    assert go("--dry-run") == 0
    assert go("--estimate") == 0
    assert git(exp, "branch", "--list", "results/exp") == ""


def test_outside_a_git_work_tree_refused_before_any_call(exp, tmp_path_factory, monkeypatch, capsys):
    import shutil
    plain = tmp_path_factory.mktemp("plain")
    for name in ("src", "prompts", "releases", "config"):
        shutil.copytree(exp / name, plain / name)
    monkeypatch.chdir(plain)
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go() == 1
    assert len(models.FAKE_REPLIES) == 1 and not (plain / "results").exists()
    assert "needs a git work tree" in capsys.readouterr().err


# Progress. Plain lines when stdout is not a terminal (capsys), a rich display on a terminal.

def reply(text="U", tokens=(10, 4)):
    return Reply(text, "ok", "s", *tokens, 0.1)


def progress_lines(out):
    return [line for line in out.splitlines() if line.startswith("[")]


def test_plain_progress_line_per_attempt(exp, capsys):
    models.FAKE_REPLIES[:] = [reply(), reply("M"), Reply("", "ok", "s", 10, 4, 0.1)]
    assert go("--model", "A", "--limit", "3", "--no-commit") == 0
    first, second, third = progress_lines(capsys.readouterr().out)
    assert first.startswith("[1/3] A 2x2 ") and " no_model #1 failure | in 10 out 4 | $0.0000 | " in first
    assert first.endswith("balanced precision n/a hallucination 0% malformed 0% truncated 0% abstention 0% format error 0%")
    assert " no_model #2 hallucination | in 20 out 8 | " in second
    assert second.endswith("balanced precision n/a hallucination 50% malformed 0% truncated 0% abstention 0% format error 0%")
    assert " descriptive #1 malformed_output | in 30 out 12 | " in third and third.startswith("[3/3] A ")
    assert third.endswith("balanced precision n/a hallucination 50% malformed 33% truncated 0% abstention 0% format error 0%")


def test_progress_counts_prior_records(exp, capsys):
    go("--model", "A", "--limit", "2", "--no-commit")
    capsys.readouterr()
    go("--model", "A", "--limit", "1", "--no-commit")
    (line,) = progress_lines(capsys.readouterr().out)
    assert line.startswith("[3/3] A ")  # two prior records counted


def test_progress_rates_leave_out_infrastructure_failures(exp, capsys):
    models.FAKE_REPLIES[:] = [InfrastructureError("x", 0, 0) for _ in range(4)] + [reply()]
    go("--model", "A", "--limit", "2", "--no-commit")
    first, second = progress_lines(capsys.readouterr().out)
    assert "infrastructure_failure" in first and first.endswith("balanced precision n/a hallucination n/a malformed n/a truncated n/a abstention n/a format error n/a")
    assert second.endswith("balanced precision n/a hallucination 0% malformed 0% truncated 0% abstention 0% format error 0%")


def test_no_progress_for_dry_run_and_estimate(exp, capsys):
    go("--dry-run")
    go("--estimate")
    assert progress_lines(capsys.readouterr().out) == []


def test_rich_progress_smoke(exp):
    import io
    from rich.console import Console
    from src.config import load_experiment_config, load_prices
    from src.run.progress import Progress
    config = load_experiment_config(exp / "config/experiments/exp.toml")
    prices = load_prices(exp / "config/prices.toml")
    go("--model", "A", "--limit", "3", "--no-commit")
    rows = records(exp, "A")
    totals = {("A", rows[0]["puzzle"]): 5, ("B", rows[0]["puzzle"]): 5}
    out = io.StringIO()
    shown = Progress(config, prices, totals, rows[:1], console=Console(file=out, force_terminal=True, width=200))
    with shown:
        for row in rows[1:]:
            shown.update(row)
    text = out.getvalue()
    assert "A 2x2" in text and "B 2x2" in text and "total" in text and "last attempt" in text


# Fix round: sync with origin, removals, temporary files, commit failures, interrupts.

def test_a_file_missing_from_the_work_tree_survives_the_commit(exp):
    assert go() == 0
    (exp / "results/exp/raw/A.jsonl").unlink()
    (exp / "results/exp/.experiment.toml.99.tmp").write_text("x", encoding="utf-8")
    assert go("--model", "B") == 0
    names = git(exp, "ls-tree", "-r", "--name-only", BRANCH).splitlines()
    assert "results/exp/raw/A.jsonl" in names and "results/exp/raw/B.jsonl" in names


def test_a_work_tree_behind_the_branch_is_refused_before_any_write_or_call(exp, capsys):
    assert go() == 0
    raw = exp / "results/exp/raw/A.jsonl"
    full = raw.read_bytes()
    raw.write_bytes(full.splitlines(keepends=True)[0])
    tip = git(exp, "rev-parse", BRANCH)
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go() == 1
    assert len(models.FAKE_REPLIES) == 1 and git(exp, "rev-parse", BRANCH) == tip
    assert raw.read_bytes() == full.splitlines(keepends=True)[0]
    err = capsys.readouterr().err
    assert "results/exp/raw/A.jsonl on results/exp holds records this checkout lacks" in err
    assert "git restore --source=results/exp --worktree -- results/exp" in err and "uncommitted" in err
    raw.unlink()  # a missing file of a model in scope is just as stale
    assert go() == 1 and not raw.exists()
    assert go("--model", "B") == 0  # A is out of scope
    assert go("--no-commit") == 0  # no branch work, no check


def test_a_fresh_checkout_names_the_remote_branch(exp, tmp_path_factory, capsys):
    with_remote(exp, tmp_path_factory)
    assert go() == 0
    git(exp, "update-ref", "-d", BRANCH)  # only origin/results/exp is left
    raw = exp / "results/exp/raw/A.jsonl"
    raw.write_bytes(raw.read_bytes().splitlines(keepends=True)[0])
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go() == 1 and len(models.FAKE_REPLIES) == 1
    err = capsys.readouterr().err
    assert "results/exp/raw/A.jsonl on origin/results/exp holds records this checkout lacks" in err
    assert "git restore --source=origin/results/exp --worktree -- results/exp" in err


def test_a_work_tree_that_extends_the_branch_runs(exp):
    assert go() == 0
    raw = exp / "results/exp/raw/A.jsonl"
    raw.write_bytes(raw.read_bytes() + b"\n")
    assert go() == 0


def test_temporary_copies_are_never_committed(exp):
    (exp / "results/exp").mkdir(parents=True)
    (exp / "results/exp/.experiment.toml.99.tmp").write_text("x", encoding="utf-8")
    assert go("--limit", "1") == 0
    assert not [n for n in git(exp, "ls-tree", "-r", "--name-only", BRANCH).splitlines() if n.endswith(".tmp")]


def test_a_stale_local_branch_is_fast_forwarded_to_origin(exp, tmp_path_factory):
    with_remote(exp, tmp_path_factory)
    assert go() == 0
    tip = git(exp, "rev-parse", BRANCH)
    git(exp, "update-ref", BRANCH, f"{BRANCH}~3")
    assert go() == 0
    assert git(exp, "rev-parse", BRANCH) == tip


def test_a_diverged_branch_is_refused_before_any_call(exp, tmp_path_factory, capsys):
    with_remote(exp, tmp_path_factory)
    assert go() == 0
    tree = git(exp, "rev-parse", f"{BRANCH}^{{tree}}")
    git(exp, "update-ref", BRANCH, git(exp, "commit-tree", tree, "-p", f"{BRANCH}~1", "-m", "local only"))
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    (exp / "results/exp/raw/A.jsonl").unlink()
    assert go() == 1
    assert len(models.FAKE_REPLIES) == 1
    err = capsys.readouterr().err
    assert "diverged" in err and BRANCH in err and "refs/remotes/origin/results/exp" in err


def test_a_commit_failure_warns_and_the_budget_line_stays_last(exp, capsys, monkeypatch):
    from src.run.branch import BranchError, ResultsBranch

    def boom(self, message):
        raise BranchError("boom")

    monkeypatch.setattr(ResultsBranch, "commit", boom)
    with_budget(exp, per_model_usd=0.035)
    assert go() == 1
    lines = capsys.readouterr().err.strip().splitlines()
    assert any(l.startswith("warning: commit of results/exp failed: boom") for l in lines)
    assert lines[-1].startswith("error: budget reached:")
    assert len(records(exp, "A")) == 3


def interrupt_on_third_record(monkeypatch, how):
    real, calls = run_module.append_record, []

    def append(path, record):
        calls.append(1)
        if len(calls) == 3:
            how()
        real(path, record)

    monkeypatch.setattr(run_module, "append_record", append)


def test_interrupt_commits_and_pushes_what_was_written(exp, tmp_path_factory, monkeypatch):
    remote = with_remote(exp, tmp_path_factory)

    def stop():
        raise KeyboardInterrupt

    interrupt_on_third_record(monkeypatch, stop)
    with pytest.raises(KeyboardInterrupt):
        go("--model", "A")
    assert len(records(exp, "A")) == 2
    assert git(exp, "show", f"{BRANCH}:results/exp/raw/A.jsonl") + "\n" == \
        (exp / "results/exp/raw/A.jsonl").read_text(encoding="utf-8")
    assert git(remote, "rev-parse", BRANCH) == git(exp, "rev-parse", BRANCH)


def test_sigterm_unwinds_with_a_non_zero_exit_and_pushes(exp, tmp_path_factory, monkeypatch):
    import os
    import signal
    remote = with_remote(exp, tmp_path_factory)
    before = signal.getsignal(signal.SIGTERM)
    interrupt_on_third_record(monkeypatch, lambda: os.kill(os.getpid(), signal.SIGTERM))
    with pytest.raises(SystemExit) as stopped:
        go("--model", "A")
    assert stopped.value.code == 128 + signal.SIGTERM
    assert git(remote, "rev-parse", BRANCH) == git(exp, "rev-parse", BRANCH)
    assert signal.getsignal(signal.SIGTERM) == before  # the handler is put back


# Config on stdin. `--config -` reads the experiment config from stdin and needs no file.

def stdin_run(exp, monkeypatch, text, *extra):
    (exp / "config" / "experiments" / "exp.toml").unlink()
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    return go("--config", "-", *extra)


def test_config_from_stdin_writes_no_config_file(exp, monkeypatch):
    assert stdin_run(exp, monkeypatch, EXPERIMENT) == 0
    assert list((exp / "config" / "experiments").iterdir()) == []
    assert (exp / "results/exp/experiment.toml").read_text(encoding="utf-8") == EXPERIMENT
    assert len(records(exp, "A")) == len(records(exp, "B")) > 0
    assert git(exp, "show", f"{BRANCH}:results/exp/experiment.toml") == EXPERIMENT.strip()


def test_broken_stdin_config_refused_before_any_write(exp, monkeypatch, capsys):
    assert stdin_run(exp, monkeypatch, 'release = "1.0.0"\n') == 1
    assert "<stdin>" in capsys.readouterr().err
    assert not (exp / "results").exists()


# Decision models. One model, one attempt per setup, driven by models.FAKE_DECISION_REPLIES.

DECISION_EXPERIMENT = (
    'release = "1.0.0"\nattempts = 1\nretry_cap = 3\nmax_output_tokens = 100\n'
    '[[models]]\nname = "D"\nprovider = "fake_decision"\napi_model_id = "d-1"\n'
)


def decision_exp(repo, monkeypatch, config=DECISION_EXPERIMENT, prices="[D]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n"):
    (repo / "config" / "experiments" / "exp.toml").write_text(config, encoding="utf-8")
    (repo / "config" / "prices.toml").write_text(prices, encoding="utf-8")
    monkeypatch.setattr(models, "FAKE_DECISION_REPLIES", [])
    return models.FAKE_DECISION_REPLIES


def d_reply(choice, tokens=(10, 0), model="d-served", latency=0.25):
    call = {"answers": {"next_move": {"type": "choice", "choice": choice}},
            "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}, "model": model}
    return models.DecisionReply(call, tokens[0], tokens[1], model, latency)


def solving_replies(repo):
    """The replies that undo the first input's scramble, then say done."""
    first = json.loads((repo / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["validity"] == "valid"
    legal = get_engine(first["puzzle"]).legal_moves()
    undo = [m[:-1] if m.endswith("'") else m if m.endswith("2") else m + "'" for m in reversed(first["scramble"])]
    return [d_reply(f"move_{legal.index(m) + 1}") for m in undo] + [d_reply("done")]


def test_decision_model_end_to_end(exp, monkeypatch):
    fake = decision_exp(exp, monkeypatch)
    solved = solving_replies(exp)
    fake[:] = [*solved, models.DecisionReply({}, 3, 0, "d-served", 0.1),
               *[InfrastructureError("x", 5, 1) for _ in range(4)]]
    assert go("--limit", "3") == 0
    solved_row, malformed_row, failed_row = records(exp, "D")
    assert solved_row["outcome"] == "success" and solved_row["hallucination"] is False
    assert len(json.loads(solved_row["raw_response"])) == len(solved)
    assert solved_row["input_tokens"] == 10 * len(solved) and solved_row["served_model"] == "d-served"
    assert solved_row["latency_s"] == pytest.approx(0.25 * len(solved)) and solved_row["stop_reason"] == "ok"
    assert solved_row["prompt_version"] == json.loads(
        (exp / "releases/1.0.0/manifest.json").read_text(encoding="utf-8"))["decision_prompt_versions"]["no_model"]["2x2"]
    assert malformed_row["outcome"] == "malformed_output" and json.loads(malformed_row["raw_response"]) == [{}]
    assert failed_row["outcome"] == "infrastructure_failure" and failed_row["raw_response"] == ""
    assert (failed_row["retry_input_tokens"], failed_row["retry_output_tokens"]) == (20, 4)
    assert failed_row["latency_s"] is None and failed_row["served_model"] == "" and failed_row["input_tokens"] == 0
    assert set(solved_row) == FIELDS
    for decision_row in (solved_row, malformed_row, failed_row):
        assert decision_row["decision"] is True and decision_row["requested_model"] == "d-1"
    assert evaluate_module.main(["--experiment", "exp"]) == 0
    with open(exp / "results/exp/1.0.0.metrics.csv", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_setup = {r["setup"]: r for r in rows if r["model"] == "D"}
    assert by_setup["no_model"]["precision"] == "1.0000" and by_setup["no_model"]["hallucination_rate"] == "n/a"
    assert by_setup["descriptive"]["malformed_output_rate"] == "1.0000"
    assert by_setup["prescriptive"]["infrastructure_failure_count"] == "1"
    assert by_setup["prescriptive"]["precision_n"] == "0" and by_setup["prescriptive"]["input_tokens_per_attempt"] == "20.0000"


def test_decision_reply_without_a_model_keeps_served_empty_and_requests_the_entry_id(exp, monkeypatch):
    fake = decision_exp(exp, monkeypatch)
    fake[:] = [d_reply("done", model="")]
    assert go("--limit", "1") == 0
    (row,) = records(exp, "D")
    assert row["served_model"] == "" and row["requested_model"] == "d-1" and row["decision"] is True


def test_decision_mismatch_choice_ends_the_attempt_and_sets_the_flag(exp, monkeypatch):
    fake = decision_exp(exp, monkeypatch)
    fake[:] = [d_reply("move_1"), d_reply("mismatch_1"), d_reply("done")]
    assert go("--limit", "1") == 0
    (row,) = records(exp, "D")
    assert row["mismatch"] is True and len(json.loads(row["raw_response"])) == 2 and len(fake) == 1
    assert row["mismatch_reason"] == offered_reasons(get_engine(row["puzzle"]))[0]


def test_decision_infrastructure_failure_keeps_the_completed_calls(exp, monkeypatch):
    fake = decision_exp(exp, monkeypatch)
    fake[:] = [d_reply("move_1", tokens=(7, 1)), *[InfrastructureError("x", 2, 0) for _ in range(4)]]
    assert go("--limit", "1") == 0
    (row,) = records(exp, "D")
    assert row["outcome"] == "infrastructure_failure" and row["stop_reason"] == "infrastructure_failure"
    assert len(json.loads(row["raw_response"])) == 1 and (row["input_tokens"], row["output_tokens"]) == (7, 1)
    assert row["retry_input_tokens"] == 8 and row["served_model"] == "d-served"


def test_decision_budget_stop_mid_attempt_writes_the_record_then_stops(exp, monkeypatch, capsys):
    prices = "[D]\nprice_input_per_mtok = 0.0\nprice_output_per_mtok = 100.0\n"
    fake = decision_exp(exp, monkeypatch, DECISION_EXPERIMENT + "[budget]\nper_model_usd = 0.015\n", prices)
    fake[:] = [d_reply("move_1", tokens=(0, 0)), InfrastructureError("x", 0, 100), d_reply("done")]
    assert go("--limit", "2") == 1
    (row,) = records(exp, "D")  # the second attempt is never started
    assert row["outcome"] == "infrastructure_failure" and len(json.loads(row["raw_response"])) == 1
    assert row["retry_output_tokens"] == 100 and len(fake) == 1
    assert capsys.readouterr().err.strip().splitlines()[-1].startswith("error: budget reached:")


def test_decision_budget_counts_the_completed_calls_of_the_attempt(exp, monkeypatch):
    # 100 output tokens cost 0.01 USD, as does the worst case of one call: room for two calls only.
    prices = "[D]\nprice_input_per_mtok = 0.0\nprice_output_per_mtok = 100.0\n"
    fake = decision_exp(exp, monkeypatch, DECISION_EXPERIMENT + "[budget]\nper_model_usd = 0.025\n", prices)
    fake[:] = [d_reply("move_1", tokens=(0, 100)), d_reply("move_1", tokens=(0, 100)), d_reply("done")]
    assert go("--limit", "1") == 1
    (row,) = records(exp, "D")
    assert len(json.loads(row["raw_response"])) == 2 and row["output_tokens"] == 200
    assert row["outcome"] == "infrastructure_failure" and len(fake) == 1


def test_decision_dry_run_prints_the_first_state_and_questions(exp, monkeypatch, capsys):
    fake = decision_exp(exp, monkeypatch)
    fake[:] = [d_reply("done")]
    assert go("--dry-run", "--limit", "1") == 0
    out = capsys.readouterr().out
    assert "Moves so far: none" in out and "--- questions" in out and '"move_1"' in out
    assert len(fake) == 1 and not (exp / "results").exists()


def test_decision_estimate_is_cap_calls_of_the_longest_state(exp, monkeypatch, capsys):
    decision_exp(exp, monkeypatch)
    rows = [json.loads(line) for line in (exp / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    for cap, text in ((6, DECISION_EXPERIMENT),  # default: twice the largest scramble depth, 3
                      (1, DECISION_EXPERIMENT.replace("[[models]]", "max_moves = 1\n[[models]]", 1))):
        (exp / "config" / "experiments" / "exp.toml").write_text(text, encoding="utf-8")
        assert go("--estimate") == 0
        line = capsys.readouterr().out.splitlines()[0]
        expected = 0.0
        for row in rows:
            for setup in run_module.SETUPS:
                state = worst_request(build_prompt(exp / "releases/1.0.0/prompts", row, setup),
                                      get_engine(row["puzzle"]).legal_moves(), cap,
                                      load_questions(exp / "releases/1.0.0/prompts"),
                                      offered_reasons(get_engine(row["puzzle"])))
                expected += cap * (-(-len(state) // 4) * 1.0 + 100 * 2.0) / 1e6
        assert f"worst case ${expected:.4f}" in line


def test_decision_request_budget_counts_the_questions(exp, monkeypatch, capsys):
    folder = exp / "releases/1.0.0/prompts"
    rows = [json.loads(line) for line in (exp / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    states = [-(-len(worst_state(build_prompt(folder, r, s), get_engine(r["puzzle"]).legal_moves(), 6)) // 4)
              for r in rows for s in run_module.SETUPS]
    # Input tokens cost 1 USD each and output tokens nothing: the limit fits every state, not state plus questions.
    decision_exp(exp, monkeypatch, DECISION_EXPERIMENT + f"[budget]\nper_request_usd = {max(states)}\n",
                 "[D]\nprice_input_per_mtok = 1000000.0\nprice_output_per_mtok = 0.0\n")
    assert go() == 1
    assert "per_request_usd" in capsys.readouterr().err


def test_decision_attempt_reads_spent_cost_once(exp, monkeypatch):
    fake = decision_exp(exp, monkeypatch)
    solved = solving_replies(exp)
    fake[:] = list(solved)
    reads = []
    real = run_module.spent_by_model
    monkeypatch.setattr(run_module, "spent_by_model", lambda *a: reads.append(1) or real(*a))
    monkeypatch.setattr(budget_module, "spent_by_model", lambda *a: reads.append(1) or real(*a))
    assert go("--limit", "1") == 0
    assert len(json.loads(records(exp, "D")[0]["raw_response"])) == len(solved) > 1
    assert len(reads) == 1


# Parallel requests. The fake provider is wrapped at run's call_model, so each test controls timing.

class Gate:
    """Wraps call_model: counts calls in flight, notes the first arrivals, and holds them until `hold` have arrived."""

    def __init__(self, monkeypatch, hold=0, sleep=0.0, block_after=None, block_for=5.0):
        self.real, self.lock, self.hold, self.sleep = run_module.call_model, threading.Lock(), hold, sleep
        self.block_after, self.block_for = block_after, block_for
        self.arrived, self.now, self.peak, self.calls = [], 0, 0, 0
        self.full, self.release = threading.Event(), threading.Event()
        monkeypatch.setattr(run_module, "call_model", self)

    def __call__(self, model, prompt, max_output_tokens, reasoning_effort=None):
        with self.lock:
            self.calls += 1
            number = self.calls
            self.now += 1
            self.peak = max(self.peak, self.now)
            if len(self.arrived) < self.hold:
                self.arrived.append((model["name"], prompt))
                if len(self.arrived) == self.hold:
                    self.full.set()
        try:
            if number <= self.hold:
                self.full.wait(5)
            if self.block_after is not None and number > self.block_after:
                if self.release.wait(self.block_for):
                    return Reply("x", "ok", "s", 1, 1, 0.1)  # released after the test: touch nothing shared
            time.sleep(self.sleep)
            return self.real(model, prompt, max_output_tokens, reasoning_effort)
        finally:
            with self.lock:
                self.now -= 1


def test_parallel_writes_the_same_records_as_serial(exp, tmp_path):
    assert go("--parallel", "1", "--no-commit", "--results", str(tmp_path / "one")) == 0
    assert go("--parallel", "4", "--no-commit", "--results", str(tmp_path / "four")) == 0

    def keyed(folder, name):
        rows = [json.loads(line) for line in (folder / "exp/raw" / f"{name}.jsonl").read_text().splitlines()]
        return {(r["input_id"], r["setup"], r["model"], r["attempt_number"]): stable([r])[0] for r in rows}

    for name in "AB":
        assert keyed(tmp_path / "one", name) == keyed(tmp_path / "four", name)
        assert len(keyed(tmp_path / "four", name)) == input_count(exp) * 6


def test_the_fake_sees_at_most_n_calls_and_n_at_once(exp, monkeypatch):
    gate = Gate(monkeypatch, hold=3, sleep=0.01)
    assert go("--parallel", "3", "--no-commit") == 0
    assert gate.peak == 3


def test_in_flight_attempts_are_the_first_pending_in_loop_order(exp, monkeypatch):
    gate = Gate(monkeypatch, hold=4)
    manifest, inputs = run_module.load_release(exp / "releases/1.0.0")
    config = run_module.load_experiment_config(exp / "config/experiments/exp.toml")
    expected = [(m["name"], build_prompt(exp / "releases/1.0.0/prompts", row, setup))
                for row, m, setup, _ in list(run_module.pending_attempts(config, inputs, exp / "results/exp/raw", None))[:4]]
    assert go("--parallel", "4", "--no-commit", "--limit", "8") == 0
    assert sorted(gate.arrived) == sorted(expected)


def test_a_finished_attempt_is_replaced_by_the_next_pending_in_loop_order(exp, monkeypatch):
    real, lock, order = run_module.call_model, threading.Lock(), []
    two_arrived, third_arrived, free_first, free_rest = (threading.Event() for _ in range(4))

    def call(model, prompt, max_output_tokens, reasoning_effort=None):
        with lock:
            order.append((model["name"], prompt))
            number = len(order)
        if number == 2:
            two_arrived.set()
        if number == 3:
            third_arrived.set()
        if number == 1:
            free_first.wait(5)  # the first attempt finishes while the second is still in flight
        elif number == 2:
            free_rest.wait(5)
        return real(model, prompt, max_output_tokens, reasoning_effort)

    third_started_alone = []

    def release():
        two_arrived.wait(5)
        free_first.set()
        # a batched scheduler waits for the second attempt too, so this times out and the test fails
        third_started_alone.append(third_arrived.wait(5))
        free_rest.set()

    manifest, inputs = run_module.load_release(exp / "releases/1.0.0")
    config = run_module.load_experiment_config(exp / "config/experiments/exp.toml")
    expected = [(m["name"], build_prompt(exp / "releases/1.0.0/prompts", row, setup))
                for row, m, setup, _ in list(run_module.pending_attempts(config, inputs, exp / "results/exp/raw", None))[:3]]
    monkeypatch.setattr(run_module, "call_model", call)
    helper = threading.Thread(target=release, daemon=True)
    helper.start()
    assert go("--parallel", "2", "--no-commit", "--limit", "6") == 0
    helper.join(5)
    assert third_started_alone == [True]
    assert sorted(order[:2]) == sorted(expected[:2])
    assert order[2] == expected[2]


def test_parallel_budget_never_passes_the_model_budget(exp, capsys, monkeypatch):
    with_budget(exp, per_model_usd=0.035)
    gate = Gate(monkeypatch, hold=2)  # the first two calls wait for each other, so they really overlap
    assert go("--parallel", "4", "--model", "A") == 1
    assert gate.peak >= 2
    assert len(records(exp, "A")) == 3
    assert "per_model_usd 0.035 for model A" in capsys.readouterr().err


def test_a_budget_stop_writes_the_attempts_in_flight_first(exp, capsys, monkeypatch):
    with_budget(exp, per_model_usd=0.035)
    Gate(monkeypatch, sleep=0.1)
    assert go("--parallel", "4", "--model", "A") == 1
    assert len(records(exp, "A")) == 3
    assert len(git(exp, "show", f"{BRANCH}:results/exp/raw/A.jsonl").splitlines()) == 3
    lines = capsys.readouterr().err.strip().splitlines()
    assert lines[-1].startswith("error: budget reached:")


def test_a_parallel_budget_stop_counts_the_attempts_that_have_no_record():
    from src.run.budget import BudgetError

    class Stub:
        def __init__(self, seq, refused):
            self.seq, self.refused, self.error, self.stop = seq, refused, None, None

        def call(self):
            if self.refused:
                raise BudgetError("budget reached: per_model_usd 1 for model A (spent 1.0000, next request up to 0.0100)", 9)

    stubs = iter(Stub(seq, seq == 1) for seq in range(4))  # attempts 0, 2, and 3 finish; 1 is refused
    with pytest.raises(BudgetError, match=r"next request up to 0\.0100\); 7 attempts left$"):
        run_module.play_parallel(4, 10, stubs, lambda attempt: None, run_module.Flight())


def test_an_interrupt_with_attempts_in_flight_commits_and_returns_promptly(exp, monkeypatch):
    gate = Gate(monkeypatch, block_after=3, block_for=10.0)

    def stop():
        raise KeyboardInterrupt

    interrupt_on_third_record(monkeypatch, stop)
    started = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            go("--parallel", "4", "--model", "A")
        assert time.monotonic() - started < 5
        assert len(records(exp, "A")) == 2
        assert len(git(exp, "show", f"{BRANCH}:results/exp/raw/A.jsonl").splitlines()) == 2
    finally:
        gate.release.set()


def test_parallel_below_one_is_refused(exp, capsys):
    assert go("--parallel", "0") == 1
    assert "--parallel" in capsys.readouterr().err
    assert not (exp / "results").exists()


def bare_attempt(flight, results, seq, decision, budget):
    """An Attempt with only what can_afford reads, so a budget scenario can be played step by step."""
    attempt = object.__new__(run_module.Attempt)
    attempt.seq, attempt.flight, attempt.results, attempt.model = seq, flight, results, {"name": "A"}
    attempt.config = {"budget": {"per_model_usd": budget, "per_experiment_usd": 100.0}, "models": [{"name": "A"}]}
    attempt.prices = {"A": {"price_input_per_mtok": 0.0, "price_output_per_mtok": 100.0}}
    attempt.price, attempt.is_decision, attempt.worst, attempt.left = attempt.prices["A"], decision, 0.01, 1
    attempt.checks, attempt.snapshot = 0, {}
    flight.reserve(seq, "A", 0.01)
    return attempt


def test_a_decision_attempt_counts_records_other_attempts_write_after_its_snapshot(tmp_path):
    from src.run.budget import BudgetError
    flight = run_module.Flight()
    first, second = (bare_attempt(flight, tmp_path, n, True, 0.035) for n in (0, 1))
    first.can_afford(0, 0)  # snapshot taken: nothing spent
    second.can_afford(0, 0)
    flight.release(1, 0.03)  # the second attempt records 0.03 and its reservation goes
    with pytest.raises(BudgetError, match="per_model_usd"):
        first.can_afford(0, 0)  # 0.03 recorded + 0.01 next is above 0.035


def test_a_reservation_grows_with_the_tokens_its_attempt_has_paid(tmp_path):
    from src.run.budget import BudgetError
    flight = run_module.Flight()
    first = bare_attempt(flight, tmp_path, 0, False, 0.025)
    first.can_afford(0, 0)
    first.can_afford(0, 100)  # a failed call has paid 0.01 of output tokens: reserved 0.02
    second = bare_attempt(flight, tmp_path, 1, False, 0.025)
    with pytest.raises(BudgetError, match="per_model_usd"):
        second.can_afford(0, 0)  # 0.02 + 0.01 is above 0.025


def test_a_worker_failure_that_is_not_an_exception_ends_the_run(exp, monkeypatch):
    def boom(model, prompt, max_output_tokens, reasoning_effort=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_module, "call_model", boom)
    outcome = []

    def target():
        try:
            go("--parallel", "2", "--model", "A", "--no-commit")
        except BaseException as error:
            outcome.append(error)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(10)
    assert not thread.is_alive() and isinstance(outcome[0], KeyboardInterrupt)


def use_latest(repo):
    path = repo / "config/experiments/exp.toml"
    path.write_text(path.read_text().replace('release = "1.0.0"', 'release = "latest"'))


def test_latest_resolves_to_the_newest_release_and_is_stored_concrete(exp, capsys):
    edit_template(exp)
    release_ok(exp, "minor")
    use_latest(exp)
    assert go("--no-commit", "--limit", "2") == 0
    assert "release latest resolved to 1.1.0" in capsys.readouterr().out
    copy = (exp / "results/exp/experiment.toml").read_text()
    assert 'release = "1.1.0"' in copy and "latest" not in copy
    assert {r["release_version"] for r in records(exp, "A")} == {"1.1.0"}


def test_resumed_latest_keeps_the_release_in_the_copy(exp):
    use_latest(exp)
    assert go("--no-commit", "--limit", "2") == 0
    edit_template(exp)
    release_ok(exp, "minor")
    assert go("--no-commit", "--limit", "4") == 0
    assert 'release = "1.0.0"' in (exp / "results/exp/experiment.toml").read_text()
    assert {r["release_version"] for r in records(exp, "A")} == {"1.0.0"}


def test_copy_that_says_latest_is_refused(exp, capsys):
    use_latest(exp)
    (exp / "results/exp").mkdir(parents=True)
    (exp / "results/exp/experiment.toml").write_text((exp / "config/experiments/exp.toml").read_text())
    models.FAKE_REPLIES[:] = [Reply("x", "ok", "s", 1, 1, 0.1)]
    assert go("--no-commit") == 1
    assert len(models.FAKE_REPLIES) == 1
    err = capsys.readouterr().err
    assert "results/exp/experiment.toml" in err and "'release'" in err


def test_branch_copy_keeps_the_release_when_the_work_tree_lacks_it(exp):
    use_latest(exp)
    assert go("--limit", "2") == 0  # commits the copy, with 1.0.0, to the results branch
    (exp / "results/exp/experiment.toml").unlink()
    edit_template(exp)
    release_ok(exp, "minor")
    assert go("--no-commit", "--estimate") == 0  # no fetch, still reads the local branch
    assert not (exp / "results/exp/experiment.toml").exists()
    git(exp, "checkout", "-q", "-b", "other")  # the copy is read from the branch, not from HEAD
    assert go("--model", "A", "--limit", "1") == 0
    assert 'release = "1.0.0"' in (exp / "results/exp/experiment.toml").read_text()
    assert {r["release_version"] for r in records(exp, "A")} == {"1.0.0"}


def test_latest_without_any_release_refused(exp, capsys):
    use_latest(exp)
    shutil.rmtree(exp / "releases")
    assert go("--no-commit") == 1
    err = capsys.readouterr().err
    assert "releases" in err and "'release'" in err


def test_latest_line_that_does_not_match_once_refused(exp, capsys):
    path = exp / "config/experiments/exp.toml"
    path.write_text(path.read_text().replace('release = "1.0.0"', '"release" = "latest"'))
    assert go("--no-commit") == 1
    err = capsys.readouterr().err
    assert "exp.toml" in err and "'release'" in err
    assert not (exp / "results/exp").exists()


def test_run_passes_the_experiment_reasoning_effort_to_the_model(exp, monkeypatch):
    seen = []

    def call(model, prompt, max_output_tokens, reasoning_effort=None):
        seen.append(reasoning_effort)
        return Reply("U", "ok", "s", 1, 1, 0.1)

    monkeypatch.setattr(run_module, "call_model", call)
    assert stdin_run(exp, monkeypatch, 'reasoning_effort = "high"\n' + EXPERIMENT, "--limit", "1") == 0
    assert seen and set(seen) == {"high"}


def test_infrastructure_error_log_is_one_line(capsys):
    models.log_infrastructure_error("A in-1", 1, InfrastructureError("first\r\nsecond\nthird"))
    assert capsys.readouterr().err == "infrastructure error: A in-1 call 1: first  second third\n"


def test_live_hallucination_rate_is_na_for_decision_records():
    from src.run.progress import Tally
    base = {"input_tokens": 0, "retry_input_tokens": 0, "output_tokens": 0, "retry_output_tokens": 0,
            "validity": "valid", "mismatch": False, "hallucination": False, "outcome": "success",
            "parsed_moves": ["R"]}
    price = {"price_input_per_mtok": 1.0, "price_output_per_mtok": 1.0}
    decision_only, mixed, empty = Tally(), Tally(), Tally()
    for record in (dict(base, decision=True), dict(base, decision=True, outcome="infrastructure_failure")):
        decision_only.add(record, price)
    for record in (dict(base, decision=True), dict(base, decision=False, outcome="hallucination"),
                   dict(base, decision=False, outcome="abstention", parsed_moves=[]),
                   dict(base, decision=False, mismatch=True, parsed_moves=[])):
        mixed.add(record, price)
    assert decision_only.hallucination() == "n/a"
    assert mixed.hallucination() == "100%"  # the decision record is left out: 1 of the 1 text record that gave moves
    assert empty.hallucination() == "n/a"


def test_parse_raw_text_counts_the_same_lines_as_read_raw(tmp_path):
    from src.run.raw import parse_raw_text
    text = '{"a": 1}\n{"b": \n[1]\n{"d": 3}\n'
    path = tmp_path / "m.jsonl"
    path.write_text(text, encoding="utf-8")
    assert parse_raw_text(text) == read_raw(path) == ([{"a": 1}, {"d": 3}], 2)


def test_records_hold_mismatch_reason_and_progress_shows_precision(exp, capsys):
    reason = offered_reasons(get_engine("2x2"))[0]
    models.FAKE_REPLIES[:] = [reply(f"MISMATCH {reason}")]
    go("--model", "A", "--limit", "1", "--no-commit")
    (line,) = progress_lines(capsys.readouterr().out)
    (row,) = records(exp, "A")
    assert row["mismatch_reason"] == reason and "balanced precision n/a" in line


def test_progress_precision_counts_tp_and_tn():
    from src.run.progress import Tally
    price = {"price_input_per_mtok": 0, "price_output_per_mtok": 0}
    base = {"input_tokens": 0, "output_tokens": 0, "retry_input_tokens": 0, "retry_output_tokens": 0,
            "validity": "valid", "mismatch": False, "parsed_moves": []}
    tally = Tally()
    tally.add(dict(base, outcome="success", parsed_moves=["R"]), price)
    tally.add(dict(base, outcome="failure", parsed_moves=["R"]), price)
    tally.add(dict(base, outcome="success", validity="invalid", mismatch=True, mismatch_reason="twisted corner"),
              price, "twisted corner at UFR")
    tally.add(dict(base, outcome="abstention"), price)
    assert tally.precision() == "75%"  # valid 1/2, invalid 1/1


def test_progress_precision_is_na_when_a_label_has_no_classified_answer():
    from src.run.progress import Tally
    price = {"price_input_per_mtok": 0, "price_output_per_mtok": 0}
    base = {"input_tokens": 0, "output_tokens": 0, "retry_input_tokens": 0, "retry_output_tokens": 0,
            "validity": "valid", "mismatch": False, "parsed_moves": []}
    tally = Tally()
    tally.add(dict(base, outcome="success", parsed_moves=["R"]), price)
    tally.add(dict(base, validity="invalid", outcome="abstention"), price)
    assert tally.precision() == "n/a"


def test_per_puzzle_depths_give_each_puzzle_its_cap(exp):
    from src.config import max_moves
    release = {"scramble_depths": {"2x2": [3], "4x4": [10, 40]}}
    assert max_moves({}, release, "2x2") == 6 and max_moves({}, release, "4x4") == 80


def test_manifest_mismatch_reasons_must_match_the_prompts(exp, capsys):
    path = exp / "releases/1.0.0/manifest.json"
    path.chmod(0o644)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["mismatch_reasons"] = False
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert go("--estimate") == 1
    assert "mismatch_reasons" in capsys.readouterr().err


def test_decision_model_under_a_release_without_mismatch_reasons(repo, monkeypatch):
    for path in (repo / "prompts").rglob("*.txt"):
        path.write_text(path.read_text(encoding="utf-8").replace("{mismatch_reasons}", ""), encoding="utf-8")
    commit_all(repo, "templates without mismatch reasons")
    release_ok(repo, "major")
    assert json.loads((repo / "releases/1.0.0/manifest.json").read_text(encoding="utf-8"))["mismatch_reasons"] is False
    (repo / "config" / "experiments").mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.setattr(release_module, "REPO_ROOT", repo)
    fake = decision_exp(repo, monkeypatch)
    asked = []
    from src.run import decision as decision_module
    real = decision_module.call_decision

    def spy(model, state, questions):
        asked.append(questions)
        return real(model, state, questions)

    monkeypatch.setattr(decision_module, "call_decision", spy)
    fake[:] = [d_reply("move_1"), d_reply("mismatch"), d_reply("done")]
    assert go("--limit", "1") == 0
    (row,) = records(repo, "D")
    assert "mismatch" in json.dumps(asked[0]) and "mismatch_1" not in json.dumps(asked[0])
    assert row["mismatch"] is True and len(json.loads(row["raw_response"])) == 2 and row["hallucination"] is None
    assert row["mismatch_reason"] is None and row["decision"] is True


def test_check_prices_needs_batch_prices_for_batched_models():
    config = {"batch": True, "models": [{"name": "a", "provider": "anthropic"},
                                        {"name": "d", "provider": "typesafe"}]}
    plain = {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0}
    with pytest.raises(budget_module.BudgetError, match="'a'.*batch_price_input_per_mtok"):
        budget_module.check_prices(config, {"a": plain, "d": plain}, "p.toml")
    both = dict(plain, batch_price_input_per_mtok=0.5, batch_price_output_per_mtok=1.0)
    budget_module.check_prices(config, {"a": both, "d": plain}, "p.toml")  # decision models run direct
    budget_module.check_prices(dict(config, batch=False), {"a": plain, "d": plain}, "p.toml")


def test_worst_case_request_cost_uses_the_batch_tier():
    price = {"price_input_per_mtok": 4.0, "price_output_per_mtok": 8.0,
             "batch_price_input_per_mtok": 2.0, "batch_price_output_per_mtok": 4.0}
    standard = budget_module.worst_case_request_cost("x" * 400, 1000, price)
    assert budget_module.worst_case_request_cost("x" * 400, 1000, price, True) == pytest.approx(standard / 2)


def test_make_record_writes_the_batch_flag(exp):
    go("--limit", "1")
    config = run_module.load_experiment_config(exp / "config/experiments/exp.toml")
    manifest = json.loads((exp / "releases/1.0.0/manifest.json").read_text(encoding="utf-8"))
    row = json.loads((exp / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    versions = manifest["prompt_versions"]
    made = run_module.make_record(config, manifest, row, config["models"][0], "no_model", 1, versions,
                                  Reply("MISMATCH", "ok", "s", 1, 1, None), 0, 0, batch=True)
    assert made["batch"] is True and made["latency_s"] is None


# Batch mode. The fake provider's batch API: every submit is listed in models.FAKE_BATCH_SUBMITS (at most 3
# requests each), and `answer` below plays the provider, answering a batch from its own request list.

BATCH_EXPERIMENT = EXPERIMENT.replace("[[models]]\nname = \"B\"\nprovider = \"fake\"\napi_model_id = \"b-1\"\n", "") \
    + "batch = true\n"
BATCH_PRICES = ("[A]\nprice_input_per_mtok = 2.0\nprice_output_per_mtok = 4.0\n"
                "batch_price_input_per_mtok = 1.0\nbatch_price_output_per_mtok = 2.0\n")


def toml_with_batch(text):
    """`batch = true` is a top-level field, so it goes before the first table."""
    head, table = text.replace("batch = true\n", "").split("[[models]]", 1)
    return head + "batch = true\n[[models]]" + table


@pytest.fixture
def bexp(exp, monkeypatch):
    from src.run import batch as batch_module
    (exp / "config" / "experiments" / "exp.toml").write_text(toml_with_batch(BATCH_EXPERIMENT), encoding="utf-8")
    (exp / "config" / "prices.toml").write_text(BATCH_PRICES, encoding="utf-8")
    monkeypatch.setattr(models, "FAKE_BATCH_SUBMITS", [])
    monkeypatch.setattr(models, "FAKE_BATCH_PENDING", set())
    monkeypatch.setattr(models, "FAKE_BATCH_RESULTS", [])
    monkeypatch.setattr(batch_module, "POLL_S", 0)
    monkeypatch.setattr(batch_module, "batch_results", lambda model, batch_id: answer(batch_id))
    monkeypatch.setattr(bexp_state, "failing", {})
    return exp


class bexp_state:
    failing: dict = {}  # custom id -> exception to return instead of an answer


def answer(batch_id):
    """Answer a fake batch from its request list, in reverse order, tagging each reply with its own custom id."""
    (requests,) = [r for b, r in models.FAKE_BATCH_SUBMITS if b == batch_id]
    result = {}
    for custom_id, body in reversed(requests):
        failure = bexp_state.failing.get(custom_id)
        result[custom_id] = failure if failure else Reply("U", "ok", f"served-{custom_id}", 10, 100, 0.5)
    return result


def submitted_ids():
    return [cid for _, requests in models.FAKE_BATCH_SUBMITS for cid, _ in requests]


def state_events(repo):
    path = repo / "results/exp/batches/A.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_batch_requests_equal_direct_requests_and_results_map_by_custom_id(bexp):
    assert go("--limit", "7") == 0
    rows = records(bexp, "A")
    assert len(rows) == 7 and [len(r) for _, r in models.FAKE_BATCH_SUBMITS] == [3, 3, 1]
    model = {"name": "A", "provider": "fake", "api_model_id": "a-1"}
    inputs = {json.loads(l)["input_id"]: json.loads(l)
              for l in (bexp / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()}
    by_id = {}
    for _, requests in models.FAKE_BATCH_SUBMITS:
        for cid, body in requests:
            assert cid not in by_id
            by_id[cid] = body
    for row in rows:
        cid = f"{row['input_id']}_{row['setup']}_a{row['attempt_number']}_r0"
        prompt = build_prompt(bexp / "releases/1.0.0/prompts", inputs[row["input_id"]], row["setup"])
        assert by_id[cid] == models.build_request(model, prompt, 100, None)
        assert row["served_model"] == f"served-{cid}"  # the reply that was addressed to this attempt
        assert row["batch"] is True and row["latency_s"] is None
        assert row["retry_input_tokens"] == row["retry_output_tokens"] == 0
    assert len(by_id) == 7


def test_batch_state_file_and_commits(bexp):
    assert go("--limit", "4") == 0
    events = state_events(bexp)
    assert [e["event"] for e in events] == ["submitted", "collected", "submitted", "collected"]
    assert events[0]["requests"][0].keys() == {"custom_id", "input_id", "setup", "attempt_number", "retry"}
    log = git(bexp, "log", "--format=%s", BRANCH)
    assert "Results: experiment exp, A batch fake-batch-1 submitted" in log
    assert "Results: experiment exp, A batch fake-batch-1 collected" in log


def test_an_open_batch_is_collected_on_restart_without_resubmitting(bexp, monkeypatch, capsys):
    from src.run import batch as batch_module
    models.FAKE_BATCH_PENDING.add("fake-batch-1")

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(batch_module.time, "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        go("--limit", "3")
    assert [e["event"] for e in state_events(bexp)] == ["submitted"]
    assert not (bexp / "results/exp/raw/A.jsonl").exists()
    models.FAKE_BATCH_PENDING.clear()
    assert go("--limit", "3") == 0
    assert len(models.FAKE_BATCH_SUBMITS) == 1 and len(records(bexp, "A")) == 3
    assert [e["event"] for e in state_events(bexp)] == ["submitted", "collected"]
    assert "collected 3 succeeded, 0 to retry, 0 failed" in capsys.readouterr().err


def test_failed_requests_are_retried_with_the_next_retry_index_then_recorded_as_failures(bexp, capsys):
    first = "2x2-d3-001_no_model_a1_r0"
    bexp_state.failing.update({first: InfrastructureError("x"), first.replace("_r0", "_r1"): InfrastructureError("x")})
    assert go("--limit", "1") == 0  # retry_cap 3: r0 and r1 fail, r2 answers
    (row,) = records(bexp, "A")
    assert row["outcome"] != "infrastructure_failure" and row["served_model"] == "served-" + first.replace("_r0", "_r2")
    assert submitted_ids() == [first, first.replace("_r0", "_r1"), first.replace("_r0", "_r2")]
    assert "collected 0 succeeded, 1 to retry, 0 failed" in capsys.readouterr().err


def test_retries_end_at_the_cap_with_an_infrastructure_failure(bexp, capsys):
    first = "2x2-d3-001_no_model_a1_r0"
    bexp_state.failing.update({first.replace("_r0", f"_r{k}"): InfrastructureError("x") for k in range(4)})
    assert go("--limit", "1") == 0
    (row,) = records(bexp, "A")
    assert row["outcome"] == "infrastructure_failure" and row["raw_response"] == "" and row["batch"] is True
    assert row["stop_reason"] == "infrastructure_failure" and row["latency_s"] is None
    assert (row["retry_input_tokens"], row["retry_output_tokens"], row["requested_model"]) == (0, 0, "a-1")
    assert len(submitted_ids()) == 4  # retry_cap 3: one submission and three retries
    assert "collected 0 succeeded, 0 to retry, 1 failed" in capsys.readouterr().err


def test_a_missing_result_is_a_retry_and_never_an_endless_loop(bexp, monkeypatch):
    from src.run import batch as batch_module
    monkeypatch.setattr(batch_module, "batch_results", lambda model, batch_id: {})
    assert go("--limit", "1") == 0
    (row,) = records(bexp, "A")
    assert row["outcome"] == "infrastructure_failure" and len(submitted_ids()) == 4


def test_a_request_error_keeps_the_good_answers_closes_the_batch_and_stops(bexp, capsys):
    bexp_state.failing["2x2-d3-001_descriptive_a1_r0"] = models.RequestError("anthropic: HTTP 400: bad request")
    assert go("--limit", "3") == 1
    assert capsys.readouterr().err.splitlines()[-1] == "error: anthropic: HTTP 400: bad request"
    assert len(records(bexp, "A")) == 2
    assert [e["event"] for e in state_events(bexp)] == ["submitted", "collected"]
    assert len(models.FAKE_BATCH_SUBMITS) == 1


def test_a_batch_that_fails_as_a_whole_is_closed_before_the_run_stops(bexp, monkeypatch, capsys):
    from src.run import batch as batch_module

    def fail(model, batch_id):
        raise models.RequestError("openai: the batch failed")

    monkeypatch.setattr(batch_module, "batch_results", fail)
    assert go("--limit", "3") == 1
    assert [e["event"] for e in state_events(bexp)] == ["submitted", "collected"]
    assert "the batch failed" in capsys.readouterr().err


def test_batch_budget_sizes_the_chunk_and_stops(bexp, capsys):
    # Batch output price 1.0 USD per million with 100 output tokens and no input price: 0.0001 per request.
    (bexp / "config" / "prices.toml").write_text(
        "[A]\nprice_input_per_mtok = 0.0\nprice_output_per_mtok = 2.0\n"
        "batch_price_input_per_mtok = 0.0\nbatch_price_output_per_mtok = 1.0\n", encoding="utf-8")
    path = bexp / "config" / "experiments" / "exp.toml"
    path.write_text(path.read_text(encoding="utf-8") + "[budget]\nper_model_usd = 0.0004\n", encoding="utf-8")
    assert go() == 1
    assert [len(r) for _, r in models.FAKE_BATCH_SUBMITS] == [3, 1]  # room for four requests: three, then one
    assert len(records(bexp, "A")) == 4
    assert "budget reached: per_model_usd 0.0004 for model A" in capsys.readouterr().err


def two_model_batch_exp(bexp):
    two = (toml_with_batch(BATCH_EXPERIMENT) + '[[models]]\nname = "B"\nprovider = "fake"\napi_model_id = "b-1"\n'
           '[budget]\nper_experiment_usd = 0.0004\n')
    (bexp / "config" / "experiments" / "exp.toml").write_text(two, encoding="utf-8")
    cheap = ("price_input_per_mtok = 0.0\nprice_output_per_mtok = 2.0\n"
             "batch_price_input_per_mtok = 0.0\nbatch_price_output_per_mtok = 1.0\n")
    (bexp / "config" / "prices.toml").write_text(f"[A]\n{cheap}[B]\n{cheap}", encoding="utf-8")
    models.FAKE_BATCH_PENDING.add("fake-batch-1")  # B's batch stays open: 3 requests, 0.0003 USD in the worst case

    def interrupt(seconds):
        raise KeyboardInterrupt

    from src.run import batch as batch_module
    batch_module.time.sleep = interrupt
    with pytest.raises(KeyboardInterrupt):
        go("--model", "B", "--limit", "3")
    models.FAKE_BATCH_PENDING.add("fake-batch-2")


def test_with_model_a_budget_held_by_another_models_open_batch_stops_instead_of_waiting(bexp, monkeypatch, capsys):
    from src.run import batch as batch_module
    real_sleep = batch_module.time.sleep
    monkeypatch.setattr(batch_module.time, "sleep", real_sleep)  # restored after the test
    two_model_batch_exp(bexp)

    def never(seconds):
        raise AssertionError("slept while no batch of this process is open")

    batch_module.time.sleep = never
    models.FAKE_BATCH_PENDING.discard("fake-batch-2")  # A's own batch finishes at once
    assert go("--model", "A", "--limit", "20") == 1
    assert [len(r) for _, r in models.FAKE_BATCH_SUBMITS] == [3, 1]  # A gets the 0.0001 that B's batch leaves
    err = capsys.readouterr().err
    assert "open batches of B exceed per_experiment_usd 0.0004; run without --model to collect them" in err


def test_without_model_the_run_waits_for_the_other_models_open_batch(bexp, monkeypatch):
    from src.run import batch as batch_module
    monkeypatch.setattr(batch_module.time, "sleep", batch_module.time.sleep)
    two_model_batch_exp(bexp)

    def interrupt(seconds):
        raise KeyboardInterrupt

    batch_module.time.sleep = interrupt
    with pytest.raises(KeyboardInterrupt):
        go("--limit", "20")


def test_decision_models_of_a_batch_experiment_run_direct(bexp, monkeypatch):
    config = ('release = "1.0.0"\nattempts = 1\nretry_cap = 3\nmax_output_tokens = 100\nbatch = true\n'
              '[[models]]\nname = "A"\nprovider = "fake"\napi_model_id = "a-1"\n'
              '[[models]]\nname = "D"\nprovider = "fake_decision"\napi_model_id = "d-1"\n')
    (bexp / "config" / "experiments" / "exp.toml").write_text(config, encoding="utf-8")
    (bexp / "config" / "prices.toml").write_text(
        BATCH_PRICES + "[D]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n", encoding="utf-8")
    monkeypatch.setattr(models, "FAKE_DECISION_REPLIES", [d_reply("done") for _ in range(10)])
    assert go("--limit", "2") == 0
    assert len(models.FAKE_BATCH_SUBMITS) == 1 and len(submitted_ids()) == 2
    assert [r["batch"] for r in records(bexp, "A")] == [True, True]
    assert not (bexp / "results/exp/raw/D.jsonl").exists()  # --limit counts the batched attempts first
    assert go() == 0
    assert all(r["batch"] is False and r["decision"] is True for r in records(bexp, "D"))


def test_a_submit_that_fails_after_sending_stops_the_run_and_writes_no_state(bexp, monkeypatch, capsys):
    from src.run import batch as batch_module

    def fail(model, requests):
        raise InfrastructureError("connection reset")

    monkeypatch.setattr(batch_module, "submit_batch", fail)
    assert go("--limit", "3") == 1
    err = capsys.readouterr().err
    assert "A: the batch submit failed after sending (connection reset); the provider may have created the batch, " \
           "so check its console before running again; a new run resubmits these 3 requests" in err
    assert not (bexp / "results/exp/batches/A.jsonl").exists()


def test_a_sigterm_during_submit_waits_for_the_state_file_and_its_commit(bexp, monkeypatch):
    import os
    import signal
    from src.run import batch as batch_module
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))

    def send_then_signal(model, requests):
        batch_id = models.submit_batch(model, requests)
        os.kill(os.getpid(), signal.SIGTERM)
        assert not (bexp / "results/exp/batches/A.jsonl").exists()  # deferred: the handler did not run yet
        return batch_id

    monkeypatch.setattr(batch_module, "submit_batch", send_then_signal)
    with pytest.raises(SystemExit) as stopped:
        go("--limit", "3")
    assert stopped.value.code == 128 + signal.SIGTERM
    assert [e["event"] for e in state_events(bexp)] == ["submitted"]
    assert '"event": "submitted"' in git(bexp, "show", f"{BRANCH}:results/exp/batches/A.jsonl")
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before


def test_a_pending_batch_is_committed_and_pushed_at_submit_and_survives_sigterm_while_waiting(
        bexp, monkeypatch, tmp_path_factory):
    import os
    import signal
    from src.run import batch as batch_module
    remote = with_remote(bexp, tmp_path_factory)
    models.FAKE_BATCH_PENDING.add("fake-batch-1")
    seen = {}

    def terminate_while_waiting(seconds):
        seen["remote"] = git(remote, "show", f"{BRANCH}:results/exp/batches/A.jsonl")  # pushed before waiting
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(batch_module.time, "sleep", terminate_while_waiting)
    with pytest.raises(SystemExit):
        go("--limit", "3")
    assert '"event": "submitted"' in seen["remote"]
    assert [e["event"] for e in state_events(bexp)] == ["submitted"]  # left open, never cancelled
    assert "batch fake-batch-1 submitted" in git(bexp, "log", "--format=%s", BRANCH)
    models.FAKE_BATCH_PENDING.clear()
    assert go("--limit", "3") == 0  # a later run collects it without resubmitting
    assert len(models.FAKE_BATCH_SUBMITS) == 1 and len(records(bexp, "A")) == 3


def test_a_request_that_is_larger_than_the_provider_limit_is_refused(bexp, monkeypatch, capsys):
    from src.run import batch as batch_module
    monkeypatch.setitem(batch_module.LIMITS, "fake", (3, 100))
    assert go("--limit", "3") == 1
    err = capsys.readouterr().err.splitlines()[-1]
    assert err == "error: A 2x2-d3-001_no_model_a1_r0: request larger than the fake batch limit"
    assert not models.FAKE_BATCH_SUBMITS


def test_chunks_are_cut_by_the_utf8_bytes_of_the_batch_lines(bexp, monkeypatch):
    from src.run import batch as batch_module
    first = json.loads((bexp / "releases/1.0.0/inputs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    sizes = []
    for setup, number in (("no_model", 1), ("no_model", 2), ("descriptive", 1)):
        prompt = build_prompt(bexp / "releases/1.0.0/prompts", first, setup)
        body = models.build_request({"name": "A", "provider": "fake", "api_model_id": "a-1"}, prompt, 100, None)
        sizes.append(batch_module.line_size(f"{first['input_id']}_{setup}_a{number}_r0", body))
    monkeypatch.setitem(batch_module.LIMITS, "fake", (3, sizes[0] + sizes[1]))
    assert go("--limit", "3") == 0
    assert [len(r) for _, r in models.FAKE_BATCH_SUBMITS] == [2, 1]


def test_a_request_error_does_not_count_toward_the_retry_cap(bexp, capsys):
    target = "2x2-d3-001_descriptive_a1_r0"
    bexp_state.failing[target] = models.RequestError("anthropic: HTTP 400: bad request")
    for _ in range(5):  # more runs than retry_cap + 1
        assert go("--limit", "3") == 1
    assert target in submitted_ids() and submitted_ids().count(target) == 5  # always retry index 0
    bexp_state.failing.clear()
    assert go("--limit", "3") == 0
    assert all(r["outcome"] != "infrastructure_failure" for r in records(bexp, "A"))
