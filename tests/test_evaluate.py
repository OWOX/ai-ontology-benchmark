# Spec: docs/specs/evaluate.md
"""Tests for evaluate. The metric tests call compute() on a hand-built set of 12 raw records
on four 2x2 inputs. The command tests build a real release in a temporary git repo (helpers
from test_release), run the fake provider, and call evaluate's main() in-process.
"""

import json
import shutil
from pathlib import Path

import pytest

from src.evaluate import evaluate as evaluate_module
from src.evaluate.metrics import compute, wilson
from src.puzzles.registry import get_engine
from src.run import models, run as run_module
from test_release import commit_all, edit, release_ok, repo  # noqa: F401  (repo is a fixture)

PRICES = {"M": {"price_input_per_mtok": 1000.0, "price_output_per_mtok": 2000.0}}


def make_inputs() -> list[dict]:
    """Two valid inputs (one move from solved, solution R and U) and an invalid copy of each."""
    engine = get_engine("2x2")
    rows = []
    for n, seed in ((1, 1), (2, 2)):
        state, _ = engine.scramble(seed, 1)
        base = {"puzzle": "2x2", "scramble_depth": 1, "input_seed": seed, "state": state, "validity": "valid"}
        rows.append(dict(base, input_id=f"2x2-d1-00{n}"))
        bad, _ = engine.corrupt(state, seed)
        rows.append(dict(base, input_id=f"2x2-d1-00{n}-x", state=bad, validity="invalid"))
    return rows


def write_release_dir(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in make_inputs())
    (folder / "inputs.jsonl").write_text(text, encoding="utf-8")
    return folder


def raw(input_id, number, response, outcome, latency=1.0, retry=(0, 0), setup="no_model", model="M", **extra):
    stop = "infrastructure_failure" if outcome == "infrastructure_failure" else "ok"
    record = {
        "input_id": input_id, "setup": setup, "model": model, "attempt_number": number,
        "raw_response": response, "stop_reason": stop, "outcome": outcome,
        "input_tokens": 0 if stop != "ok" else 10, "output_tokens": 0 if stop != "ok" else 5,
        "retry_input_tokens": retry[0], "retry_output_tokens": retry[1],
        "latency_s": None if stop != "ok" else latency, "served_model": "m-1" if stop == "ok" else "",
        "created_at": "2026-01-01T00:00:00Z",
    }
    record.update(extra)
    return record


def answer(moves, mismatch=False):
    return json.dumps({"moves": moves, "mismatch": mismatch})


def twelve_records() -> list[dict]:
    v1, v2, i1, i2 = "2x2-d1-001", "2x2-d1-002", "2x2-d1-001-x", "2x2-d1-002-x"
    return [
        raw(v1, 1, answer(["R"]), "success", 1.0),
        raw(v1, 2, answer(["R", "U", "U'"]), "success", 3.0),
        raw(v1, 3, answer(["X"]), "hallucination", 2.0, retry=(2, 1)),
        raw(v2, 1, answer(["U"]), "success", 2.0),
        raw(v2, 2, answer([]), "failure", 4.0),
        raw(v2, 3, answer(["U"], True), "failure", 6.0),
        raw(i1, 1, answer([], True), "success"),
        raw(i1, 2, "oops", "malformed_output"),
        raw(i1, 3, answer(["X"], True), "hallucination"),
        raw(i2, 1, answer([], True), "success"),
        raw(i2, 2, answer([]), "failure"),
        raw(i2, 3, answer(["X"]), "hallucination"),
    ]


def infra_records() -> list[dict]:
    return [raw("2x2-d1-001-x", n, "", "infrastructure_failure", retry=(7, 3)) for n in (4, 5)]


@pytest.fixture
def release_dir(tmp_path):
    return write_release_dir(tmp_path / "release")


def metric(rows, validity):
    (row,) = [r for r in rows if r["validity"] == validity]
    return row


def test_wilson_seven_of_ten():
    rate, low, high = wilson(7, 10)
    assert (rate, round(low, 3), round(high, 3)) == (0.7, 0.397, 0.892)
    assert wilson(0, 0) == ("n/a", "n/a", "n/a")


