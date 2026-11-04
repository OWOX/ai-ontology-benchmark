# Spec: docs/specs/ui.md
"""The maths behind `GET /api/benchmarks`: pools attempt rows into one cell per AI model, puzzle,
and metric, ranks the cells, and runs the paired model test between neighbours. For display only,
so it lives outside the assessment. Reads attempt rows, writes nothing.
"""

from collections import defaultdict
from fractions import Fraction

from src.evaluate.metrics import consistency, holm, is_hit, mean, rates, sign_test
from ui.expdata import all_scope_rates
from ui.expdata import cell as na_to_none

RATE_METRICS = ("success_rate", "hallucination_rate", "mismatch_detection_rate", "false_mismatch_rate",
                "malformed_output_rate")
METRICS = (*RATE_METRICS, "efficiency", "consistency", "latency_per_attempt_s", "tokens_per_attempt",
           "cost_per_success")
HIGHER = ("success_rate", "mismatch_detection_rate", "consistency")


def direction(metric: str) -> str:
    return "higher" if metric in HIGHER else "lower"


def pooled_rates(done: list[dict], scope: str) -> dict:
    """Rates over the attempts that are not infrastructure failures, as `all_scope_rates` pools them."""
    return all_scope_rates(done) if scope == "all" else rates(done, scope)


def rate_cell(stats: dict, metric: str) -> dict:
    n = stats[metric + "_n"]
    return {"value": na_to_none(stats[metric]), "low": na_to_none(stats[metric + "_low"]),
            "high": na_to_none(stats[metric + "_high"]), "n": n}


def consistency_of(done: list[dict]) -> object:
    """Per input, AI model, and setup: rows are keyed so that input sets and setups never mix."""
    keyed = [{"input_id": (r["input_set_id"], r["input_id"], r["setup"]), "outcome": r["outcome"]} for r in done]
    return consistency(keyed)


def efficiency_ratios(done: list[dict]) -> list[float]:
    return [r["move_count"] / r["reference_length"] for r in done
            if r["outcome"] == "success" and r["validity"] == "valid" and r["reference_length"]]


def cells(rows: list[dict], scope: str) -> dict[str, dict]:
    """The cell of every metric for one AI model and puzzle. `rows` are its attempt rows, scope applied."""
    done = [r for r in rows if r["outcome"] != "infrastructure_failure"]
    stats = pooled_rates(done, scope)
    out = {m: rate_cell(stats, m) for m in RATE_METRICS}
    ratios = efficiency_ratios(done)
    out["efficiency"] = {"value": na_to_none(mean(ratios)), "n": len(ratios)}
    out["consistency"] = {"value": na_to_none(consistency_of(done)), "n": len(done)}
    latencies = [r["latency_s"] for r in done if r["latency_s"] is not None]
    out["latency_per_attempt_s"] = {"value": na_to_none(mean(latencies)), "n": len(latencies)}
    tokens = [r["input_tokens"] + r["output_tokens"] + r["retry_input_tokens"] + r["retry_output_tokens"]
              for r in rows]
    out["tokens_per_attempt"] = {"value": na_to_none(mean(tokens)), "n": len(rows)}
    successes = sum(r["outcome"] == "success" for r in rows)
    priced = all(r.get("priced", True) for r in rows)  # an unpriced model's cost is 0, never a result
    out["cost_per_success"] = {"value": sum(r["cost"] for r in rows) / successes if successes and priced else None,
                               "n": len(rows)}
    return out


def hit(row: dict, metric: str) -> bool:
    return bool(row["mismatch"]) if metric == "false_mismatch_rate" else is_hit(row, metric)


def shares(rows: list[dict], metric: str) -> dict:
    """Like `src.evaluate.metrics.input_shares`, but per input across setups and keyed by (input set id, input id).
    Mismatch detection counts invalid rows only and false mismatch valid rows only."""
    counts = defaultdict(lambda: [0, 0])
    wanted = {"mismatch_detection_rate": "invalid", "false_mismatch_rate": "valid"}.get(metric)
    for r in rows:
        if r["outcome"] == "infrastructure_failure" or (wanted and r["validity"] != wanted):
            continue
        found = counts[(r["input_set_id"], r["input_id"])]
        found[0] += hit(r, metric)
        found[1] += 1
    return {key: Fraction(h, n) for key, (h, n) in counts.items()}


