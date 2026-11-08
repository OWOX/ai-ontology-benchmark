# Spec: docs/specs/ui.md
"""Pools the rows of an experiment's report CSV (`<version>.metrics.csv`) into bundle rows and
summary rows. Each rate is pooled as hits over n, with hits rounded back from the CSV's 4-decimal
rate. The CSV holds no per-input cells, so the intervals are Wilson score intervals over the pooled
attempts, for display only (the UI marks them with `*`). Reads parsed CSV rows and writes nothing.
"""

import math
from collections import defaultdict

from src.evaluate.metrics import NA, summary_sort_key, sorted_keys

Z = 1.96  # 95% confidence, used by `wilson`

RATES = ("precision", "coverage", "hallucination_rate", "mismatch_detection_rate", "false_mismatch_rate",
         "malformed_output_rate", "truncated_rate", "abstention_rate", "format_error_rate",
         "reason_hallucination_rate", "diagnosis_rate")


def wilson(hits: int, n: int) -> tuple:
    """Return (rate, low, high) with a 95% Wilson score interval, or n/a when n is 0."""
    if n == 0:
        return NA, NA, NA
    p = hits / n
    spread = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    centre = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    return p, max(0.0, centre - spread), min(1.0, centre + spread)


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


def balanced_precision(rows: list[dict]) -> dict:
    """The precision columns over rows of both validity labels: the mean of the valid rows' and the invalid rows'
    pooled precisions, and of their interval ends. n/a when either label has no precision. `_n` and `_inputs`
    are the sums."""
    sides = []
    for validity in ("valid", "invalid"):
        part = [r for r in rows if r.get("validity") == validity]
        hits, n = hits_and_n(part, "precision")
        sides.append((*wilson(hits, n), n, total(part, "precision_inputs")))
    out = {"precision_n": sum(s[3] for s in sides), "precision_inputs": sum(s[4] for s in sides)}
    for i, name in enumerate(("precision", "precision_low", "precision_high")):
        out[name] = sum(s[i] for s in sides) / 2 if all(s[3] for s in sides) else NA
    return out


def pooled_rates(rows: list[dict], balanced: bool = False) -> dict:
    """The rate, interval, and denominator columns pooled over `rows`. The `_inputs` column is the
    sum over the pooled rows, whose inputs never overlap. `balanced` is true for rows of both validity
    labels, which show balanced precision in place of the pooled one."""
    out: dict = {}
    for rate in RATES:
        hits, n = hits_and_n(rows, rate)
        out[rate], out[rate + "_low"], out[rate + "_high"] = wilson(hits, n)
        out[rate + "_n"] = n
        out[rate + "_inputs"] = total(rows, rate + "_inputs")
    return out | balanced_precision(rows) if balanced else out


def total(rows: list[dict], column: str) -> int:
    return sum(int(number(r.get(column)) or 0) for r in rows)


def pooled_summary(csv_rows: list[dict], order: list[str], attempts: list[dict]) -> list[dict]:
    """One row per AI model, setup, and validity label, as `compute` gives them. Cost per attempt comes from the
    attempt rows (raw records), since the CSV holds it only per puzzle and depth. A rate whose columns an old
    CSV lacks pools to n/a."""
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
        item["cost_per_attempt"] = costs[key] / item["attempts"] if item["attempts"] else NA
        out.append(item)
    return out
