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
from src.evaluate.metrics import CORRUPTION_COLUMNS, DETECTION_COLUMNS, bootstrap_interval, compute, corruption_rows, corruption_type, detection_rows, holm, paired_tests, rates, sign_test
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


def answer(moves):
    """The line format: the moves one per line, or the single line MISMATCH for an empty list."""
    return "\n".join(moves) if moves else "MISMATCH"


def twelve_records() -> list[dict]:
    v1, v2, i1, i2 = "2x2-d1-001", "2x2-d1-002", "2x2-d1-001-x", "2x2-d1-002-x"
    return [
        raw(v1, 1, answer(["R"]), "success", 1.0),
        raw(v1, 2, answer(["R", "U", "U'"]), "success", 3.0),
        raw(v1, 3, answer(["M"]), "hallucination", 2.0, retry=(2, 1)),
        raw(v2, 1, answer(["U"]), "success", 2.0),
        raw(v2, 2, answer(["R"]), "failure", 4.0),
        raw(v2, 3, answer([]), "failure", 6.0),
        raw(i1, 1, answer([]), "success"),
        raw(i1, 2, " \n", "malformed_output"),
        raw(i1, 3, answer(["M"]), "hallucination"),
        raw(i2, 1, answer([]), "success"),
        raw(i2, 2, answer(["R"]), "failure"),
        raw(i2, 3, answer(["M"]), "hallucination"),
    ]


def infra_records() -> list[dict]:
    return [raw("2x2-d1-001-x", n, "", "infrastructure_failure", retry=(7, 3)) for n in (4, 5)]


@pytest.fixture
def release_dir(tmp_path):
    return write_release_dir(tmp_path / "release")


def metric(rows, validity):
    (row,) = [r for r in rows if r["validity"] == validity]
    return row


def test_bootstrap_is_deterministic():
    cells = [(1, 3), (0, 3), (3, 3), (2, 3)]
    a = bootstrap_interval(cells, "g|success_rate")
    assert a == bootstrap_interval(cells, "g|success_rate")
    assert a[0] == 0.5 and 0.0 <= a[1] <= 0.5 <= a[2] <= 1.0


def test_bootstrap_pinned_values():
    """Pins the seeding and key format: a change to either moves the interval."""
    rate, low, high = bootstrap_interval([(1, 3), (0, 3), (3, 3), (2, 3)], "g|success_rate")
    assert rate == 0.5 and low == pytest.approx(0.0833333333) and high == pytest.approx(0.8333333333)


def test_bootstrap_one_input_has_no_interval():
    assert bootstrap_interval([(2, 3)], "k") == (2 / 3, "n/a", "n/a")


def test_bootstrap_empty():
    assert bootstrap_interval([], "k") == ("n/a", "n/a", "n/a")


def test_bootstrap_all_hits():
    assert bootstrap_interval([(3, 3)] * 10, "k") == (1.0, 1.0, 1.0)


def test_clustered_interval_is_wider_than_independent():
    clustered = bootstrap_interval([(3, 3)] * 5 + [(0, 3)] * 5, "k")
    independent = bootstrap_interval([(1, 1)] * 15 + [(0, 1)] * 15, "k")
    assert clustered[2] - clustered[1] > independent[2] - independent[1]


def test_balanced_accuracy_interval_is_stratified_and_deterministic():
    rows = ([_row(f"v{i}", "valid", mismatch=i == 1) for i in range(1, 5)]
            + [_row(f"x{i}", "invalid", mismatch=i != 4) for i in range(1, 5)])
    [row] = detection_rows(rows, ["m"])
    assert row == detection_rows(rows, ["m"])[0]
    assert row["balanced_accuracy_low"] == 0.375 and row["balanced_accuracy_high"] == 1.0


def test_balanced_accuracy_draws_each_side_separately():
    """With 2 valid and 2 invalid inputs, an unstratified draw can leave one side empty."""
    rows = [_row("v1", "valid", False), _row("v2", "valid", False),
            _row("x1", "invalid", True), _row("x2", "invalid", True)]
    row = detection_rows(rows, ["m"])[0]
    assert (row["balanced_accuracy_low"], row["balanced_accuracy_high"]) == (1.0, 1.0)


