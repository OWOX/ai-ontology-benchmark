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
from ui.catalogue import build_providers
from ui import secrets as key_store
from ui.bundle import Bundles, is_mirror
from ui.common import ApiError
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
SUCCESS = "MISMATCH"
HALLUCINATION = "u"
FAILURE = "U"


class Reply:
    def __init__(self, text, stop="ok"):
        self.text, self.stop_reason, self.served_model = text, stop, "served-1"
        self.input_tokens, self.output_tokens, self.latency_s = 10, 5, 0.5


def record(input_row, setup, attempt, reply, model="example-model"):
    """A raw record as `run` writes it; `reply` is text, or None for an infrastructure failure."""
    config = {"experiment_id": "x", "release": "1.0.0"}
    made = make_record(config, MANIFEST, input_row, {"name": model, "api_model_id": "ex-1"}, setup, attempt, "", VERSIONS,
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
    records = [record(valid, "no_model", 1, HALLUCINATION), record(valid, "descriptive", 1, ""),
               record(invalid, "no_model", 1, SUCCESS), record(invalid, "prescriptive", 1, FAILURE)]
    return valid, invalid, records


def files_for(records, **extra):
    return {"results/e/experiment.toml": EXP_TOML,
            "results/e/raw/example-model.jsonl": jsonl(records), **extra}


def files_as(experiment_id, files):
    return {path.replace("results/e/", f"results/{experiment_id}/"): text for path, text in files.items()}


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


# --- bundle ----------------------------------------------------------------------------------

def make_bundles(ui_repo):
    # a clock that advances 100 s per read, so every refresh is past the 30-second throttle
    ticks = iter(range(0, 10**6, 100))
    return Bundles(ui_repo, GitData(ui_repo, clock=lambda: next(ticks)))


def exp_ids(bundle):
    return sorted({r["id"] for r in bundle["experiments"]})


def test_bundle_reads_refs_only(ui_repo, samples):
    _, _, records = samples
    (ui_repo / "results" / "x").mkdir(parents=True)
    (ui_repo / "results" / "x" / "experiment.toml").write_text(EXP_TOML, encoding="utf-8")
    bundles = make_bundles(ui_repo)
    assert exp_ids(bundles.get(None, True, set(), {}, set())) == []
    push_results(ui_repo, "e", files_for(records))
    bundle = bundles.get(None, True, set(), {}, set())
    assert exp_ids(bundle) == ["e"] and bundle["schema"] == 2 and bundle["release"] == "1.0.0"
    assert [r["validity"] for r in bundle["experiments"]] == ["all", "valid", "invalid"]
    assert bundle["defaults"]["attempts"] == 3
    with pytest.raises(ApiError) as caught:
        bundles.get("9.9.9", False, set(), {}, set())
    assert caught.value.status == 400 and "'release'" in caught.value.message


def test_bundle_cache_by_sha(ui_repo, samples, monkeypatch):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    calls = []
    real = expdata.load_experiment
    monkeypatch.setattr(expdata, "load_experiment", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    bundles = make_bundles(ui_repo)
    first = bundles.get(None, True, set(), {}, set())
    assert bundles.get(None, False, set(), {}, set()) == first and calls == ["e"]
    push_results(ui_repo, "f", files_as("f", files_for(records)))
    second = bundles.get(None, True, set(), {}, set())
    assert exp_ids(second) == ["e", "f"] and calls.count("f") == 1


def test_malformed_parsed_moves_do_not_break_bundle(ui_repo, samples):
    valid, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    for name, bad in (("b1", [{}]), ("b2", "R"), ("b3", [None, ["R"]])):
        broken = {**record(valid, "no_model", 1, HALLUCINATION), "parsed_moves": bad}
        push_results(ui_repo, name, files_as(name, files_for([broken])))
    bundle = make_bundles(ui_repo).get(None, True, set(), {}, set())
    assert exp_ids(bundle) == ["b1", "b2", "b3", "e"]
    seen = next(p for p in bundle["puzzles"] if p["name"] == "2x2")["impossible_seen"]
    assert [(s["move"], s["count"]) for s in seen] == [("u", 4)] and seen[0]["experiments"] == ["b1", "b2", "b3", "e"]  # counted after re-validation


def test_key_status_not_cached(ui_repo):
    bundles = make_bundles(ui_repo)

    def cloud(bundle):
        provider = next(p for p in bundle["providers"] if p["name"] == "anthropic")
        return provider["key"], next(m for m in provider["models"] if m["name"] == "cloud-model")

    key, model = cloud(bundles.get(None, True, set(), {}, set()))
    assert key["source"] == "missing" and model["disabled_reason"] == "no API key: add it under Models"
    key_store.save(ui_repo, "anthropic", "sk-test-1234")
    key, model = cloud(bundles.get(None, False, set(), {}, set()))
    assert key["source"] == "file" and key["tail"] == "1234" and model["disabled_reason"] is None
    bundle = bundles.get(None, False, set(), {}, set())
    assert [p["name"] for p in bundle["providers"]] == ["anthropic", "cloudflare", "fake"]
    assert next(p for p in bundle["providers"] if p["name"] == "fake")["key"] is None
    assert all(p["models"] for p in bundle["providers"])
    unpriced = next(m for p in bundle["providers"] for m in p["models"] if m["name"] == "unpriced")
    assert unpriced["disabled_reason"] == "no price in config/prices.toml" and unpriced["price"] is None


def test_cloudflare_reason_names_what_is_missing(ui_repo, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    bundles = make_bundles(ui_repo)

    def reason():
        provider = {"name": "cloudflare", "variable": "CLOUDFLARE_API_TOKEN", "models": [{"disabled_reason": None}]}
        return bundles._fill_keys({"providers": [provider]}, dict(os.environ))["providers"][0]["models"][0]["disabled_reason"]

    assert reason() == "no API key: add it under Models"
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    assert reason() == "no account id: add it under Models"
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    assert reason() is None


def test_model_matching(ui_repo, samples):
    _, _, records = samples
    renamed = EXP_TOML.replace('name = "example-model"', 'name = "renamed"')
    push_results(ui_repo, "e", {"results/e/experiment.toml": renamed,
                                "results/e/raw/renamed.jsonl": jsonl([dict(r, model="renamed") for r in records])})
    same = {"results/e/experiment.toml": EXP_TOML + "params = { temperature = 1.0 }\n",
            "results/e/raw/example-model.jsonl": jsonl(records)}
    push_results(ui_repo, "g", files_as("g", same))
    bundle = make_bundles(ui_repo).get(None, True, set(), {}, set())
    catalogue = next(m for p in bundle["providers"] for m in p["models"] if m["name"] == "example-model")
    assert catalogue["experiments"] == ["e", "g"]
    differs = {r["id"]: r["differs_from_catalogue"] for r in bundle["experiments"]}
    assert differs == {"e": True, "g": False}


def test_kind_shown_but_ignored_by_differs_from_catalogue(ui_repo, samples):
    _, _, records = samples
    # the catalogue says system-2; one experiment says system-1, another has no kind at all
    other = {"results/k/experiment.toml": EXP_TOML + 'kind = "system-1"\nparams = { temperature = 1.0 }\n',
             "results/k/raw/example-model.jsonl": jsonl(records)}
    push_results(ui_repo, "k", other)
    plain = {"results/p/experiment.toml": EXP_TOML + "params = { temperature = 1.0 }\n", "results/p/raw/example-model.jsonl": jsonl(records)}
    push_results(ui_repo, "p", plain)
    bundles = make_bundles(ui_repo)
    bundle = bundles.get(None, True, set(), {}, set())
    kinds = {m["name"]: m["kind"] for p in bundle["providers"] for m in p["models"]}
    assert kinds == {"example-model": "system-2", "cloud-model": None, "unpriced": None, "edge-model": None}
    differs = {r["id"]: r["differs_from_catalogue"] for r in bundle["experiments"]}
    assert differs == {"k": False, "p": False}
    assert bundles.experiment("k", set(), set())["model_entries"][0]["kind"] == "system-1"
    assert bundles.experiment("p", set(), set())["model_entries"][0]["kind"] is None


def test_impossible_seen(ui_repo, samples):
    valid, _, _ = samples
    reply = "u\nx\nu"
    push_results(ui_repo, "e", files_for([record(valid, "no_model", 1, reply)]))
    puzzle = make_bundles(ui_repo).get(None, True, set(), {}, set())["puzzles"][0]
    assert [(m["move"], m["count"]) for m in puzzle["impossible_seen"]] == [("u", 2), ("x", 1)]
    assert puzzle["impossible_seen"][0]["models"] == ["example-model"]
    assert puzzle["impossible_seen"][0]["experiments"] == ["e"]
    assert "U" in puzzle["legal_moves"] and puzzle["n"] == 2


def sources(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("source") and isinstance(item, str):
                yield item
            else:
                yield from sources(item)
    elif isinstance(value, list):
        for item in value:
            yield from sources(item)


def test_links_pin_sha(ui_repo, samples, monkeypatch):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    monkeypatch.setattr(GitData, "github", lambda self: "https://github.com/o/r")
    bundles = make_bundles(ui_repo)
    bundle = bundles.get(None, True, set(), {}, set())
    found = list(sources(bundle["puzzles"])) + [bundle["about"]["source"]]
    assert len(found) >= 5
    assert all(s.startswith(f"https://github.com/o/r/blob/{bundle['main_sha']}/") for s in found)
    sha = bundles.git.sha("refs/remotes/origin/results/e")
    assert {r["branch"] for r in bundle["experiments"]} == {f"https://github.com/o/r/tree/{sha}/results/e"}
    assert bundle["repo"] == "https://github.com/o/r"


def test_failed_fetch_keeps_old_refs(ui_repo, samples):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    bundles = make_bundles(ui_repo)
    good = bundles.get(None, True, set(), {}, set())
    assert good["fetch_error"] is None and good["fetched_at"]
    git(ui_repo, "remote", "set-url", "origin", str(ui_repo / "missing.git"))
    bad = bundles.get(None, True, set(), {}, set())
    assert exp_ids(bad) == ["e"] and bad["fetch_error"]
    assert bad["fetched_at"] == good["fetched_at"]


def test_live_and_pushed_flags(ui_repo, samples):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    bundles = make_bundles(ui_repo)
    assert {(r["pushed"], r["running"]) for r in bundles.get(None, True, set(), {}, set())["experiments"]} == {(True, False)}
    tip = "refs/remotes/origin/results/e"
    ahead = git(ui_repo, "commit-tree", f"{tip}^{{tree}}", "-p", tip, "-m", "local record").strip()
    git(ui_repo, "update-ref", "refs/heads/results/e", ahead)
    live = bundles.get(None, False, {"e"}, {}, {"e"})
    assert {(r["pushed"], r["running"]) for r in live["experiments"]} == {(False, True)}


def test_detail_inputs_branches(ui_repo, samples):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    bundles = make_bundles(ui_repo)
    bundles.get(None, True, set(), {}, set())
    detail = bundles.experiment("e", set(), set())
    assert detail["id"] == "e" and detail["release"] == "1.0.0" and detail["config"]["models"] == ["example-model"]
    assert detail["metrics_source"] == "computed" and detail["metric_rows"] and detail["report"] is None
    assert detail["served_models"] == {"example-model": ["served-1"]}
    assert detail["local_results"] is False
    assert [m["name"] for m in detail["model_entries"]] == ["example-model"]
    assert set(detail["model_entries"][0]) == {"name", "provider", "api_model_id", "kind", "params"}
    (ui_repo / "results" / "e").mkdir(parents=True)
    (ui_repo / "results" / "e" / "experiment.toml").write_text("x", encoding="utf-8")
    assert bundles.experiment("e", set(), set())["local_results"] is True
    assert bundles.experiment("e", set(), set())["local_report"] is False
    (ui_repo / "results" / "e" / "0.9.0.md").write_text("r", encoding="utf-8")
    assert bundles.experiment("e", set(), set())["local_report"] is False
    (ui_repo / "results" / "e" / "1.0.0.md").write_text("r", encoding="utf-8")
    assert bundles.experiment("e", set(), set())["local_report"] is True
    with pytest.raises(ApiError) as caught:
        bundles.experiment("nope", set(), set())
    assert caught.value.status == 404
    rows = bundles.inputs("1.0.0", "2x2")
    assert rows and set(rows[0]) == {"input_id", "scramble_depth", "validity", "state", "scramble",
                                     "source_input_id", "corruption"}
    for release, puzzle in (("9.9.9", "2x2"), ("1.0.0", "7x7")):
        with pytest.raises(ApiError) as caught:
            bundles.inputs(release, puzzle)
        assert caught.value.status == 400
    assert bundles.branches() == [{"id": "e", "release": "1.0.0", "local": False, "remote": True}]
    assert bundles.releases() == ["1.0.0"]


def test_no_writes(ui_repo, samples):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    bundles = make_bundles(ui_repo)
    bundles.get(None, True, set(), {}, set())

    def snapshot():
        status = git(ui_repo, "status", "--porcelain", "--ignored")
        times = {str(p): p.stat().st_mtime_ns for p in ui_repo.rglob("*")
                 if ".git" not in p.relative_to(ui_repo).parts and "__pycache__" not in p.parts}
        return status, times

    before = snapshot()
    bundles.get(None, False, {"e"}, {}, {"e"})
    bundles.experiment("e", set(), set()); bundles.inputs("1.0.0", "2x2"); bundles.branches(); bundles.releases()
    assert snapshot() == before


def test_refresh_respects_throttle(ui_repo):
    git_data = GitData(ui_repo, clock=lambda: 100.0)
    fetches = []
    real = git_data._git
    git_data._git = lambda *a, **k: (fetches.append(a) if a[0] == "fetch" else None) or real(*a, **k)
    bundles = Bundles(ui_repo, git_data)
    bundles.get(None, True, set(), {}, set())
    bundles.get(None, True, set(), {}, set())   # inside the 30-second limit: no second fetch
    assert len(fetches) == 1


def test_is_mirror():
    def manifest(inputs_hash):
        return {"files": {"inputs.jsonl": inputs_hash}}

    manifests = {"1.0.0": manifest("a"), "1.0.1": manifest("a"), "1.1.0": manifest("a"),
                 "2.0.0": manifest("b"), "1.0.2": manifest("c"), "bad": None}
    assert is_mirror("1.0.1", "1.0.0", manifests) and is_mirror("1.0.0", "1.0.0", manifests)
    assert not is_mirror("1.0.1", "1.1.0", manifests)    # a different minor is not a mirror
    assert not is_mirror("1.0.1", "1.0.2", manifests)    # different inputs
    assert not is_mirror("1.0.1", "2.0.0", manifests) and not is_mirror("1.0.1", "9.9.9", manifests)
    assert not is_mirror("1.0.1", None, manifests)


def broken_files(kind, records, valid):
    if kind == "null_tokens":
        bad = dict(record(valid, "no_model", 1, SUCCESS), input_tokens=None)
        return files_for([bad])
    if kind == "prices_not_table":
        return files_for(records, **{"results/e/prices.toml": 'example-model = 5\n'})
    header = "puzzle,setup,model,scramble_depth,infrastructure_failure_count,success_rate,success_rate_n\n"
    return files_for(records, **{"results/e/1.0.0.metrics.csv": header + "2x2,no_model,example-model,5,0,0.5,2\n"})


@pytest.mark.parametrize("kind", ["null_tokens", "prices_not_table", "csv_missing_column"])
def test_malformed_branch_isolated(ui_repo, samples, kind):
    valid, _, records = samples
    push_results(ui_repo, "ok", files_as("ok", files_for(records)))
    push_results(ui_repo, "e", broken_files(kind, records, valid))
    bundles = make_bundles(ui_repo)
    rows = bundles.get(None, True, set(), {}, set())["experiments"]
    bad = [r for r in rows if r["id"] == "e"]
    good = [r for r in rows if r["id"] == "ok"]
    assert bad and all(r["error"] and "results/e" in r["error"] for r in bad)
    assert good and all(r["error"] is None for r in good) and any(r["attempts"] for r in good)
    detail = bundles.experiment("e", set(), set())
    assert detail["error"] and "results/e" in detail["error"]


def test_provider_without_catalogue_models_is_left_out():
    from ui.catalogue import PROVIDER_ORDER
    catalogue = {"m": {"name": "m", "provider": "typesafe", "api_model_id": "x"}}
    assert PROVIDER_ORDER[3:5] == ("typesafe", "cloudflare")
    assert [p["name"] for p in build_providers(catalogue, {}, [])] == ["typesafe"]


def test_decision_model_attempts_are_scored_not_malformed(ui_repo, samples):
    _, invalid, _ = samples
    calls = json.dumps([{"answers": {"next_move": {"choice": "mismatch"}}}])
    toml = EXP_TOML.replace('provider = "fake"', 'provider = "fake_decision"')
    old = record(invalid, "no_model", 1, calls)
    del old["decision"], old["requested_model"]  # a record written before the fields existed
    files = {"results/e/experiment.toml": toml, "results/e/raw/example-model.jsonl": jsonl([old])}
    exp, inputs = open_experiment(ui_repo, "e", files)
    rows = expdata.attempt_rows(exp, inputs)
    assert [r["outcome"] for r in rows] == ["success"]

    flagged = record(invalid, "no_model", 1, calls) | {"decision": True}
    # The config says this model is not a decision model, and the record's own flag wins.
    files = {"results/e2/experiment.toml": EXP_TOML, "results/e2/raw/example-model.jsonl": jsonl([flagged])}
    exp, inputs = open_experiment(ui_repo, "e2", files)
    assert [r["outcome"] for r in expdata.attempt_rows(exp, inputs)] == ["success"]


# --- benchmarks -------------------------------------------------------------------------------

OTHER_TOML = EXP_TOML + '[[models]]\nname = "cloud-model"\nprovider = "anthropic"\napi_model_id = "cl-1"\n'


def bench_query(**kwargs):
    return {k: kwargs.get(k) for k in ("releases", "models", "puzzles", "setups", "validity")}


def two_model_files(ui_repo, replies):
    """Experiment `e` with both models, one reply per (model, input, setup) from `replies(model, row, setup)`."""
    inputs = [json.loads(line) for line in
              (ui_repo / "releases" / "1.0.0" / "inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    files = {"results/e/experiment.toml": OTHER_TOML}
    for model in ("example-model", "cloud-model"):
        recs = [record(r, s, 1, replies(model, r, s), model=model) for r in inputs
                for s in ("no_model", "descriptive", "prescriptive")]
        files[f"results/e/raw/{model}.jsonl"] = jsonl(recs)
    return files, inputs


def test_benchmarks_pooled_rates_equal_metrics(ui_repo, samples):
    from src.evaluate.metrics import rates
    _, _, records = samples
    exp, inputs = open_experiment(ui_repo, "e", files_for(records))
    out = make_bundles(ui_repo).benchmarks(bench_query(), set())
    done = [r for r in expdata.attempt_rows(exp, inputs) if r["outcome"] != "infrastructure_failure"]
    expected = expdata.all_scope_rates(done)
    cells = {r["metric"]: r["cells"]["example-model"] for r in out["rows"] if r["puzzle"] == "2x2"}
    assert out["experiments"] == ["e"] and out["releases"] == ["1.0.0"] and out["skipped"] == []
    for metric in ("success_rate", "hallucination_rate", "mismatch_detection_rate", "false_mismatch_rate",
                   "malformed_output_rate"):
        assert cells[metric] == {"value": expected[metric], "low": expected[metric + "_low"],
                                 "high": expected[metric + "_high"], "n": expected[metric + "_n"]}
    invalid = out_for(ui_repo, validity="invalid")
    only = rates([r for r in done if r["validity"] == "invalid"], "invalid")
    assert invalid["success_rate"]["value"] == only["success_rate"]
    assert invalid["efficiency"]["value"] is None and invalid["false_mismatch_rate"]["value"] is None
    valid = out_for(ui_repo, validity="valid")
    assert valid["mismatch_detection_rate"]["value"] is None and valid["mismatch_detection_rate"]["n"] == 0
    assert [r["metric"] for r in out["rows"]][:3] == ["success_rate", "hallucination_rate", "mismatch_detection_rate"]
    assert cells["tokens_per_attempt"] == {"value": 20, "n": 4}


def out_for(ui_repo, **kwargs):
    out = make_bundles(ui_repo).benchmarks(bench_query(**kwargs), set())
    return {r["metric"]: r["cells"]["example-model"] for r in out["rows"]}


def test_benchmarks_one_cell_has_no_best_and_worst(ui_repo, samples):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    rows = make_bundles(ui_repo).benchmarks(bench_query(), set())["rows"]
    assert all(r["best"] is None and r["worst"] is None for r in rows)


def test_benchmarks_two_models_share_one_test(ui_repo):
    from src.evaluate.metrics import sign_test
    files, inputs = two_model_files(ui_repo, lambda model, row, setup:
                                    HALLUCINATION if model == "example-model" else FAILURE)
    push_results(ui_repo, "e", files)
    out = make_bundles(ui_repo).benchmarks(bench_query(), set())
    assert [m["name"] for m in out["models"]] == ["cloud-model", "example-model"]  # provider order: anthropic, fake
    assert {p["name"] for p in out["options"]["providers"]} == {"anthropic", "fake"}
    row = next(r for r in out["rows"] if r["metric"] == "hallucination_rate")
    assert row["tested"] and row["best"]["model"] == "cloud-model" and row["worst"]["model"] == "example-model"
    assert row["best"]["against"] == "example-model" and row["worst"]["against"] == "cloud-model"
    assert row["best"]["inputs_paired"] == len(inputs)
    assert row["best"]["p_value"] == row["worst"]["p_value"] == sign_test(len(inputs), 0)
    assert row["best"]["p_holm"] == row["best"]["p_value"] == row["worst"]["p_holm"]
    eff = next(r for r in out["rows"] if r["metric"] == "efficiency")
    assert eff["tested"] is False and "p_value" not in (eff["best"] or {})


def test_benchmarks_filters_narrow_models_not_options(ui_repo):
    files, _ = two_model_files(ui_repo, lambda *a: FAILURE)
    push_results(ui_repo, "e", files)
    out = make_bundles(ui_repo).benchmarks(bench_query(models=["cloud-model", "gone"], setups=["no_model"]), set())
    assert [m["name"] for m in out["models"]] == ["cloud-model"]
    assert sorted(m for p in out["options"]["providers"] for m in p["models"]) == ["cloud-model", "example-model"]
    assert all(set(r["cells"]) == {"cloud-model"} for r in out["rows"])


@pytest.mark.parametrize("field,value", [("releases", ["9.9.9"]), ("puzzles", ["7x7"]), ("setups", ["x"]),
                                         ("validity", "some")])
def test_benchmarks_unknown_choice_is_400(ui_repo, field, value):
    with pytest.raises(ApiError) as caught:
        make_bundles(ui_repo).benchmarks(bench_query(**{field: value}), set())
    assert caught.value.status == 400 and f"'{field}'" in caught.value.message


def test_benchmarks_reads_once_and_caches(ui_repo, samples, monkeypatch):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    push_results(ui_repo, "f", files_as("f", files_for(records)))
    calls = []
    real = expdata.load_experiment
    monkeypatch.setattr(expdata, "load_experiment", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    bundles = make_bundles(ui_repo)
    first = bundles.benchmarks(bench_query(), set())
    assert bundles.benchmarks(bench_query(), set()) is first and sorted(calls) == ["e", "f"]
    assert first["experiments"] == ["e", "f"]


def test_benchmarks_broken_experiment_is_skipped(ui_repo, samples):
    _, _, records = samples
    bad = [dict(r) for r in records]
    del bad[0]["raw_response"]
    push_results(ui_repo, "e", files_for(records))
    push_results(ui_repo, "f", files_as("f", files_for(bad)))
    out = make_bundles(ui_repo).benchmarks(bench_query(), set())
    assert out["experiments"] == ["e"] and [s["id"] for s in out["skipped"]] == ["f"] and out["skipped"][0]["error"]


def synthetic(model, input_id, outcome, set_id="1", puzzle="2x2", validity="valid", mismatch=False, setup="no_model"):
    return {"model": model, "input_id": input_id, "input_set_id": set_id, "puzzle": puzzle, "validity": validity,
            "outcome": outcome, "mismatch": mismatch, "setup": setup, "reference_length": 3, "move_count": 3,
            "latency_s": 1.0, "input_tokens": 1, "output_tokens": 1, "retry_input_tokens": 0,
            "retry_output_tokens": 0, "cost": 0.5}


def test_pairing_uses_input_set_id():
    from ui import benchmarks as bm
    a = [synthetic("a", "i1", "success"), synthetic("a", "i2", "failure")]
    b = [synthetic("b", "i1", "failure", set_id="2"), synthetic("b", "i2", "failure")]
    test = bm.paired_model_test(a, b, "success_rate")
    assert test["inputs_paired"] == 1          # i1 under set 2 is another input


def test_ties_and_holm_over_distinct_tests():
    from src.evaluate.metrics import holm, sign_test
    from ui import benchmarks as bm
    ids = [f"i{n}" for n in range(8)]
    rows = ([synthetic("a", i, "success") for i in ids]
            + [synthetic("b", i, "success" if n < 4 else "failure") for n, i in enumerate(ids)]
            + [synthetic("c", i, "failure") for i in ids])
    row = next(r for r in bm.build_rows(rows, ["a", "b", "c"], ["2x2"], "valid") if r["metric"] == "success_rate")
    p_ab, p_bc = sign_test(4, 0), sign_test(4, 0)
    assert (row["best"]["model"], row["best"]["against"]) == ("a", "b")
    assert (row["worst"]["model"], row["worst"]["against"]) == ("c", "b")
    assert row["best"]["p_value"] == p_ab and row["best"]["p_holm"] == holm([p_ab, p_bc])[0]
    tied = [synthetic("a", "i0", "success"), synthetic("b", "i0", "success"), synthetic("c", "i0", "failure")]
    row = next(r for r in bm.build_rows(tied, ["a", "b", "c"], ["2x2"], "valid") if r["metric"] == "success_rate")
    assert row["best"] is None and row["worst"]["model"] == "c"


def test_unpriced_model_has_no_cost_per_success():
    from ui import benchmarks as bm
    rows = [dict(synthetic("a", "i1", "success"), priced=False), synthetic("b", "i1", "success")]
    row = next(r for r in bm.build_rows(rows, ["a", "b"], ["2x2"], "valid") if r["metric"] == "cost_per_success")
    assert row["cells"]["a"]["value"] is None and row["cells"]["b"]["value"] == 0.5
    assert row["best"] is None and row["worst"] is None


def test_efficiency_n_counts_ratios():
    from ui import benchmarks as bm
    rows = [synthetic("a", "i1", "success"), synthetic("a", "i2", "failure")]
    row = next(r for r in bm.build_rows(rows, ["a"], ["2x2"], "valid") if r["metric"] == "efficiency")
    assert row["cells"]["a"] == {"value": 1.0, "n": 1}


def test_benchmarks_only_unknown_models_means_no_filter(ui_repo, samples):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    out = make_bundles(ui_repo).benchmarks(bench_query(models=["gone"]), set())
    assert [m["name"] for m in out["models"]] == ["example-model"] and out["rows"]


def test_benchmarks_moved_ref_gives_new_answer(ui_repo, samples):
    _, _, records = samples
    push_results(ui_repo, "e", files_for(records))
    bundles = make_bundles(ui_repo)
    first = bundles.benchmarks(bench_query(), set())
    push_results(ui_repo, "f", files_as("f", files_for(records)))
    bundles.git.fetch(force=True)
    second = bundles.benchmarks(bench_query(), set())
    assert first["experiments"] == ["e"] and second["experiments"] == ["e", "f"]
    assert not bundles._cache  # separate from the bundle cache


def test_benchmarks_mirror_release_is_read_once(ui_repo, samples, monkeypatch):
    _, _, records = samples
    release = ui_repo / "releases" / "1.0.1"
    release.mkdir()
    source = ui_repo / "releases" / "1.0.0"
    (release / "inputs.jsonl").write_text((source / "inputs.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    git(ui_repo, "add", "releases/1.0.1")
    git(ui_repo, "commit", "-q", "-m", "mirror")
    git(ui_repo, "push", "-q", "origin", "HEAD:refs/heads/main")
    files = files_for(records)
    push_results(ui_repo, "m", {"results/m/experiment.toml": EXP_TOML.replace('"1.0.0"', '"1.0.1"'),
                                "results/m/raw/example-model.jsonl": files["results/e/raw/example-model.jsonl"]})
    calls = []
    real = expdata.load_experiment
    monkeypatch.setattr(expdata, "load_experiment", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    bundles = make_bundles(ui_repo)
    out = bundles.benchmarks(bench_query(releases=["1.0.0"]), set())
    assert out["experiments"] == ["m"] and out["skipped"] == [] and calls == ["m"]
    calls.clear()
    out = bundles.benchmarks(bench_query(releases=["1.0.0", "1.0.1"]), set())
    assert out["experiments"] == ["m"] and calls == ["m"]
