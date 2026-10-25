# Spec: docs/specs/ui.md
"""Tests for the UI's git reader, over a temporary repo with a bare origin."""

import json
import os
import subprocess

import pytest

from src.evaluate import evaluate as evaluate_module
from src.evaluate.metrics import compute
from src.run.run import make_record
from test_release import git, repo  # noqa: F401
from test_ui import PRICES, ui_repo  # noqa: F401  (ui_repo is a fixture)
from ui import expdata
from ui.gitdata import GitData
from ui.pooling import pooled_summary


def test_show_reads_ref_not_work_tree(ui_repo):
    data = GitData(ui_repo); data.fetch(force=True)
    (ui_repo / "config" / "models.toml").write_text("changed", encoding="utf-8")
    assert "example-model" in data.show(data.main_ref(), "config/models.toml")
    assert data.show(data.main_ref(), "no/such/file") is None


def test_results_refs_prefers_local_for_live(ui_repo):
    git(ui_repo, "branch", "results/a")
    git(ui_repo, "push", "-q", "origin", "results/a")
    git(ui_repo, "branch", "results/b")      # local only
    data = GitData(ui_repo); data.fetch(force=True)
    assert data.results_refs() == {"a": "refs/remotes/origin/results/a"}
    assert data.results_refs({"a", "b"}) == {"a": "refs/heads/results/a", "b": "refs/heads/results/b"}


def test_fetch_is_throttled(ui_repo):
    now = [100.0]
    data = GitData(ui_repo, clock=lambda: now[0])
    data.fetch(); first = data.fetched_at
    assert first
    git(ui_repo, "branch", "results/c")  # push by URL, so no tracking ref moves until a fetch
    url = git(ui_repo, "remote", "get-url", "origin").strip()
    git(ui_repo, "push", "-q", url, "results/c")
    data.fetch(); assert "c" not in data.remote_ids()
    now[0] += 31; data.fetch(); assert "c" in data.remote_ids()


def test_github_url_forms(ui_repo):
    data = GitData(ui_repo)
    for url in ("https://github.com/o/r.git", "https://github.com/o/r", "git@github.com:o/r.git"):
        git(ui_repo, "remote", "set-url", "origin", url)
        assert data.github() == "https://github.com/o/r"
    assert data.link("abc", "README.md") == "https://github.com/o/r/blob/abc/README.md"
    git(ui_repo, "remote", "set-url", "origin", "https://gitlab.com/o/r.git")
    assert data.github() is None and data.link("abc", "x") is None


def test_no_origin_reads_head(ui_repo):
    git(ui_repo, "remote", "remove", "origin")
    data = GitData(ui_repo); data.fetch(force=True)
    assert data.fetch_error and data.main_ref() == "HEAD"
    assert data.show("HEAD", "config/models.toml")


# --- expdata ---------------------------------------------------------------------------------

EXP_TOML = ('release = "1.0.0"\nattempts = 1\nretry_cap = 1\nmax_output_tokens = 100\n'
            '[[models]]\nname = "example-model"\nprovider = "fake"\napi_model_id = "ex-1"\n')
MANIFEST = {"input_set_id": "1", "release_config": {"seed": 7}}
VERSIONS = {s: {"2x2": "v"} for s in ("no_model", "descriptive", "prescriptive")}
SUCCESS = '{"moves": [], "mismatch": true}'
HALLUCINATION = '{"moves": ["u"], "mismatch": false}'
FAILURE = '{"moves": [], "mismatch": false}'


class Reply:
    def __init__(self, text, stop="ok"):
        self.text, self.stop_reason, self.served_model = text, stop, "served-1"
        self.input_tokens, self.output_tokens, self.latency_s = 10, 5, 0.5


def record(input_row, setup, attempt, reply, model="example-model"):
    """A raw record as `run` writes it; `reply` is text, or None for an infrastructure failure."""
    config = {"experiment_id": "x", "release": "1.0.0"}
    made = make_record(config, MANIFEST, input_row, {"name": model}, setup, attempt, "", VERSIONS,
                       None if reply is None else Reply(reply), 3, 2)
    made["created_at"] = "2026-10-25T00:00:00Z"
    return made


def jsonl(records):
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)