def test_balanced_accuracy_interval_needs_two_inputs_per_side():
    rows = [_row("v1", "valid", False), _row("x1", "invalid", True), _row("x2", "invalid", True)]
    row = detection_rows(rows, ["m"])[0]
    assert row["balanced_accuracy"] == 1.0 and row["balanced_accuracy_low"] == "n/a"


def test_hand_worked_metrics(release_dir):
    attempts, metrics, summary = compute(twelve_records(), release_dir, PRICES)
    assert len(attempts) == 12 and len(metrics) == 2 and len(summary) == 2
    valid, invalid = metric(metrics, "valid"), metric(metrics, "invalid")
    assert [r["validity"] for r in metrics] == ["valid", "invalid"]
    assert (valid["attempts"], valid["infrastructure_failure_count"]) == (6, 0)
    assert (valid["success_rate"], valid["success_rate_n"]) == (0.5, 6)
    assert valid["hallucination_rate"] == pytest.approx(1 / 5)  # 5 of the 6 attempts gave moves
    assert valid["hallucination_rate_n"] == 5
    assert valid["false_mismatch_rate"] == pytest.approx(1 / 6)
    assert valid["malformed_output_rate"] == 0
    assert (valid["mismatch_detection_rate"], valid["mismatch_detection_rate_n"]) == ("n/a", 0)
    assert valid["consistency"] == pytest.approx(2 / 3)
    assert valid["latency_per_attempt_s"] == pytest.approx(3.0)
    assert valid["input_tokens_per_attempt"] == pytest.approx(62 / 6)
    assert valid["output_tokens_per_attempt"] == pytest.approx(31 / 6)
    assert valid["cost_per_success"] == pytest.approx(0.124 / 3)
    assert invalid["success_rate"] == pytest.approx(2 / 6)
    assert invalid["hallucination_rate"] == pytest.approx(2 / 3)  # MISMATCH and malformed attempts left out
    assert invalid["hallucination_rate_n"] == 3
    assert invalid["malformed_output_rate"] == pytest.approx(1 / 6)
    assert invalid["mismatch_detection_rate"] == pytest.approx(2 / 6)
    assert invalid["false_mismatch_rate"] == "n/a"
    assert invalid["consistency"] == pytest.approx(1 / 3)
    assert invalid["cost_per_success"] == pytest.approx(0.12 / 2)
    assert invalid["success_rate_low"] <= 2 / 6 <= invalid["success_rate_high"]
    assert invalid["success_rate_inputs"] == 2 and valid["success_rate_inputs"] == 2
    assert [(r["validity"], r["success_rate_n"]) for r in summary] == [("valid", 6), ("invalid", 6)]


def test_infrastructure_failures_change_only_counts_tokens_and_cost(release_dir):
    _, before, _ = compute(twelve_records(), release_dir, PRICES)
    _, after, _ = compute(twelve_records() + infra_records(), release_dir, PRICES)
    old, new = metric(before, "invalid"), metric(after, "invalid")
    assert metric(before, "valid") == metric(after, "valid")
    for name in ("success_rate", "hallucination_rate", "mismatch_detection_rate", "malformed_output_rate",
                 "success_rate_n", "consistency", "latency_per_attempt_s"):
        assert new[name] == old[name]
    assert (old["infrastructure_failure_count"], new["infrastructure_failure_count"]) == (0, 2)
    assert new["input_tokens_per_attempt"] == pytest.approx((60 + 14) / 8)
    assert new["output_tokens_per_attempt"] == pytest.approx((30 + 6) / 8)
    assert new["cost_per_success"] == pytest.approx((0.12 + 2 * (7 * 1000 + 3 * 2000) / 1e6) / 2)


def test_no_successes_gives_no_cost_per_success(release_dir):
    records = [raw("2x2-d1-001", 1, answer(["U"]), "failure")]
    _, metrics, _ = compute(records, release_dir, PRICES)
    assert metrics[0]["cost_per_success"] == "n/a"


