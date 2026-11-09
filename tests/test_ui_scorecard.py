# Spec: docs/specs/ui.md
"""Tests for `GET /api/scorecard/<id>`: the point values equal those of `src.evaluate.metrics` on the same records,
elapsed and time left with and without a running job, and n/a values as null. Uses the temporary git repo of
tests/test_ui.py."""

import json
from datetime import datetime, timezone

import pytest

from src.evaluate.metrics import (NA, attempt_cost, corruption_type, detection_rows, make_attempt_rows,
                                  mean_of_two, rates)
from test_ui import FORM, call, put_branch, server, ui_repo  # noqa: F401  (fixtures)
from test_ui_estimate import config_of, inputs_of, record
from test_release import repo  # noqa: F401  (fixture)
from ui import expdata
from ui.expdata import cell
from ui.scorecard import model_values, scorecard
from ui.tomlw import dumps_config

PRICE = {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0}
RESPONSES = ["R", "R2'", "MISMATCH twisted corner", "sorry, I cannot", "R", "MISMATCH twisted centre", "MISMATCH flipped edge"]


def inverse(moves):
    flip = lambda m: m if m.endswith("2") else (m[:-1] if m.endswith("'") else m + "'")
    return [flip(m) for m in reversed(moves)]


def good_answer(row, setup, n):
    """Solves valid inputs and diagnoses invalid ones under two setups, and answers badly under the third."""
    if setup == "prescriptive":
        return RESPONSES[n % len(RESPONSES)]
    if row["validity"] == "invalid":
        return "MISMATCH " + (corruption_type(row["corruption"]) if setup == "no_model" else "flipped edge")
    return "\n".join(inverse(row["scramble"]))


def put_records(server, latencies=None, stamps=None, answer=None):
    """Nine records of example-model, one per input and setup, with varied answers, on a pushed branch."""
    inputs = {r["input_id"]: r for r in inputs_of(server)}
    records = []
    for n, (input_id, setup) in enumerate((i, s) for i in inputs for s in ("no_model", "descriptive", "prescriptive")):
        r = record("example-model", input_id, setup, latency=(latencies or [2.0] * 9)[n], tokens=1000 * (n + 1))
        r["raw_response"] = answer(inputs[input_id], setup, n) if answer else RESPONSES[n % len(RESPONSES)]
        r["created_at"] = (stamps or [f"2026-11-08T00:00:{n:02d}Z"] * 9)[n]
        records.append(r)
    body = "\n".join(json.dumps(r) for r in records) + "\n"
    put_branch(server.root, "t1", {"results/t1/experiment.toml": dumps_config(config_of(FORM, server)),
                                  "results/t1/raw/example-model.jsonl": body}, where="both")
    return records


def oracle(server, records):
    inputs = inputs_of(server)
    reasons = bool(json.loads((server.root / "releases" / "1.0.0" / "manifest.json").read_text()).get("mismatch_reasons"))
    rows = make_attempt_rows(records, inputs, {"example-model": PRICE}, frozenset(), reasons)
    done = [r for r in rows if r["outcome"] != "infrastructure_failure"]
    return rows, expdata.all_scope_rates(done, "oracle")


def test_values_equal_metrics(server):
    records = put_records(server, answer=good_answer)
    status, body = call(server, "GET", "/api/scorecard/t1")
    assert status == 200, body
    rows, want = oracle(server, records)
    m = body["models"][0]
    assert m["name"] == "example-model" and m["running"] is False and body["live"] is False
    assert m["balanced_precision"] == want["precision"] > 0
    assert m["coverage"] == want["coverage"]
    assert m["hallucination_rate"] == want["hallucination_rate"]
    done = [r for r in rows if r["outcome"] != "infrastructure_failure"]
    side = lambda label: [r for r in done if r["validity"] == label]
    assert m["reason_hallucination_rate"] == cell(want["reason_hallucination_rate"])
    assert m["critical_thinking"] == cell(mean_of_two(rates(side("invalid"), "invalid", "k")["diagnosis_rate"],
                                                      rates(side("valid"), "valid", "k")["false_mismatch_rate"], True))
    cost = sum(attempt_cost(r, PRICE) for r in records)
    assert m["cost_usd"] == pytest.approx(cost)
    assert m["cost_efficiency"] == pytest.approx(cost / len(records) / (want["precision"] * want["coverage"]))
    assert (m["done"], m["planned"]) == (9, 9)
    assert body["total"]["done"] == 9 and body["total"]["cost_usd"] == pytest.approx(cost)
    assert body["total"]["per_model_usd"] == 5.0 and body["total"]["per_experiment_usd"] == 10.0


def test_one_puzzle_and_setup_equals_detection_rows(server):
    records = put_records(server, answer=good_answer)
    rows, _ = oracle(server, records)
    for setup in ("no_model", "descriptive"):
        group = [r for r in rows if r["setup"] == setup]
        got = model_values(group, PRICE)
        (want,) = [d for d in detection_rows(rows) if d["puzzle"] == "2x2" and d["setup"] == setup]
        assert got["balanced_precision"] == want["balanced_precision"] > 0
        assert got["critical_thinking"] == want["critical_thinking"]
        assert got["coverage"] == want["coverage"]
        assert got["cost_efficiency"] == pytest.approx(want["cost_efficiency"])
    assert model_values([r for r in rows if r["setup"] == "no_model"], PRICE)["critical_thinking"] == 1.0


