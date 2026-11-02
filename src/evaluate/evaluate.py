# Spec: docs/specs/evaluate.md
"""Re-validates every raw record of one experiment under one release and computes the metrics.
Reads results/<ID>/experiment.toml, results/<ID>/raw/*.jsonl, the release folder, the assessment
files and the token prices. Writes results/<ID>/prices.toml (first run only), <VERSION>.metrics.csv
and <VERSION>.md. Never edits a raw record, and makes no model calls. The metric maths is in
src/evaluate/metrics.py.
"""

import argparse
import csv
import io
import json
import sys
from pathlib import Path

from src.config import load_experiment_config, load_prices
from src.evaluate.metrics import EvalError, compute
from src.evaluate.report import write_report
from src.release.release import parse_version
from src.run.raw import read_raw
from src.run.run import RunError, load_release

# Moves to src.run.models.DECISION_PROVIDERS in Task 4.
DECISION_PROVIDERS = ("typesafe", "cloudflare", "fake_decision")

REQUIRED = (
    "input_id", "setup", "model", "attempt_number", "raw_response", "stop_reason", "outcome",
    "input_tokens", "output_tokens", "retry_input_tokens", "retry_output_tokens", "latency_s",
    "served_model", "created_at",
)


def read_raw_dir(raw_dir: Path) -> tuple[list[dict], int]:
    """Return (records, skipped line count) over every raw file of the experiment."""
    if not raw_dir.is_dir():
        raise EvalError(f"{raw_dir}: folder not found")
    records, skipped = [], 0
    seen: set[tuple] = set()
    for path in sorted(raw_dir.glob("*.jsonl")):
        found, torn = read_raw(path)
        skipped += torn
        for record in found:
            missing = [f for f in REQUIRED if f not in record]
            if missing:
                raise EvalError(f"{path}: a record lacks field '{missing[0]}'")
            key = (record["input_id"], record["setup"], record["model"], record["attempt_number"])
            if key in seen:
                raise EvalError(f"{path}: attempt {key} appears more than once")
            seen.add(key)
            records.append(record)
    return records, skipped


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
    version = args.release or config["release"]
    release_dir = args.releases / version
    check_release(args.releases, config["release"], version)
    records, torn = read_raw_dir(results / "raw")
    saved_prices = results / "prices.toml"
    prices_path = saved_prices if saved_prices.exists() else args.prices
    prices = load_prices(prices_path)
    check_prices(prices, prices_path, config)
    names = [m["name"] for m in config["models"]]
    decision_models = {m["name"] for m in config["models"] if m["provider"] in DECISION_PROVIDERS}
    attempt_rows, metric_rows, summary_rows = compute(records, release_dir, prices, names, decision_models)
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