def test_changed_stored_outcome_shows_both_and_metrics_use_current(release_dir):
    records = twelve_records()
    records[1]["outcome"] = "failure"  # stored says failure, re-validation says success
    attempts, metrics, _ = compute(records, release_dir, PRICES)
    changed = [r for r in attempts if r["stored_outcome"] != r["outcome"]]
    assert [(r["stored_outcome"], r["outcome"]) for r in changed] == [("failure", "success")]
    assert metric(metrics, "valid")["success_rate"] == 0.5


def test_rows_sorted_by_setup_then_model_order(release_dir):
    prices = {"A": PRICES["M"], "B": PRICES["M"]}
    records = []
    for model in ("A", "B"):
        for setup in ("prescriptive", "no_model"):
            records.append(raw("2x2-d1-001", 1, answer(["R"]), "success", setup=setup, model=model))
    _, metrics, _ = compute(records, release_dir, prices, ["B", "A"])
    assert [(r["setup"], r["model"]) for r in metrics] == [
        ("no_model", "B"), ("no_model", "A"), ("prescriptive", "B"), ("prescriptive", "A")]


# ---- mismatch detection ----


def _row(input_id, validity, mismatch, outcome="failure", model="m", setup="no_model", puzzle="2x2"):
    return {"model": model, "puzzle": puzzle, "validity": validity, "setup": setup,
            "input_id": input_id, "outcome": outcome, "mismatch": mismatch, "decision": False,
            "parsed_moves": ["R"]}


def test_balanced_accuracy():
    rows = ([_row("v1", "valid", mismatch=True)] + [_row(f"v{i}", "valid", mismatch=False) for i in range(2, 5)]
            + [_row(f"x{i}", "invalid", mismatch=True) for i in range(1, 4)] + [_row("x4", "invalid", mismatch=False)])
    [row] = detection_rows(rows, ["m"])
    assert row["detection_rate"] == 0.75 and row["false_mismatch_rate"] == 0.25
    assert row["balanced_accuracy"] == 0.75
    assert (row["detection_rate_n"], row["false_mismatch_rate_n"]) == (4, 4)
    assert (row["detection_rate_inputs"], row["false_mismatch_rate_inputs"]) == (4, 4)
    assert row["detection_rate_low"] <= 0.75 <= row["detection_rate_high"]
    assert row["false_mismatch_rate_low"] <= 0.25 <= row["false_mismatch_rate_high"]


def test_always_mismatch_scores_half():
    rows = [_row("v1", "valid", mismatch=True), _row("x1", "invalid", mismatch=True)]
    assert detection_rows(rows, ["m"])[0]["balanced_accuracy"] == 0.5


def test_no_invalid_inputs_gives_na():
    assert detection_rows([_row("v1", "valid", mismatch=False)], ["m"])[0]["balanced_accuracy"] == "n/a"


def test_detection_leaves_out_infrastructure_failures_and_sorts():
    rows = [_row("v1", "valid", False, outcome="infrastructure_failure"),
            _row("v2", "valid", False, setup="prescriptive"), _row("x1", "invalid", True, setup="prescriptive"),
            _row("v2", "valid", False, setup="no_model"), _row("x1", "invalid", True, setup="no_model"),
            _row("v2", "valid", False, model="a"), _row("x1", "invalid", True, model="a")]
    result = detection_rows(rows, ["m", "a"])
    assert [(r["model"], r["setup"]) for r in result] == [
        ("m", "no_model"), ("m", "prescriptive"), ("a", "no_model")]
    assert result[0]["false_mismatch_rate_n"] == 1


# ---- paired setup test ----


def arow(input_id, setup, outcome, model="M", puzzle="2x2", validity="valid", mismatch=False, moves=("R",)):
    return {"model": model, "puzzle": puzzle, "validity": validity, "setup": setup,
            "input_id": input_id, "outcome": outcome, "mismatch": mismatch, "decision": False,
            "parsed_moves": list(moves)}


def pair_row(rows, metric_name="success_rate", pair=("no_model", "descriptive"), **where):
    (found,) = [r for r in paired_tests(rows) if r["metric"] == metric_name
                and (r["setup_a"], r["setup_b"]) == pair
                and all(r[k] == v for k, v in where.items())]
    return found


def test_sign_test_exact_values():
    assert sign_test(8, 2) == pytest.approx(0.109375)
    assert sign_test(2, 8) == pytest.approx(0.109375)
    assert sign_test(0, 0) == 1.0
    assert sign_test(10, 0) == pytest.approx(0.001953125)
    assert sign_test(5, 5) == 1.0