def paired_model_test(a_rows: list[dict], b_rows: list[dict], metric: str) -> dict:
    """The paired model test of `a` against `b`: inputs paired, and the sign test on those that differ."""
    a, b = shares(a_rows, metric), shares(b_rows, metric)
    paired = sorted(set(a) & set(b))
    a_higher = sum(a[k] > b[k] for k in paired)
    b_higher = sum(a[k] < b[k] for k in paired)
    return {"inputs_paired": len(paired), "p_value": sign_test(a_higher, b_higher) if paired else None,
            "a_higher": a_higher, "b_higher": b_higher}


def agrees(side: str, found: tuple[str, str], metric: str, test: dict) -> bool:
    """True when most paired inputs that differ favour the better model of the pair, in the metric's direction.
    The better model is the named one for `best` and the other one for `worst`. A tie in the counts is False.
    `test` was computed with `test["order"]` as (a, b)."""
    higher = dict(zip(test["order"], (test["a_higher"], test["b_higher"])))
    model, other = found
    better, worse = (higher[model], higher[other]) if direction(metric) == "higher" else (higher[other], higher[model])
    return (better > worse) if side == "best" else (worse > better)


def ranking(cells_by_model: dict[str, dict], metric: str) -> list[str]:
    """The AI models with a value, best first."""
    valued = [(m, c["value"]) for m, c in cells_by_model.items() if c["value"] is not None]
    valued.sort(key=lambda item: item[1], reverse=direction(metric) == "higher")
    return [m for m, _ in valued]


def pick(order: list[str], values: dict[str, float], end: int) -> tuple[str, str] | None:
    """The best (`end` 0) or worst (`end` -1) model and the next one in, or None on a tie or too few."""
    if len(order) < 2:
        return None
    step = 1 if end == 0 else -1
    model, other = order[end], order[end + step]
    return None if values[model] == values[other] else (model, other)


def row_for(puzzle: str, metric: str, cells_by_model: dict[str, dict], by_model: dict[str, list[dict]]) -> dict:
    order = ranking(cells_by_model, metric)
    values = {m: cells_by_model[m]["value"] for m in order}
    picks = {"best": pick(order, values, 0), "worst": pick(order, values, -1)}
    tested = metric in RATE_METRICS
    out = {"puzzle": puzzle, "metric": metric, "direction": direction(metric), "tested": tested,
           "cells": cells_by_model, "best": None, "worst": None}
    if not tested:
        for side, found in picks.items():
            out[side] = {"model": found[0]} if found else None
        return out
    tests: dict[frozenset, dict] = {}
    for found in picks.values():
        if found and frozenset(found) not in tests:
            tests[frozenset(found)] = {**paired_model_test(by_model[found[0]], by_model[found[1]], metric),
                                       "order": found}
    family = [t for t in tests.values() if t["p_value"] is not None]
    for t, adjusted in zip(family, holm([t["p_value"] for t in family])):
        t["p_holm"] = adjusted
    for side, found in picks.items():
        if found:
            test = tests[frozenset(found)]
            out[side] = {"model": found[0], "against": found[1], "inputs_paired": test["inputs_paired"],
                         "p_value": test["p_value"], "p_holm": test.get("p_holm"),
                         "agrees": agrees(side, found, metric, test)}
    return out


def build_rows(attempts: list[dict], models: list[str], puzzles: list[str], scope: str) -> list[dict]:
    """One row per puzzle and metric, for the puzzles with any attempt. `attempts` are already filtered."""
    out = []
    for puzzle in puzzles:
        by_model = {m: [r for r in attempts if r["model"] == m and r["puzzle"] == puzzle
                        and scope in ("all", r["validity"])] for m in models}
        by_model = {m: found for m, found in by_model.items() if found}
        if not by_model:
            continue
        per_model = {m: cells(found, scope) for m, found in by_model.items()}
        for metric in METRICS:
            out.append(row_for(puzzle, metric, {m: per_model[m][metric] for m in per_model}, by_model))
    return out