def test_hand_worked_metrics(release_dir):
    attempts, metrics, summary = compute(twelve_records(), release_dir, PRICES)
    assert len(attempts) == 12 and len(metrics) == 2 and len(summary) == 2
    valid, invalid = metric(metrics, "valid"), metric(metrics, "invalid")
    assert [r["validity"] for r in metrics] == ["valid", "invalid"]
    assert (valid["attempts"], valid["infrastructure_failure_count"]) == (6, 0)
    assert (valid["success_rate"], valid["success_rate_n"]) == (0.5, 6)
    assert valid["hallucination_rate"] == pytest.approx(1 / 6)
    assert valid["false_mismatch_rate"] == pytest.approx(1 / 6)
    assert valid["malformed_output_rate"] == 0
    assert (valid["mismatch_detection_rate"], valid["mismatch_detection_rate_n"]) == ("n/a", 0)
    assert valid["efficiency"] == pytest.approx((1 + 3 + 1) / 3)
    assert valid["consistency"] == pytest.approx(2 / 3)
    assert valid["latency_per_attempt_s"] == pytest.approx(3.0)
    assert valid["input_tokens_per_attempt"] == pytest.approx(62 / 6)
    assert valid["output_tokens_per_attempt"] == pytest.approx(31 / 6)
    assert valid["cost_per_success"] == pytest.approx(0.124 / 3)
    assert invalid["success_rate"] == pytest.approx(2 / 6)
    assert invalid["hallucination_rate"] == pytest.approx(2 / 6)
    assert invalid["malformed_output_rate"] == pytest.approx(1 / 6)
    assert invalid["mismatch_detection_rate"] == pytest.approx(3 / 6)
    assert (invalid["false_mismatch_rate"], invalid["efficiency"]) == ("n/a", "n/a")
    assert invalid["consistency"] == pytest.approx(1 / 3)
    assert invalid["cost_per_success"] == pytest.approx(0.12 / 2)
    low, high = invalid["success_rate_low"], invalid["success_rate_high"]
    assert (round(low, 3), round(high, 3)) == (round(wilson(2, 6)[1], 3), round(wilson(2, 6)[2], 3))
    assert [(r["validity"], r["success_rate_n"]) for r in summary] == [("valid", 6), ("invalid", 6)]


def test_infrastructure_failures_change_only_counts_tokens_and_cost(release_dir):
    _, before, _ = compute(twelve_records(), release_dir, PRICES)
    _, after, _ = compute(twelve_records() + infra_records(), release_dir, PRICES)
    old, new = metric(before, "invalid"), metric(after, "invalid")
    assert metric(before, "valid") == metric(after, "valid")
    for name in ("success_rate", "hallucination_rate", "mismatch_detection_rate", "malformed_output_rate",
                 "success_rate_n", "efficiency", "consistency", "latency_per_attempt_s"):
        assert new[name] == old[name]
    assert (old["infrastructure_failure_count"], new["infrastructure_failure_count"]) == (0, 2)
    assert new["input_tokens_per_attempt"] == pytest.approx((60 + 14) / 8)
    assert new["output_tokens_per_attempt"] == pytest.approx((30 + 6) / 8)
    assert new["cost_per_success"] == pytest.approx((0.12 + 2 * (7 * 1000 + 3 * 2000) / 1e6) / 2)


def test_no_successes_gives_no_cost_per_success(release_dir):
    records = [raw("2x2-d1-001", 1, answer([]), "failure")]
    _, metrics, _ = compute(records, release_dir, PRICES)
    assert metrics[0]["cost_per_success"] == "n/a" and metrics[0]["efficiency"] == "n/a"


def test_changed_stored_outcome_shows_both_and_metrics_use_current(release_dir):
    records = twelve_records()
    records[1]["outcome"] = "failure"  # stored says failure, re-validation says success
    attempts, metrics, _ = compute(records, release_dir, PRICES)
    changed = [r for r in attempts if r["stored_outcome"] != r["outcome"]]
    assert [(r["stored_outcome"], r["outcome"]) for r in changed] == [("failure", "success")]
    assert metric(metrics, "valid")["success_rate"] == 0.5


