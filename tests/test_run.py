# Spec: docs/specs/run.md
"""Tests for run. Each test builds a tiny release in a temporary git repo (the helper from
test_release), then calls run's main() in-process from inside that repo with the fake provider.
"""

import csv
import io
import json
import sys
import threading
import time

import pytest

from src.evaluate import evaluate as evaluate_module
from src.puzzles.registry import get_engine
from src.run import budget as budget_module, models, run as run_module
from src.run.models import InfrastructureError, Reply
from src.run.budget import worst_request, worst_state
from src.run.prompts import build_prompt, load_questions
from src.run.raw import read_raw
from test_release import git, release_ok, repo  # noqa: F401  (repo is a fixture)

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
    "stop_reason", "served_model", "decision", "requested_model", "created_at",
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
        assert row["decision"] is False and row["requested_model"] == "a-1"
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
    models.FAKE_REPLIES[:] = [reply(), reply("X"), Reply("", "ok", "s", 10, 4, 0.1)]
    assert go("--model", "A", "--limit", "3", "--no-commit") == 0
    first, second, third = progress_lines(capsys.readouterr().out)
    assert first.startswith("[1/3] A 2x2 ") and " no_model #1 failure | in 10 out 4 | $0.0000 | " in first
    assert first.endswith("success 0% hallucination 0% malformed 0%")
    assert " no_model #2 hallucination | in 20 out 8 | " in second
    assert second.endswith("success 0% hallucination 50% malformed 0%")
    assert " descriptive #1 malformed_output | in 30 out 12 | " in third and third.startswith("[3/3] A ")
    assert third.endswith("success 0% hallucination 33% malformed 33%")


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
    assert "infrastructure_failure" in first and first.endswith("success n/a hallucination n/a malformed n/a")
    assert second.endswith("success 0% hallucination 0% malformed 0%")


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
    assert by_setup["no_model"]["success_rate"] == "1.0000" and by_setup["no_model"]["hallucination_rate"] == "0.0000"
    assert by_setup["descriptive"]["malformed_output_rate"] == "1.0000"
    assert by_setup["prescriptive"]["infrastructure_failure_count"] == "1"
    assert by_setup["prescriptive"]["success_rate_n"] == "0" and by_setup["prescriptive"]["input_tokens_per_attempt"] == "20.0000"


def test_decision_reply_without_a_model_keeps_served_empty_and_requests_the_entry_id(exp, monkeypatch):
    fake = decision_exp(exp, monkeypatch)
    fake[:] = [d_reply("done", model="")]
    assert go("--limit", "1") == 0
    (row,) = records(exp, "D")
    assert row["served_model"] == "" and row["requested_model"] == "d-1" and row["decision"] is True


def test_decision_mismatch_choice_ends_the_attempt_and_sets_the_flag(exp, monkeypatch):
    fake = decision_exp(exp, monkeypatch)
    fake[:] = [d_reply("move_1"), d_reply("mismatch"), d_reply("done")]
    assert go("--limit", "1") == 0
    (row,) = records(exp, "D")
    assert row["mismatch"] is True and len(json.loads(row["raw_response"])) == 2 and len(fake) == 1


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
                                      load_questions(exp / "releases/1.0.0/prompts"))
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

    def __call__(self, model, prompt, max_output_tokens):
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
            return self.real(model, prompt, max_output_tokens)
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

    def call(model, prompt, max_output_tokens):
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
        return real(model, prompt, max_output_tokens)

    def release():
        two_arrived.wait(5)
        free_first.set()
        third_arrived.wait(5)
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
    def boom(model, prompt, max_output_tokens):
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