def test_reason_values_equal_metrics():
    def row(validity, flagged, reason, decoy, corruption, outcome="failure", moves=()):
        return {"validity": validity, "outcome": outcome, "mismatch": flagged, "mismatch_reason": reason,
                "decoy": decoy, "corruption": corruption, "reasons": True, "decision": False, "impossible_move": False,
                "parsed_moves": list(moves), "input_id": f"{validity}{reason}{flagged}",
                "answer_class": None, "input_tokens": 10, "output_tokens": 10, "retry_input_tokens": 0,
                "retry_output_tokens": 0}
    rows = [row("invalid", True, "twisted corner", False, "twisted corner at UFR"),
            row("invalid", True, "twisted centre", True, "twisted corner at UFR"),
            row("invalid", True, "flipped edge", False, "twisted corner at UFR"),
            row("valid", True, "twisted corner", False, None),
            row("valid", False, None, False, None, "success", ["R"]),
            row("valid", False, None, False, None, "success", ["U"])]
    for r in rows:
        from src.evaluate.metrics import answer_class
        r["answer_class"] = answer_class(r)
    got = model_values(rows, PRICE)
    invalid, valid = rates(rows[:3], "invalid", "k"), rates(rows[3:], "valid", "k")
    assert got["critical_thinking"] == mean_of_two(invalid["diagnosis_rate"], valid["false_mismatch_rate"], True)
    assert got["reason_hallucination_rate"] == rates(rows, "valid", "k")["reason_hallucination_rate"] == 0.25
    assert got["balanced_precision"] == mean_of_two(valid["precision"], invalid["precision"])


def test_elapsed_and_time_left(server):
    stamps = [f"2026-11-08T00:{n:02d}:00Z" for n in range(9)]
    put_records(server, latencies=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0], stamps=stamps)
    bundles = server.app.bundles
    now = datetime(2026, 11, 8, 0, 10, 0, tzinfo=timezone.utc)
    no_history = lambda remote: {}
    over = scorecard(bundles, "t1", set(), {"run:example-model": "done"}, {}, no_history, now)
    assert over["live"] is False and over["total"]["elapsed_s"] == 480.0  # first to last record
    assert over["total"]["time_left_s"] is None
    # 9 planned, 9 done: nothing left even while running
    live = scorecard(bundles, "t1", set(), {"run:example-model": "running"}, {"example-model": 3}, no_history, now)
    assert live["live"] is True and live["total"]["elapsed_s"] == 600.0  # first record to now
    assert live["models"][0]["running"] is True and live["total"]["time_left_s"] == 0.0


def test_time_left_uses_own_median_then_history(server):
    ids = [r["input_id"] for r in inputs_of(server)]
    put_records(server, latencies=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
    bundles = server.app.bundles
    now = datetime(2026, 11, 8, 0, 10, 0, tzinfo=timezone.utc)
    # More attempts planned than done: attempts 2 per input and setup doubles the plan to 18, so 9 are left.
    form = {**FORM, "attempts": 2}
    put_branch(server.root, "t1", {"results/t1/experiment.toml": dumps_config(config_of(form, server))}, where="both")
    history = lambda remote: {"example-model": (100.0, 50)}
    state, par = {"run:example-model": "running"}, {"example-model": 3}
    got = scorecard(bundles, "t1", set(), state, par, history, now)
    assert got["total"]["time_left_s"] == pytest.approx(9 * 5.0 / 3)  # 9 left x own median 5.0 / parallel 3
    assert len(ids) == 3 and got["models"][0]["planned"] == 18


def test_time_left_falls_back_to_history_and_null(server):
    put_records(server, latencies=[1.0] * 9)
    form = {**FORM, "attempts": 2}
    put_branch(server.root, "t1", {"results/t1/experiment.toml": dumps_config(config_of(form, server))}, where="both")
    now = datetime(2026, 11, 8, 0, 10, 0, tzinfo=timezone.utc)
    state = {"run:example-model": "running"}
    # Fewer than 5 own records: the pushed history is used. Simulate by dropping the own records' latency.
    got = scorecard(server.app.bundles, "t1", set(), state, {}, lambda remote: {}, now)
    assert got["total"]["time_left_s"] == pytest.approx(9 * 1.0)  # own median 1.0, parallel 1
    only = {"results/t1/raw/example-model.jsonl": "\n".join(open_lines(server)[:2]) + "\n"}
    put_branch(server.root, "t1", only, where="both")
    assert scorecard(server.app.bundles, "t1", set(), state, {}, lambda remote: {}, now)["total"]["time_left_s"] is None
    got = scorecard(server.app.bundles, "t1", set(), state, {"example-model": 2},
                    lambda remote: {"example-model": (4.0, 99)}, now)
    assert got["total"]["time_left_s"] == pytest.approx(16 * 4.0 / 2)


def open_lines(server):
    from ui.gitdata import GitData
    return GitData(server.root).show("origin/results/t1", "results/t1/raw/example-model.jsonl").splitlines()


def test_unpriced_model_has_null_cost():
    values = model_values([], None)
    assert values["cost_usd"] is None and values["cost_efficiency"] is None
    assert values["balanced_precision"] is None and values["coverage"] is None
    assert NA not in values.values()


def test_unknown_experiment_is_404(server):
    assert call(server, "GET", "/api/scorecard/nope")[0] == 404


def test_batch_rows_are_priced_at_the_batch_tier_and_need_batch_prices():
    from ui.scorecard import priced
    rows = [{"batch": True, "input_tokens": 1_000_000, "output_tokens": 0, "retry_input_tokens": 0,
             "retry_output_tokens": 0}]
    both = dict(PRICE, batch_price_input_per_mtok=0.5, batch_price_output_per_mtok=1.0)
    assert priced({"m": PRICE}, "m", rows) is None  # batch rows, no batch prices: cost n/a, no KeyError
    assert priced({"m": PRICE}, "m", [{"batch": False}]) == PRICE
    assert attempt_cost(rows[0], priced({"m": both}, "m", rows)) == pytest.approx(0.5)