def test_reference_length_not_implemented_gives_na_efficiency(release_dir, monkeypatch):
    def refuse(state):
        raise NotImplementedError("no solver")
    monkeypatch.setattr(get_engine("2x2"), "reference_length", refuse)
    _, metrics, _ = compute(twelve_records(), release_dir, PRICES)
    assert metric(metrics, "valid")["efficiency"] == "n/a"


def test_rows_sorted_by_setup_then_model_order(release_dir):
    prices = {"A": PRICES["M"], "B": PRICES["M"]}
    records = []
    for model in ("A", "B"):
        for setup in ("prescriptive", "no_model"):
            records.append(raw("2x2-d1-001", 1, answer(["R"]), "success", setup=setup, model=model))
    _, metrics, _ = compute(records, release_dir, prices, ["B", "A"])
    assert [(r["setup"], r["model"]) for r in metrics] == [
        ("no_model", "B"), ("no_model", "A"), ("prescriptive", "B"), ("prescriptive", "A")]


# ---- command tests ----

EXPERIMENT = (
    'release = "{release}"\nattempts = 2\nretry_cap = 1\nmax_output_tokens = 100\n'
    '[[models]]\nname = "A"\nprovider = "fake"\napi_model_id = "a-1"\n'
)
PRICE_FILE = "[A]\nprice_input_per_mtok = {price}\nprice_output_per_mtok = 2.0\n"


def prepare(repo, monkeypatch, release="1.0.0"):
    (repo / "config" / "experiments").mkdir(parents=True, exist_ok=True)
    (repo / "config" / "experiments" / "exp.toml").write_text(EXPERIMENT.format(release=release), encoding="utf-8")
    (repo / "config" / "prices.toml").write_text(PRICE_FILE.format(price=1.0), encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(models, "FAKE_REPLIES", [])
    assert run_module.main(["--experiment", "exp"]) == 0


def go(*extra):
    return evaluate_module.main(["--experiment", "exp", *extra])


def test_minor_bump_is_not_a_mirror(repo, monkeypatch, capsys):
    release_ok(repo, "major")
    edit(repo, "prompts/no_model/2x2.txt", "Solve this", "Please solve this")
    commit_all(repo, "t1")
    release_ok(repo, "minor")  # 1.1.0
    prepare(repo, monkeypatch, "1.1.0")
    edit(repo, "prompts/no_model/2x2.txt", "Please solve this", "Kindly solve this")
    commit_all(repo, "t2")
    release_ok(repo, "minor")  # 1.2.0
    # The working tree now renders 1.2.0 prompts, which is fine for scoring: only the assessment hash matters.
    assert go("--release", "1.2.0") == 1
    assert "mirror" in capsys.readouterr().err
    assert not (repo / "results/exp/1.2.0.md").exists()


def test_patch_mirror_scores(repo, monkeypatch):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    path = repo / "src/validator.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# fix\n", encoding="utf-8")
    commit_all(repo, "validator")
    release_ok(repo, "patch")  # 1.0.1
    assert go("--release", "1.0.1") == 0
    text = (repo / "results/exp/1.0.1.md").read_text(encoding="utf-8")
    assert text.startswith("# Experiment exp on release 1.0.1") and "mirror of release 1.0.0" in text
    assert (repo / "results/exp/1.0.1.metrics.csv").is_file()
    assert go() == 1  # 1.0.0: the assessment changed, so its hash no longer matches


def test_assessment_mismatch_refused(repo, monkeypatch, capsys):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    path = repo / "src/validator.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8")
    assert go() == 1
    assert "assessment_sha256" in capsys.readouterr().err
    assert not (repo / "results/exp/1.0.0.md").exists() and not (repo / "results/exp/prices.toml").exists()


