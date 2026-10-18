# Spec: docs/specs/evaluate.md
"""Re-validates every raw record of one experiment under one release and computes the metrics.
Reads results/<ID>/experiment.toml, results/<ID>/raw/*.jsonl, the release folder, the assessment
files and the token prices. Writes results/<ID>/prices.toml (first run only), <VERSION>.metrics.csv
and <VERSION>.md. Never edits a raw record, and makes no model calls.
"""

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
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
RATES = ("success_rate", "hallucination_rate", "mismatch_detection_rate", "false_mismatch_rate",
         "malformed_output_rate")
REQUIRED = ("input_id", "setup", "model", "attempt_number", "raw_response", "stop_reason", "outcome",
            "input_tokens", "output_tokens", "retry_input_tokens", "retry_output_tokens", "latency_s",
            "served_model", "created_at")
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


def rates(rows: list[dict], validity: str) -> dict:
    """Rates over the attempts that are not infrastructure failures (`rows` holds only those)."""
    count = lambda outcome: sum(r["outcome"] == outcome for r in rows)
    flagged = sum(r["mismatch"] for r in rows)
    valid, invalid = validity == "valid", validity == "invalid"
    out: dict = {}
    rate_columns(out, "success_rate", count("success"), len(rows))
    rate_columns(out, "hallucination_rate", count("hallucination"), len(rows))
    rate_columns(out, "mismatch_detection_rate", flagged if invalid else 0, len(rows) if invalid else 0)
    rate_columns(out, "false_mismatch_rate", flagged if valid else 0, len(rows) if valid else 0)
    rate_columns(out, "malformed_output_rate", count("malformed_output"), len(rows))
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
    successes = sum(r["outcome"] == "success" for r in rows)
    out = {"attempts": len(rows), "infrastructure_failure_count": len(rows) - len(done)}
    out.update(rates(done, validity))
    out["cost_per_success"] = sum(r["cost"] for r in rows) / successes if successes else NA
    if full:
        ratios = [r["move_count"] / r["reference_length"] for r in done
                  if r["outcome"] == "success" and validity == "valid" and r["reference_length"]]
        out["efficiency"] = mean(ratios)
        out["consistency"] = consistency(done)
        out["latency_per_attempt_s"] = mean([r["latency_s"] for r in done if r["latency_s"] is not None])
        out["input_tokens_per_attempt"] = mean([r["input_tokens"] + r["retry_input_tokens"] for r in rows])
        out["output_tokens_per_attempt"] = mean([r["output_tokens"] + r["retry_output_tokens"] for r in rows])
    return out


def reference_length(cache: dict, row: dict) -> int | None:
    """Reference length of a valid input, or None where the engine has no solver yet."""
    if row["input_id"] not in cache:
        try:
            cache[row["input_id"]] = get_engine(row["puzzle"]).reference_length(row["state"])
        except NotImplementedError:
            cache[row["input_id"]] = None
    return cache[row["input_id"]]


def make_attempt_rows(raw_records, inputs, prices, cache) -> list[dict]:
    by_id = {row["input_id"]: (number, row) for number, row in enumerate(inputs, start=1)}
    rows = []
    for raw in raw_records:
        if raw["input_id"] not in by_id:
            raise EvalError(f"raw record {raw['input_id']!r}: field 'input_id' is not in inputs.jsonl")
        if raw["model"] not in prices:
            raise EvalError(f"prices: no prices for model {raw['model']!r}")
        line, source = by_id[raw["input_id"]]
        verdict = validate(source, raw["raw_response"], raw["stop_reason"])
        price = prices[raw["model"]]
        cost = ((raw["input_tokens"] + raw["retry_input_tokens"]) * price["price_input_per_mtok"]
                + (raw["output_tokens"] + raw["retry_output_tokens"]) * price["price_output_per_mtok"]) / 1e6
        reference = reference_length(cache, source) if verdict.outcome == "success" and source["validity"] == "valid" else None
        rows.append({
            "input_id": raw["input_id"], "input_line": line, "puzzle": source["puzzle"],
            "scramble_depth": source["scramble_depth"], "validity": source["validity"], "setup": raw["setup"],
            "model": raw["model"], "attempt_number": raw["attempt_number"], "stored_outcome": raw["outcome"],
            "outcome": verdict.outcome, "parsed_moves": verdict.parsed_moves, "mismatch": verdict.mismatch,
            "move_count": verdict.move_count, "reference_length": reference, "input_tokens": raw["input_tokens"],
            "output_tokens": raw["output_tokens"], "retry_input_tokens": raw["retry_input_tokens"],
            "retry_output_tokens": raw["retry_output_tokens"], "latency_s": raw["latency_s"],
            "served_model": raw["served_model"], "created_at": raw["created_at"], "cost": cost,
        })
    return rows