def test_paired_csv_keeps_small_p_values():
    attempts = [arow(f"i{n}", s, o) for n in range(20)
                for s, o in (("no_model", "failure"), ("descriptive", "success"))]
    rows = paired_tests(attempts)
    row = pair_row(attempts)
    assert row["p_value"] == pytest.approx(1.9073486e-06)
    text = evaluate_module.csv_text(rows, exact=("p_value", "p_holm"))
    line = dict(zip(text.splitlines()[0].split(","), text.splitlines()[1].split(",")))
    assert float(line["p_value"]) == pytest.approx(1.9073486e-06, rel=1e-4)
    assert line["mean_difference"] == "1.0000"


def test_holm_adjusts_in_input_order():
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([]) == []


def test_paired_counts_difference_and_holm():
    rows = []
    for n in range(1, 9):  # 8 inputs: no_model fails, descriptive succeeds
        rows += [arow(f"i{n}", "no_model", "failure"), arow(f"i{n}", "descriptive", "success"),
                 arow(f"i{n}", "prescriptive", "failure")]
    for n in (9, 10):  # 2 inputs the other way round
        rows += [arow(f"i{n}", "no_model", "success"), arow(f"i{n}", "descriptive", "failure"),
                 arow(f"i{n}", "prescriptive", "failure")]
    row = pair_row(rows)
    assert (row["inputs_paired"], row["a_higher"], row["b_higher"]) == (10, 2, 8)
    assert row["mean_difference"] == pytest.approx(0.6)
    assert row["p_value"] == pytest.approx(0.109375)
    other = pair_row(rows, pair=("no_model", "prescriptive"))
    assert (other["inputs_paired"], other["a_higher"], other["b_higher"]) == (10, 2, 0)
    assert other["p_value"] == pytest.approx(0.5)
    third = pair_row(rows, pair=("descriptive", "prescriptive"))
    assert third["p_value"] == pytest.approx(0.0078125)
    # family p-values (0.109375, 0.5, 0.0078125): Holm gives 0.21875, 0.5, 0.0234375
    assert row["p_holm"] == pytest.approx(0.21875) and other["p_holm"] == pytest.approx(0.5)
    assert third["p_holm"] == pytest.approx(0.0234375) and third["significant"] is True
    assert row["significant"] is False


def test_paired_significant_when_holm_below_threshold():
    rows = []
    for n in range(10):
        rows += [arow(f"i{n}", "no_model", "failure"), arow(f"i{n}", "descriptive", "success"),
                 arow(f"i{n}", "prescriptive", "success")]
    row = pair_row(rows)
    assert row["p_value"] == pytest.approx(0.001953125)
    assert row["p_holm"] == pytest.approx(0.005859375) and row["significant"] is True
    assert pair_row(rows, pair=("descriptive", "prescriptive"))["p_value"] == 1.0


def test_input_with_one_setup_or_only_infrastructure_failures_is_not_paired():
    rows = [arow("i1", "no_model", "success"), arow("i1", "descriptive", "failure"),
            arow("i2", "no_model", "success"),  # only one setup
            arow("i3", "no_model", "success"), arow("i3", "descriptive", "infrastructure_failure")]
    row = pair_row(rows)
    assert (row["inputs_paired"], row["a_higher"], row["b_higher"]) == (1, 1, 0)
    empty = pair_row(rows, pair=("no_model", "prescriptive"))
    assert empty["inputs_paired"] == 0
    assert [empty[k] for k in ("mean_difference", "p_value", "p_holm", "significant")] == ["n/a"] * 4


def test_pairs_without_inputs_leave_the_holm_family():
    rows = [arow("i1", "no_model", "success"), arow("i1", "descriptive", "failure")]
    row = pair_row(rows)
    assert row["p_value"] == 1.0 and row["p_holm"] == 1.0  # family of one