def test_prices_copied_once_and_outputs_stable(repo, monkeypatch):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    raw_before = {p.name: p.read_bytes() for p in (repo / "results/exp/raw").iterdir()}
    assert go() == 0
    first = {n: (repo / "results/exp" / n).read_bytes() for n in ("1.0.0.md", "1.0.0.metrics.csv", "prices.toml")}
    assert go() == 0
    assert first == {n: (repo / "results/exp" / n).read_bytes() for n in first}
    assert raw_before == {p.name: p.read_bytes() for p in (repo / "results/exp/raw").iterdir()}
    (repo / "config/prices.toml").write_text(PRICE_FILE.format(price=9.0), encoding="utf-8")
    assert go() == 0
    assert first == {n: (repo / "results/exp" / n).read_bytes() for n in first}
    (repo / "results/exp/prices.toml").unlink()
    assert go() == 0
    assert (repo / "results/exp/1.0.0.md").read_bytes() != first["1.0.0.md"]
    assert "9.0" in (repo / "results/exp/prices.toml").read_text(encoding="utf-8")


def test_torn_lines_skipped_and_counted(repo, monkeypatch):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    raw_file = repo / "results/exp/raw/A.jsonl"
    first, *others = raw_file.read_text(encoding="utf-8").splitlines()
    torn_in_the_middle = '{"input_id": "x", "n": {"a": 1}'  # ends in "}" but does not parse
    text = "\n".join([first, torn_in_the_middle, *others]) + '\ngarbage\n{"input_id": "torn\n'
    raw_file.write_text(text, encoding="utf-8")
    assert go() == 0
    assert "Torn raw lines skipped: 3." in (repo / "results/exp/1.0.0.md").read_text(encoding="utf-8")


def test_record_missing_a_field_refused(repo, monkeypatch, capsys):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    raw_file = repo / "results/exp/raw/A.jsonl"
    raw_file.write_text(raw_file.read_text(encoding="utf-8") + '{"input_id": "x"}\n', encoding="utf-8")
    assert go() == 1
    err = capsys.readouterr().err
    assert "A.jsonl" in err and "field" in err


def test_duplicate_attempt_refused(repo, monkeypatch, capsys):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    raw_file = repo / "results/exp/raw/A.jsonl"
    first = raw_file.read_text(encoding="utf-8").splitlines()[0]
    raw_file.write_text(raw_file.read_text(encoding="utf-8") + first + "\n", encoding="utf-8")
    assert go() == 1
    err = capsys.readouterr().err
    assert "A.jsonl" in err and "more than once" in err
    assert not (repo / "results/exp/1.0.0.md").exists()


def test_config_model_without_price_refused_and_nothing_written(repo, monkeypatch, capsys):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    config = repo / "config/experiments/exp.toml"
    (repo / "results/exp/experiment.toml").write_text(
        config.read_text(encoding="utf-8")
        + '[[models]]\nname = "Z"\nprovider = "fake"\napi_model_id = "z-1"\n', encoding="utf-8")
    assert go() == 1
    err = capsys.readouterr().err
    assert "prices.toml" in err and "'Z'" in err
    for name in ("prices.toml", "1.0.0.md", "1.0.0.metrics.csv"):
        assert not (repo / "results/exp" / name).exists()


def test_decision_model_records_are_parsed_as_arrays(release_dir):
    legal = get_engine("2x2").legal_moves()
    state, scramble = get_engine("2x2").scramble(1, 1)
    inverse = {"": "'", "'": "", "2": "2"}
    solve = scramble[0][0] + inverse[scramble[0][1:]]
    calls = [{"answers": {"next_move": {"choice": f"move_{legal.index(solve) + 1}"}, "mismatch": {"noul": 0.1}}},
             {"answers": {"next_move": {"choice": "done"}, "mismatch": {"noul": 0.1}}}]
    record = raw("2x2-d1-001", 1, json.dumps(calls), "success", model="M")
    attempts, _, _ = compute([record], release_dir, PRICES, decision_models={"M"})
    assert attempts[0]["outcome"] == "success"
    attempts, _, _ = compute([record], release_dir, PRICES)
    assert attempts[0]["outcome"] == "malformed_output"
