# Spec: docs/specs/evaluate.md
"""Metric maths for evaluate: re-validates raw records against the release inputs and groups
the attempts. Reads the release's inputs.jsonl and writes nothing. It is part of the assessment.
"""

import json
import math
from collections import Counter, defaultdict
from operator import itemgetter
from pathlib import Path

from src.puzzles.registry import ENGINES, get_engine
from src.run.prompts import SETUPS
from src.validator import validate

NA = "n/a"
Z = 1.96  # 95% confidence
KEY = ("puzzle", "setup", "model", "scramble_depth", "validity")


class EvalError(Exception):
    """A checked error. The message names the file or field at fault."""


def wilson(hits: int, n: int) -> tuple:
    """Return (rate, low, high) with a 95% Wilson score interval, or n/a when n is 0."""
    if n == 0:
        return NA, NA, NA
    p = hits / n
    spread = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    centre = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    return p, max(0.0, centre - spread), min(1.0, centre + spread)


def mean(values: list) -> object:
    return sum(values) / len(values) if values else NA


def rate_columns(row: dict, name: str, hits: int, n: int) -> None:
    row[name], row[name + "_low"], row[name + "_high"] = wilson(hits, n)
    row[name + "_n"] = n


def count_outcome(rows: list[dict], outcome: str) -> int:
    return sum(1 for r in rows if r["outcome"] == outcome)


def rates(rows: list[dict], validity: str) -> dict:
    """Rates over the attempts that are not infrastructure failures (`rows` holds only those)."""
    n = len(rows)
    flagged = sum(r["mismatch"] for r in rows)
    out: dict = {}
    rate_columns(out, "success_rate", count_outcome(rows, "success"), n)
    rate_columns(out, "hallucination_rate", count_outcome(rows, "hallucination"), n)
    if validity == "invalid":
        rate_columns(out, "mismatch_detection_rate", flagged, n)
        rate_columns(out, "false_mismatch_rate", 0, 0)
    else:
        rate_columns(out, "mismatch_detection_rate", 0, 0)
        rate_columns(out, "false_mismatch_rate", flagged, n)
    rate_columns(out, "malformed_output_rate", count_outcome(rows, "malformed_output"), n)
    return out


def consistency(rows: list[dict]) -> object:
    """Mean share of attempts that agree with the most common outcome, per input with 2 or more."""
    by_input = defaultdict(list)
    for r in rows:
        by_input[r["input_id"]].append(r["outcome"])
    shares = []
    for outcomes in by_input.values():
        if len(outcomes) >= 2:
            most_common = Counter(outcomes).most_common(1)[0][1]
            shares.append(most_common / len(outcomes))
    return mean(shares)


def group_metrics(rows: list[dict], validity: str, full: bool) -> dict:
    """Metrics for one group of attempt rows. `full` adds the columns the summary leaves out."""
    done = [r for r in rows if r["outcome"] != "infrastructure_failure"]
    successes = count_outcome(rows, "success")
    out = {"attempts": len(rows), "infrastructure_failure_count": len(rows) - len(done)}
    out.update(rates(done, validity))
    out["cost_per_success"] = sum(r["cost"] for r in rows) / successes if successes else NA
    if full:
        out["efficiency"] = efficiency(done, validity)
        out["consistency"] = consistency(done)
        latencies = [r["latency_s"] for r in done if r["latency_s"] is not None]
        out["latency_per_attempt_s"] = mean(latencies)
        in_tokens = [r["input_tokens"] + r["retry_input_tokens"] for r in rows]
        out_tokens = [r["output_tokens"] + r["retry_output_tokens"] for r in rows]
        out["input_tokens_per_attempt"] = mean(in_tokens)
        out["output_tokens_per_attempt"] = mean(out_tokens)
    return out


def efficiency(done: list[dict], validity: str) -> object:
    """Mean of move count over reference length, for successes on valid inputs."""
    ratios = []
    for r in done:
        if r["outcome"] == "success" and validity == "valid" and r["reference_length"]:
            ratios.append(r["move_count"] / r["reference_length"])
    return mean(ratios)


def reference_length(cache: dict, row: dict) -> int | None:
    """Reference length of a valid input, or None where the engine has no solver yet."""
    if row["input_id"] not in cache:
        try:
            cache[row["input_id"]] = get_engine(row["puzzle"]).reference_length(row["state"])
        except NotImplementedError:
            cache[row["input_id"]] = None
    return cache[row["input_id"]]


