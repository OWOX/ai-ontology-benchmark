# Spec: docs/specs/evaluate.md
"""Re-validates every raw record of one experiment under one release and computes the metrics.
Reads results/<ID>/experiment.toml, results/<ID>/raw/*.jsonl, the release folder, the assessment
files and the token prices. Writes results/<ID>/prices.toml (first run only), <VERSION>.metrics.csv
and <VERSION>.md. Never edits a raw record, and makes no model calls.
"""

import argparse
import csv
import io
import json
import math
import sys
from collections import Counter, defaultdict
from operator import itemgetter
from pathlib import Path

from src.config import load_experiment_config, load_prices
from src.evaluate.report import write_report
from src.puzzles.registry import ENGINES, get_engine
from src.release.release import parse_version
from src.run.prompts import SETUPS
from src.run.run import RunError, load_release
from src.validator import validate

NA = "n/a"
Z = 1.96  # 95% confidence
REQUIRED = (
    "input_id", "setup", "model", "attempt_number", "raw_response", "stop_reason", "outcome",
    "input_tokens", "output_tokens", "retry_input_tokens", "retry_output_tokens", "latency_s",
    "served_model", "created_at",
)
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
    by_input = defaultdict(list)
    for r in rows:
        by_input[r["input_id"]].append(r["outcome"])
    shares = [Counter(o).most_common(1)[0][1] / len(o) for o in by_input.values() if len(o) >= 2]
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


def make_attempt_rows(raw_records, inputs, prices, cache) -> list[dict]:
    by_id = {row["input_id"]: (number, row) for number, row in enumerate(inputs, start=1)}
    rows = []
    for raw in raw_records:
        if raw["input_id"] not in by_id:
            raise EvalError(
                f"raw record {raw['input_id']!r}: field 'input_id' is not in inputs.jsonl")
        if raw["model"] not in prices:
            raise EvalError(f"prices: no prices for model {raw['model']!r}")
        line, source = by_id[raw["input_id"]]
        verdict = validate(source, raw["raw_response"], raw["stop_reason"])
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
            models: list[str] | None = None) -> tuple:
    """Return (attempt_rows, metric_rows, summary_rows). `models` fixes the AI model sort order."""
    lines = (Path(release_dir) / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
    inputs = [json.loads(line) for line in lines]
    rows = make_attempt_rows(raw_records, inputs, prices, {})
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


def read_raw(raw_dir: Path) -> tuple[list[dict], int]:
    """Return (records, torn line count). A torn line starts with "{" and lacks the closing "}"."""
    if not raw_dir.is_dir():
        raise EvalError(f"{raw_dir}: folder not found")
    records, torn = [], 0
    for path in sorted(raw_dir.glob("*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                record = json.loads(line)
                missing = [f for f in REQUIRED if f not in record]
            except (ValueError, TypeError):
                if line.startswith("{") and not line.endswith("}"):
                    torn += 1
                    continue
                raise EvalError(f"{path}: line {number} is not a valid raw record") from None
            if missing:
                raise EvalError(f"{path}: line {number} lacks field '{missing[0]}'")
            records.append(record)
    return records, torn


def check_release(releases: Path, base: str, target: str) -> None:
    """The target must be the experiment's release or a mirror of it."""
    manifest, _ = load_release(releases / target)
    if target == base:
        return
    base_path = releases / base / "manifest.json"
    if not base_path.is_file():
        raise EvalError(f"{base_path}: file not found")
    old = json.loads(base_path.read_text(encoding="utf-8"))
    if parse_version(base)[:2] != parse_version(target)[:2]:
        raise EvalError(f"{releases / target}: not a mirror of {base}; major and minor must match")
    if old["files"]["inputs.jsonl"] != manifest["files"]["inputs.jsonl"]:
        raise EvalError(f"{releases / target / 'inputs.jsonl'}: differs from release {base}")
    if old["prompt_versions"] != manifest["prompt_versions"]:
        raise EvalError(
            f"{releases / target / 'manifest.json'}: "
            f"field 'prompt_versions' differs from release {base}")


def show_float(value: object) -> object:
    return f"{value:.4f}" if isinstance(value, float) else value


def csv_text(metric_rows: list[dict]) -> str:
    """Return the metrics CSV, floats with 4 decimal places."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(metric_rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in metric_rows:
        writer.writerow({key: show_float(value) for key, value in row.items()})
    return buffer.getvalue()


def check_prices(prices: dict, prices_path: Path, config: dict) -> None:
    """Every AI model in the experiment config needs a price, whether or not it has records."""
    for model in config["models"]:
        if model["name"] not in prices:
            raise EvalError(f"{prices_path}: no prices for model {model['name']!r}")


def evaluate(args: argparse.Namespace) -> None:
    results = args.results / args.experiment
    config = load_experiment_config(results / "experiment.toml")
    config["experiment_id"] = args.experiment
    version = args.release or config["release"]
    release_dir = args.releases / version
    check_release(args.releases, config["release"], version)
    records, torn = read_raw(results / "raw")
    saved_prices = results / "prices.toml"
    prices_path = saved_prices if saved_prices.exists() else args.prices
    prices = load_prices(prices_path)
    check_prices(prices, prices_path, config)
    names = [m["name"] for m in config["models"]]
    attempt_rows, metric_rows, summary_rows = compute(records, release_dir, prices, names)
    if not metric_rows:
        raise EvalError(f"{results / 'raw'}: no raw records")
    csv_content = csv_text(metric_rows)
    # Every check is done. Write the outputs last, the prices copy after the others.
    write_report(results / f"{version}.md", args.experiment, config, release_dir, prices,
                 attempt_rows, metric_rows, summary_rows, torn)
    (results / f"{version}.metrics.csv").write_text(csv_content, encoding="utf-8", newline="")
    if not saved_prices.exists():
        saved_prices.write_bytes(prices_path.read_bytes())
    print(f"Evaluated {len(attempt_rows)} attempts under release {version}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-validate one experiment and write its report.")
    parser.add_argument("--experiment", required=True, help="experiment id, the config file stem")
    parser.add_argument("--release", help="release to score under (default: the experiment's)")
    parser.add_argument("--releases", default="releases", type=Path)
    parser.add_argument("--results", default="results", type=Path)
    parser.add_argument("--prices", default="config/prices.toml", type=Path)
    try:
        evaluate(parser.parse_args(argv))
    except (EvalError, RunError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