def push_results(repo, experiment_id, files):
    """Commit `files` on top of HEAD into refs/heads/results/<id> on origin, never touching the work tree."""
    index = repo / ".git" / f"index-{experiment_id}"
    env = dict(os.environ, GIT_INDEX_FILE=str(index))

    def run(*args, stdin=None):
        done = subprocess.run(["git", *args], cwd=repo, env=env, input=stdin, check=True,
                              capture_output=True, text=True)
        return done.stdout.strip()

    try:
        run("read-tree", "HEAD")
        for path, text in files.items():
            blob = run("hash-object", "-w", "--stdin", stdin=text)
            run("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
        commit = run("commit-tree", run("write-tree"), "-p", "HEAD", "-m", f"results {experiment_id}")
    finally:
        index.unlink(missing_ok=True)
    run("push", "-q", "origin", f"{commit}:refs/heads/results/{experiment_id}")


def open_experiment(ui_repo, experiment_id, files):
    push_results(ui_repo, experiment_id, files)
    git_data = GitData(ui_repo)
    git_data.fetch(force=True)
    main = git_data.main_ref()
    ref = f"refs/remotes/origin/results/{experiment_id}"
    return (expdata.load_experiment(git_data, experiment_id, ref, main),
            expdata.read_inputs(git_data, main, "1.0.0"))


@pytest.fixture
def samples(ui_repo):
    inputs = [json.loads(line) for line in
              (ui_repo / "releases" / "1.0.0" / "inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    valid = next(r for r in inputs if r["validity"] == "valid")
    invalid = next(r for r in inputs if r.get("source_input_id") == valid["input_id"])
    records = [record(valid, "no_model", 1, HALLUCINATION), record(valid, "descriptive", 1, "nope"),
               record(invalid, "no_model", 1, SUCCESS), record(invalid, "prescriptive", 1, FAILURE)]
    return valid, invalid, records


def files_for(records, **extra):
    return {"results/e/experiment.toml": EXP_TOML,
            "results/e/raw/example-model.jsonl": jsonl(records), **extra}


def rows_by_scope(rows):
    return {r["validity"]: r for r in rows}


def test_computed_rows_equal_compute(ui_repo, samples):
    _, _, records = samples
    exp, inputs = open_experiment(ui_repo, "e", files_for(records))
    rows = expdata.experiment_rows(exp, inputs)
    assert len(rows) == 3 and exp["error"] is None
    assert {r["metrics_source"] for r in rows} == {"computed"}
    by = rows_by_scope(rows)
    assert by["valid"]["attempts"] + by["invalid"]["attempts"] == by["all"]["attempts"] == 4
    prices = {"example-model": {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0}}
    summary = compute(records, ui_repo / "releases" / "1.0.0", prices)[2]
    for validity in ("valid", "invalid"):
        mine = [r for r in summary if r["validity"] == validity]
        for rate in ("success_rate", "hallucination_rate", "malformed_output_rate"):
            n = sum(r[rate + "_n"] for r in mine)
            expected = sum(r[rate] * r[rate + "_n"] for r in mine if r[rate + "_n"]) / n
            assert by[validity][rate] == pytest.approx(expected)
    assert by["valid"]["mismatch_detection_rate"] is None
    assert by["invalid"]["false_mismatch_rate"] is None
    assert by["invalid"]["mismatch_detection_rate"] == pytest.approx(0.5)
    assert by["all"]["success_rate"] == pytest.approx(0.25)
    assert by["all"]["hallucination_rate"] == pytest.approx(0.25)
    assert by["all"]["false_mismatch_rate"] == 0
    assert by["all"]["total_tokens"] == 4 * 20
    assert by["all"]["cost_usd"] == pytest.approx(4 * 2.7e-5)
    assert by["all"]["served_models"] == ["served-1"]


def test_infrastructure_failures_change_no_rate(ui_repo, samples):
    valid, _, records = samples
    exp, inputs = open_experiment(ui_repo, "e", files_for(records))
    before = rows_by_scope(expdata.experiment_rows(exp, inputs))
    exp, inputs = open_experiment(ui_repo, "f", {
        "results/f/experiment.toml": EXP_TOML,
        "results/f/raw/example-model.jsonl": jsonl(records + [record(valid, "descriptive", 2, None)])})
    after = rows_by_scope(expdata.experiment_rows(exp, inputs))
    for scope in before:
        assert after[scope]["infrastructure_failures"] == before[scope]["infrastructure_failures"] + (scope != "invalid")
        for rate in expdata.RATES:
            assert after[scope][rate] == before[scope][rate]
    assert after["all"]["total_tokens"] == before["all"]["total_tokens"] + 5


def test_report_csv_used(ui_repo, samples):
    _, _, records = samples
    header = "puzzle,setup,model,scramble_depth,validity,attempts,infrastructure_failure_count,success_rate,success_rate_n\n"
    text = (header + "2x2,no_model,example-model,5,valid,2,0,0.5000,2\n"
            + "2x2,descriptive,example-model,5,valid,4,0,0.2500,4\n")
    exp, inputs = open_experiment(ui_repo, "e", files_for(
        records, **{"results/e/1.0.0.metrics.csv": text, "results/e/0.9.0.metrics.csv": header,
                    "results/e/1.0.0.md": "# report"}))
    assert exp["report_version"] == "1.0.0" and exp["report_md"] == "# report"
    by = rows_by_scope(expdata.experiment_rows(exp, inputs))
    assert {r["metrics_source"] for r in by.values()} == {"report"}
    assert by["valid"]["success_rate"] == pytest.approx(2 / 6)
    assert by["valid"]["attempts"] == 6 and by["invalid"]["attempts"] == 0
    assert by["invalid"]["success_rate"] is None
    assert by["valid"]["total_tokens"] > 0


def test_torn_line_skipped(ui_repo, samples):
    _, _, records = samples
    lines = jsonl(records).splitlines(keepends=True)
    torn = "".join(lines[:2]) + '{"input_id": "2x2-d5\n' + "".join(lines[2:])
    exp, inputs = open_experiment(ui_repo, "e", {"results/e/experiment.toml": EXP_TOML,
                                                 "results/e/raw/example-model.jsonl": torn})
    assert exp["skipped"] == 1 and exp["error"] is None
    assert len(expdata.attempt_rows(exp, inputs)) == 4


def test_broken_branch_gives_error_row(ui_repo):
    exp, inputs = open_experiment(ui_repo, "e", {"results/e/experiment.toml": "release = 3\n"})
    rows = expdata.experiment_rows(exp, inputs)
    assert len(rows) == 1 and "results/e/experiment.toml" in rows[0]["error"]
    assert rows[0]["model"] is None and rows[0]["success_rate"] is None


def test_record_missing_field_gives_error(ui_repo, samples):
    valid, _, _ = samples
    broken = record(valid, "no_model", 1, SUCCESS)
    del broken["served_model"]
    exp, inputs = open_experiment(ui_repo, "e", files_for([broken]))
    rows = expdata.experiment_rows(exp, inputs)
    assert "served_model" in rows[0]["error"] and rows[0]["attempts"] is None


def test_impossible_moves():
    assert expdata.impossible_moves({"parsed_moves": ["R", "u", "R"]}, ["R"]) == ["u"]
    assert expdata.impossible_moves({"parsed_moves": []}, ["R"]) == []
    assert expdata.impossible_moves({}, ["R"]) == []


def test_summary_from_csv_equals_compute(ui_repo, samples, tmp_path):
    _, _, records = samples
    work = tmp_path / "work"
    (work / "e" / "raw").mkdir(parents=True)
    (work / "e" / "experiment.toml").write_text(EXP_TOML, encoding="utf-8")
    (work / "e" / "raw" / "example-model.jsonl").write_text(jsonl(records), encoding="utf-8")
    (tmp_path / "prices.toml").write_text(PRICES, encoding="utf-8")
    code = evaluate_module.main(["--experiment", "e", "--results", str(work),
                                 "--releases", str(ui_repo / "releases"),
                                 "--prices", str(tmp_path / "prices.toml")])
    assert code == 0
    exp, inputs = open_experiment(ui_repo, "e", files_for(
        records, **{"results/e/1.0.0.metrics.csv": (work / "e" / "1.0.0.metrics.csv").read_text(encoding="utf-8")}))
    from_csv = expdata.detail_metrics(exp, inputs)
    assert from_csv[2] == "report"
    exp["csv_rows"] = None
    computed = expdata.detail_metrics(exp, inputs)
    assert computed[2] == "computed" and len(computed[1]) == len(from_csv[1]) > 0
    for mine, theirs in zip(from_csv[1], computed[1]):
        for key, value in theirs.items():
            if isinstance(value, float):
                assert mine[key] == pytest.approx(value, abs=1e-4 if key == "cost_per_success" else 1e-9)
            else:
                assert mine[key] == value


def test_pooled_cost_counts_groups_without_successes():
    group = {"model": "m", "setup": "no_model", "validity": "valid"}
    csv_rows = [
        {**group, "puzzle": "2x2", "attempts": 1, "infrastructure_failure_count": 0,
         "success_rate": 0.0, "success_rate_n": 1, "cost_per_success": "n/a"},
        {**group, "puzzle": "3x3", "attempts": 1, "infrastructure_failure_count": 0,
         "success_rate": 1.0, "success_rate_n": 1, "cost_per_success": 0.1},
    ]
    costs = [{**group, "cost": 0.1}, {**group, "cost": 0.1}]
    [row] = pooled_summary(csv_rows, ["m"], costs)
    assert row["cost_per_success"] == pytest.approx(0.2)