def compute(raw_records: list[dict], release_dir: Path, prices: dict, models: list[str] | None = None) -> tuple:
    """Return (attempt_rows, metric_rows, summary_rows). `models` fixes the AI model sort order."""
    lines = (Path(release_dir) / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
    inputs = [json.loads(line) for line in lines]
    rows = make_attempt_rows(raw_records, inputs, prices, {})
    order = models or sorted({r["model"] for r in rows})
    puzzle_rank, setup_rank = list(ENGINES), list(SETUPS)
    model_rank = lambda name: (order.index(name) if name in order else len(order), name)
    rows.sort(key=lambda r: (r["input_line"], model_rank(r["model"]), setup_rank.index(r["setup"]), r["attempt_number"]))

    groups, pooled = defaultdict(list), defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in KEY)].append(r)
        pooled[(r["model"], r["setup"], r["validity"])].append(r)
    sort_key = lambda k: (puzzle_rank.index(k[0]), setup_rank.index(k[1]), model_rank(k[2]), k[3], k[4] != "valid")
    metric_rows = [dict(zip(KEY, key), **group_metrics(groups[key], key[4], True)) for key in sorted(groups, key=sort_key)]
    pooled_key = lambda k: (setup_rank.index(k[1]), model_rank(k[0]), k[2] != "valid")
    summary_rows = [dict(zip(("model", "setup", "validity"), key), **group_metrics(pooled[key], key[2], False))
                    for key in sorted(pooled, key=pooled_key)]
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
        raise EvalError(f"{releases / target / 'manifest.json'}: field 'prompt_versions' differs from release {base}")


def write_csv(path: Path, metric_rows: list[dict]) -> None:
    def show(value: object) -> object:
        return f"{value:.4f}" if isinstance(value, float) else value
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metric_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: show(v) for k, v in row.items()} for row in metric_rows)


def evaluate(args: argparse.Namespace) -> None:
    results = args.results / args.experiment
    config_path = results / "experiment.toml"
    config = load_experiment_config(config_path)
    config["experiment_id"] = args.experiment
    version = args.release or config["release"]
    check_release(args.releases, config["release"], version)
    records, torn = read_raw(results / "raw")
    saved_prices = results / "prices.toml"
    prices_path = saved_prices if saved_prices.exists() else args.prices
    prices = load_prices(prices_path)
    names = [m["name"] for m in config["models"]]
    attempt_rows, metric_rows, summary_rows = compute(records, args.releases / version, prices, names)
    if not metric_rows:
        raise EvalError(f"{results / 'raw'}: no raw records")
    if not saved_prices.exists():
        saved_prices.write_bytes(prices_path.read_bytes())
    write_csv(results / f"{version}.metrics.csv", metric_rows)
    write_report(results / f"{version}.md", args.experiment, config, args.releases / version, prices,
                 attempt_rows, metric_rows, summary_rows, torn)
    print(f"Evaluated {len(attempt_rows)} attempts under release {version}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-validate one experiment and write its report.")
    parser.add_argument("--experiment", required=True, help="experiment id, the config file stem")
    parser.add_argument("--release", help="release version to score under (default: the experiment's)")
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