def test_two_attempts_on_one_input_are_one_paired_input():
    rows = [arow("i1", "no_model", "success"), arow("i1", "no_model", "failure"),
            arow("i1", "descriptive", "success"), arow("i1", "descriptive", "success")]
    row = pair_row(rows)
    assert (row["inputs_paired"], row["a_higher"], row["b_higher"]) == (1, 0, 1)
    assert row["mean_difference"] == pytest.approx(0.5)


def test_hallucination_rate_counts_only_attempts_that_gave_moves():
    rows = [arow("a", "no_model", "hallucination"), arow("a", "no_model", "success"),
            arow("b", "no_model", "failure"),
            arow("b", "no_model", "success", mismatch=True, moves=()),
            arow("c", "no_model", "abstention", moves=()),
            arow("c", "no_model", "truncated", moves=()),
            arow("d", "no_model", "malformed_output", moves=())]
    out = rates(rows, "valid", "k")
    assert out["hallucination_rate"] == pytest.approx(1 / 3)
    assert (out["hallucination_rate_n"], out["hallucination_rate_inputs"]) == (3, 2)
    assert out["success_rate_n"] == 7


def test_hallucination_rate_is_na_when_no_attempt_gave_moves():
    rows = [arow("a", "no_model", "abstention", moves=()), arow("b", "no_model", "failure", mismatch=True, moves=())]
    out = rates(rows, "valid", "k")
    assert out["hallucination_rate"] == "n/a" and out["hallucination_rate_n"] == 0


def test_hallucination_pair_needs_a_move_giving_attempt_under_each_setup():
    rows = [arow("i1", "no_model", "abstention", moves=()), arow("i1", "descriptive", "hallucination"),
            arow("i2", "no_model", "success"), arow("i2", "descriptive", "hallucination")]
    row = pair_row(rows, "hallucination_rate")
    assert row["inputs_paired"] == 1 and row["b_higher"] == 1
    assert pair_row(rows, "success_rate")["inputs_paired"] == 2


def test_valid_inputs_get_no_mismatch_detection_rows():
    rows = [arow("i1", "no_model", "success", validity="valid"),
            arow("i1", "descriptive", "success", validity="valid"),
            arow("j1", "no_model", "success", validity="invalid", mismatch=True),
            arow("j1", "descriptive", "failure", validity="invalid")]
    result = paired_tests(rows)
    assert {(r["validity"], r["metric"]) for r in result} == {
        ("valid", "success_rate"), ("valid", "hallucination_rate"),
        ("invalid", "success_rate"), ("invalid", "hallucination_rate"),
        ("invalid", "mismatch_detection_rate")}
    row = pair_row(rows, "mismatch_detection_rate", validity="invalid")
    assert (row["a_higher"], row["b_higher"]) == (1, 0)


def test_paired_rows_sorted_and_pooled_over_depths():
    rows = []
    for model in ("B", "A"):
        for puzzle in ("3x3", "2x2"):
            rows += [arow("i1", "no_model", "success", model=model, puzzle=puzzle),
                     arow("i1", "descriptive", "success", model=model, puzzle=puzzle)]
    result = paired_tests(rows, ["B", "A"])
    keys = [(r["model"], r["puzzle"], r["metric"], r["setup_a"], r["setup_b"]) for r in result]
    assert [k[:2] for k in keys[::6]] == [("B", "2x2"), ("B", "3x3"), ("A", "2x2"), ("A", "3x3")]
    assert [(r["metric"], r["setup_a"], r["setup_b"]) for r in result[:6]] == [
        (m, a, b) for m in ("success_rate", "hallucination_rate")
        for a, b in (("no_model", "descriptive"), ("no_model", "prescriptive"), ("descriptive", "prescriptive"))]
    assert [r["model"] for r in paired_tests(rows)[::6]] == ["A", "A", "B", "B"]


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
    assert not (repo / "results/exp/1.0.0.paired.csv").exists()
    assert not (repo / "results/exp/1.0.0.detection.csv").exists()


