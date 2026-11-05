# Spec: docs/specs/ui.md
"""Pools the rows of an experiment's report CSV (`<version>.metrics.csv`) into bundle rows and
summary rows. Each rate is pooled as hits over n, with hits rounded back from the CSV's 4-decimal
rate. The CSV holds no per-input cells, so the intervals are Wilson score intervals over the pooled
attempts, for display only (the UI marks them with `*`). Reads parsed CSV rows and writes nothing.
"""

from collections import defaultdict

from src.evaluate.metrics import NA, summary_sort_key, sorted_keys, wilson

RATES = ("success_rate", "hallucination_rate", "mismatch_detection_rate", "false_mismatch_rate",
         "malformed_output_rate", "truncated_rate", "abstention_rate", "format_error_rate")


def number(text: object) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def hits_and_n(rows: list[dict], rate: str) -> tuple[int, int]:
    hits = total = 0
    for row in rows:
        n, value = number(row.get(rate + "_n")), number(row.get(rate))
        if n and n > 0 and value is not None:
            hits += round(value * n)
            total += int(n)
    return hits, total


def pooled_rates(rows: list[dict]) -> dict:
    """The rate, interval, and denominator columns pooled over `rows`. The `_inputs` column is the
    sum over the pooled rows, whose inputs never overlap."""
    out: dict = {}
    for rate in RATES:
        hits, n = hits_and_n(rows, rate)
        out[rate], out[rate + "_low"], out[rate + "_high"] = wilson(hits, n)
        out[rate + "_n"] = n
        out[rate + "_inputs"] = total(rows, rate + "_inputs")
    return out


def total(rows: list[dict], column: str) -> int:
    return sum(int(number(r.get(column)) or 0) for r in rows)


def pooled_summary(csv_rows: list[dict], order: list[str], attempts: list[dict]) -> list[dict]:
    """One row per AI model, setup, and validity label, as `compute` gives them. Cost comes from the
    attempt rows (raw records), since the CSV holds only per-group cost per success."""
    costs: dict = defaultdict(float)
    for a in attempts:
        costs[(a["model"], a["setup"], a["validity"])] += a["cost"]
    groups = defaultdict(list)
    for row in csv_rows:
        groups[(row["model"], row["setup"], row["validity"])].append(row)
    out = []
    for key in sorted_keys(groups, summary_sort_key, order):
        rows = groups[key]
        item = dict(zip(("model", "setup", "validity"), key))
        item["attempts"] = total(rows, "attempts")
        item["infrastructure_failure_count"] = total(rows, "infrastructure_failure_count")
        item.update(pooled_rates(rows))
        successes = hits_and_n(rows, "success_rate")[0]
        item["cost_per_success"] = costs[key] / successes if successes else NA
        out.append(item)
    return out