def attempt_cost(raw: dict, price: dict) -> float:
    input_tokens = raw["input_tokens"] + raw["retry_input_tokens"]
    output_tokens = raw["output_tokens"] + raw["retry_output_tokens"]
    return (input_tokens * price["price_input_per_mtok"]
            + output_tokens * price["price_output_per_mtok"]) / 1e6


def make_attempt_row(raw: dict, line: int, source: dict, verdict, cost: float, reference) -> dict:
    return {
        "input_id": raw["input_id"], "input_line": line, "puzzle": source["puzzle"],
        "scramble_depth": source["scramble_depth"], "validity": source["validity"],
        "setup": raw["setup"], "model": raw["model"], "attempt_number": raw["attempt_number"],
        "stored_outcome": raw["outcome"], "outcome": verdict.outcome,
        "parsed_moves": verdict.parsed_moves, "mismatch": verdict.mismatch,
        "move_count": verdict.move_count, "reference_length": reference,
        "input_tokens": raw["input_tokens"], "output_tokens": raw["output_tokens"],
        "retry_input_tokens": raw["retry_input_tokens"],
        "retry_output_tokens": raw["retry_output_tokens"], "latency_s": raw["latency_s"],
        "served_model": raw["served_model"], "created_at": raw["created_at"], "cost": cost,
    }


def make_attempt_rows(raw_records, inputs, prices, cache, decision_models=frozenset()) -> list[dict]:
    by_id = {row["input_id"]: (number, row) for number, row in enumerate(inputs, start=1)}
    rows = []
    for raw in raw_records:
        if raw["input_id"] not in by_id:
            raise EvalError(
                f"raw record {raw['input_id']!r}: field 'input_id' is not in inputs.jsonl")
        if raw["model"] not in prices:
            raise EvalError(f"prices: no prices for model {raw['model']!r}")
        line, source = by_id[raw["input_id"]]
        verdict = validate(source, raw["raw_response"], raw["stop_reason"],
                           decision=raw["model"] in decision_models)
        cost = attempt_cost(raw, prices[raw["model"]])
        reference = None
        if verdict.outcome == "success" and source["validity"] == "valid":
            reference = reference_length(cache, source)
        rows.append(make_attempt_row(raw, line, source, verdict, cost, reference))
    return rows


def model_rank(order: list[str], name: str) -> tuple:
    return (order.index(name) if name in order else len(order), name)


def attempt_sort_key(row: dict, order: list[str]) -> tuple:
    return (row["input_line"], model_rank(order, row["model"]),
            SETUPS.index(row["setup"]), row["attempt_number"])


def metric_sort_key(key: tuple, order: list[str]) -> tuple:
    """Key is (puzzle, setup, model, depth, validity)."""
    puzzle, setup, model, depth, validity = key
    return (list(ENGINES).index(puzzle), SETUPS.index(setup), model_rank(order, model),
            depth, validity != "valid")


def summary_sort_key(key: tuple, order: list[str]) -> tuple:
    """Key is (model, setup, validity)."""
    model, setup, validity = key
    return (SETUPS.index(setup), model_rank(order, model), validity != "valid")


def sorted_keys(groups: dict, sort_key, order: list[str]) -> list[tuple]:
    decorated = [(sort_key(key, order), key) for key in groups]
    decorated.sort(key=itemgetter(0))
    return [key for _, key in decorated]


def compute(raw_records: list[dict], release_dir: Path, prices: dict,
            models: list[str] | None = None, decision_models=frozenset()) -> tuple:
    """Return (attempt_rows, metric_rows, summary_rows). `models` fixes the AI model sort order."""
    lines = (Path(release_dir) / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
    inputs = [json.loads(line) for line in lines]
    rows = make_attempt_rows(raw_records, inputs, prices, {}, decision_models)
    order = models or sorted({r["model"] for r in rows})
    decorated = [(attempt_sort_key(r, order), r) for r in rows]
    decorated.sort(key=itemgetter(0))
    rows = [row for _, row in decorated]

    groups, pooled = defaultdict(list), defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in KEY)].append(r)
        pooled[(r["model"], r["setup"], r["validity"])].append(r)
    metric_rows = []
    for key in sorted_keys(groups, metric_sort_key, order):
        row = dict(zip(KEY, key))
        row.update(group_metrics(groups[key], key[4], True))
        metric_rows.append(row)
    summary_rows = []
    for key in sorted_keys(pooled, summary_sort_key, order):
        row = dict(zip(("model", "setup", "validity"), key))
        row.update(group_metrics(pooled[key], key[2], False))
        summary_rows.append(row)
    return rows, metric_rows, summary_rows