def test_prices_copied_once_and_outputs_stable(repo, monkeypatch):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    raw_before = {p.name: p.read_bytes() for p in (repo / "results/exp/raw").iterdir()}
    assert go() == 0
    first = {n: (repo / "results/exp" / n).read_bytes() for n in ("1.0.0.md", "1.0.0.metrics.csv", "1.0.0.paired.csv", "1.0.0.detection.csv", "1.0.0.corruption.csv", "prices.toml")}
    assert go() == 0
    header = (repo / "results/exp/1.0.0.detection.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(DETECTION_COLUMNS)
    assert first == {n: (repo / "results/exp" / n).read_bytes() for n in first}
    assert raw_before == {p.name: p.read_bytes() for p in (repo / "results/exp/raw").iterdir()}
    (repo / "config/prices.toml").write_text(PRICE_FILE.format(price=9.0), encoding="utf-8")
    assert go() == 0
    assert first == {n: (repo / "results/exp" / n).read_bytes() for n in first}
    (repo / "results/exp/prices.toml").unlink()
    assert go() == 0
    assert (repo / "results/exp/1.0.0.md").read_bytes() != first["1.0.0.md"]
    assert "9.0" in (repo / "results/exp/prices.toml").read_text(encoding="utf-8")


def test_paired_csv_written_and_stable(repo, monkeypatch):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    assert go() == 0
    path = repo / "results/exp/1.0.0.paired.csv"
    first = path.read_bytes()
    header = first.decode("utf-8").splitlines()[0]
    assert header == ("model,puzzle,validity,metric,setup_a,setup_b,inputs_paired,a_higher,b_higher,"
                      "mean_difference,p_value,p_holm,significant")
    assert go() == 0
    assert path.read_bytes() == first


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
    assert not (repo / "results/exp/1.0.0.paired.csv").exists()


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
    for name in ("prices.toml", "1.0.0.md", "1.0.0.metrics.csv", "1.0.0.paired.csv"):
        assert not (repo / "results/exp" / name).exists()


def test_decision_model_records_are_parsed_as_arrays(release_dir):
    legal = get_engine("2x2").legal_moves()
    state, scramble = get_engine("2x2").scramble(1, 1)
    inverse = {"": "'", "'": "", "2": "2"}
    solve = scramble[0][0] + inverse[scramble[0][1:]]
    calls = [{"answers": {"next_move": {"choice": f"move_{legal.index(solve) + 1}"}}},
             {"answers": {"next_move": {"choice": "done"}}}]
    record = raw("2x2-d1-001", 1, json.dumps(calls), "success", model="M")
    attempts, _, _ = compute([record], release_dir, PRICES, decision_models={"M"})
    assert attempts[0]["outcome"] == "success"
    attempts, _, _ = compute([record], release_dir, PRICES)
    assert attempts[0]["outcome"] == "abstention"  # read as lines, the JSON is prose


def test_scoring_uses_the_records_decision_flag_over_the_config_rule(release_dir):
    legal = get_engine("2x2").legal_moves()
    state, scramble = get_engine("2x2").scramble(1, 1)
    inverse = {"": "'", "'": "", "2": "2"}
    solve = scramble[0][0] + inverse[scramble[0][1:]]
    calls = [{"answers": {"next_move": {"choice": f"move_{legal.index(solve) + 1}"}}},
             {"answers": {"next_move": {"choice": "done"}}}]
    flagged = raw("2x2-d1-001", 1, json.dumps(calls), "success", model="M", decision=True)
    attempts, _, _ = compute([flagged], release_dir, PRICES, decision_models=set())
    assert attempts[0]["outcome"] == "success"
    unflagged = raw("2x2-d1-001", 1, json.dumps(calls), "success", model="M", decision=False)
    attempts, _, _ = compute([unflagged], release_dir, PRICES, decision_models={"M"})
    assert attempts[0]["outcome"] == "abstention"  # read as lines, the JSON is prose


def test_new_outcome_rates(release_dir):
    v1 = "2x2-d1-001"
    records = [
        raw(v1, 1, "R", "truncated", stop_reason="truncated"),
        raw(v1, 2, "I cannot solve this", "abstention"),
        raw(v1, 3, "R U", "format_error"),
        raw(v1, 4, answer(["R"]), "success"),
    ]
    attempts, metrics, _ = compute(records, release_dir, PRICES)
    assert [a["outcome"] for a in attempts] == ["truncated", "abstention", "format_error", "success"]
    row = metrics[0]
    assert row["truncated_rate"] == 0.25 and row["abstention_rate"] == 0.25
    assert row["format_error_rate"] == 0.25 and row["malformed_output_rate"] == 0.0
    assert row["truncated_rate_n"] == 4


def test_decision_model_hallucination_rate_is_na(release_dir):
    legal = get_engine("2x2").legal_moves()
    _, scramble = get_engine("2x2").scramble(1, 1)
    inverse = {"": "'", "'": "", "2": "2"}
    solve = scramble[0][0] + inverse[scramble[0][1:]]
    good = [{"answers": {"next_move": {"choice": f"move_{legal.index(solve) + 1}"}}},
            {"answers": {"next_move": {"choice": "done"}}}]
    bad = [{"answers": {"next_move": {"choice": "done"}}}]
    records = [
        raw("2x2-d1-001", n, json.dumps(calls), "x", model="jev", decision=True, setup=setup)
        for setup in ("no_model", "descriptive") for n, calls in ((1, good), (2, bad))]
    prices = {"jev": PRICES["M"]}
    attempts, metrics, summary = compute(records, release_dir, prices)
    assert {a["outcome"] for a in attempts} == {"success", "failure"}
    assert all(a["decision"] for a in attempts)
    assert metrics[0]["hallucination_rate"] == "n/a" and metrics[0]["hallucination_rate_n"] == 0
    assert summary[0]["hallucination_rate"] == "n/a"
    assert not any(r["metric"] == "hallucination_rate" and r["model"] == "jev"
                   for r in paired_tests(attempts))
    assert any(r["metric"] == "success_rate" for r in paired_tests(attempts))


def test_old_records_rescore_without_error(release_dir):
    legal = get_engine("2x2").legal_moves()
    _, scramble = get_engine("2x2").scramble(1, 1)
    inverse = {"": "'", "'": "", "2": "2"}
    solve = scramble[0][0] + inverse[scramble[0][1:]]
    calls = [{"answers": {"next_move": {"choice": f"move_{legal.index(solve) + 1}"}}},
             {"answers": {"next_move": {"choice": "done"}}}]
    old = raw("2x2-d1-001", 1, "R", "malformed_output", stop_reason="truncated", hallucination=False)
    decision = raw("2x2-d1-001", 2, json.dumps(calls), "success", model="M", decision=True,
                   hallucination=False)
    attempts, _, _ = compute([old, decision], release_dir, PRICES)
    assert [r["outcome"] for r in attempts] == ["truncated", "success"]


def test_corruption_type_reads_old_descriptions():
    assert corruption_type("twisted corner UFL clockwise") == "twisted corner"
    assert corruption_type("flipped edge UF") == "flipped edge"


def test_corruption_rows_split_by_type():
    def row(input_id, corruption, mismatch, **over):
        r = _row(input_id, "invalid", mismatch, **over)
        r["corruption"] = corruption
        return r
    rows = [row("x1", "swapped edges UF UR", True), row("x1", "swapped edges UF UR", False),
            row("x2", "twisted corner UFL clockwise", True),
            row("x3", "twisted corner UFR anticlockwise", False),
            row("x4", "twisted corner UFR clockwise", True, outcome="infrastructure_failure"),
            _row("v1", "valid", True)]
    result = corruption_rows(rows, ["m"])
    assert [(r["corruption_type"], r["detection_rate"], r["detection_rate_n"], r["detection_rate_inputs"])
            for r in result] == [("twisted corner", 0.5, 2, 2), ("swapped edges", 0.5, 2, 1)]
    assert result == corruption_rows(rows, ["m"])


def test_all_infrastructure_failures_evaluate_with_header_only_csvs(repo, monkeypatch):
    release_ok(repo, "major")
    prepare(repo, monkeypatch)
    for path in (repo / "results/exp/raw").iterdir():
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            record.update(outcome="infrastructure_failure", stop_reason="infrastructure_failure",
                          raw_response="", parsed_moves=[], hallucination=False, mismatch=False)
            lines.append(json.dumps(record))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert go() == 0
    for name, header in (("detection", ",".join(DETECTION_COLUMNS)),
                         ("corruption", ",".join(CORRUPTION_COLUMNS))):
        assert (repo / f"results/exp/1.0.0.{name}.csv").read_text(encoding="utf-8") == header + "\n"
