# Spec: docs/specs/run.md
"""Sends every input of one release to the AI models of one experiment and appends one raw
record per attempt. Reads config/experiments/<ID>.toml, config/prices.toml, releases/<release>/,
the assessment files, and results/<ID>/raw/*.jsonl (to resume). Writes results/<ID>/experiment.toml
and appends to results/<ID>/raw/<model name>.jsonl.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_experiment_config, load_prices
from src.release.release import assessment_sha256
from src.run.models import InfrastructureError, call_model
from src.run.prompts import SETUPS, build_prompt, prompt_versions
from src.validator import validate


class RunError(Exception):
    """A checked error. The message names the file or field at fault."""


def load_release(folder: Path) -> tuple[dict, list[dict]]:
    """Check the release against its manifest and the working tree. Return (manifest, inputs)."""
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise RunError(f"{manifest_path}: file not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, digest in manifest["files"].items():
        path = folder / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RunError(f"{path}: does not match its sha256 in manifest.json (field 'files')")
    if assessment_sha256() != manifest["assessment_sha256"]:
        raise RunError(f"{manifest_path}: field 'assessment_sha256' differs from the assessment files in the working tree")
    lines = (folder / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
    inputs = [json.loads(line) for line in lines]
    if prompt_versions(folder / "prompts", inputs) != manifest["prompt_versions"]:
        raise RunError(f"{manifest_path}: field 'prompt_versions' differs from the prompts the working tree renders")
    return manifest, inputs


def check_experiment_copy(config_path: Path, results: Path) -> None:
    copy = results / "experiment.toml"
    if copy.exists() and copy.read_bytes() != config_path.read_bytes():
        raise RunError(f"{config_path}: differs from {copy}; an experiment never changes once it starts")


def read_done(raw_path: Path) -> set[tuple]:
    """Return the (input_id, setup, model, attempt_number) keys already in a raw file."""
    if not raw_path.is_file():
        return set()
    done = set()
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            done.add((row["input_id"], row["setup"], row["model"], row["attempt_number"]))
    return done


def pending_attempts(config: dict, inputs: list[dict], raw_dir: Path, only_model: str | None):
    """Yield (input, model, setup, attempt_number) in loop order, skipping recorded attempts."""
    models = [m for m in config["models"] if only_model in (None, m["name"])]
    done = {m["name"]: read_done(raw_dir / f"{m['name']}.jsonl") for m in models}
    for row in inputs:
        for model in models:
            for setup in SETUPS:
                for number in range(1, config["attempts"] + 1):
                    if (row["input_id"], setup, model["name"], number) not in done[model["name"]]:
                        yield row, model, setup, number


def call_with_retries(model: dict, prompt: str, config: dict) -> tuple[object, int, int]:
    """Return (reply or None, retry_input_tokens, retry_output_tokens). Retry only infrastructure errors."""
    retry_in = retry_out = 0
    for _ in range(config["retry_cap"] + 1):
        try:
            return call_model(model, prompt, config["max_output_tokens"]), retry_in, retry_out
        except InfrastructureError as error:
            retry_in += error.input_tokens
            retry_out += error.output_tokens
    return None, retry_in, retry_out


def make_record(config, manifest, row, model, setup, number, prompt, versions) -> dict:
    reply, retry_in, retry_out = call_with_retries(model, prompt, config)
    if reply is None:
        text, stop, served, tokens_in, tokens_out, latency = "", "infrastructure_failure", "", 0, 0, None
    else:
        text, stop, served = reply.text, reply.stop_reason, reply.served_model
        tokens_in, tokens_out, latency = reply.input_tokens, reply.output_tokens, reply.latency_s
    verdict = validate(row, text, stop)
    return {
        "experiment_id": config["experiment_id"], "release_version": config["release"],
        "input_id": row["input_id"], "input_set_id": manifest["input_set_id"],
        "puzzle": row["puzzle"], "scramble_depth": row["scramble_depth"], "validity": row["validity"],
        "setup": setup, "prompt_version": versions[setup][row["puzzle"]], "model": model["name"],
        "seed": manifest["release_config"]["seed"], "input_seed": row["input_seed"],
        "attempt_number": number, "raw_response": text, "parsed_moves": verdict.parsed_moves,
        "outcome": verdict.outcome, "hallucination": verdict.hallucination,
        "mismatch": verdict.mismatch, "move_count": verdict.move_count,
        "input_tokens": tokens_in, "output_tokens": tokens_out,
        "retry_input_tokens": retry_in, "retry_output_tokens": retry_out,
        "latency_s": latency, "stop_reason": stop, "served_model": served,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def append_record(raw_path: Path, record: dict) -> None:
    with open(raw_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()


def print_estimate(config: dict, pending: list, prices_path: Path, templates: Path) -> None:
    prices = load_prices(prices_path)
    total = 0.0
    for model in config["models"]:
        if model["name"] not in prices:
            raise RunError(f"{prices_path}: no prices for model {model['name']!r}")
        mine = [item for item in pending if item[1]["name"] == model["name"]]
        tokens_in = sum(len(build_prompt(templates, row, setup)) // 4 for row, _, setup, _ in mine)
        price = prices[model["name"]]
        cost = (tokens_in * price["price_input_per_mtok"]
                + len(mine) * config["max_output_tokens"] * price["price_output_per_mtok"]) / 1e6
        total += cost
        print(f"{model['name']}: {len(mine)} attempts, ~{tokens_in} input tokens, worst case ${cost:.4f}")
    print(f"total: {len(pending)} attempts, worst case ${total:.4f}")


def run(args: argparse.Namespace) -> int:
    config_path = args.configs / f"{args.experiment}.toml"
    config = load_experiment_config(config_path)
    names = [m["name"] for m in config["models"]]
    if args.model and args.model not in names:
        raise RunError(f"{config_path}: field 'models' has no model {args.model!r}")
    folder = args.releases / config["release"]
    manifest, inputs = load_release(folder)
    results = args.results / config["experiment_id"]
    check_experiment_copy(config_path, results)
    pending = list(pending_attempts(config, inputs, results / "raw", args.model))
    if args.limit is not None:
        pending = pending[: args.limit]
    if args.estimate:
        print_estimate(config, pending, args.prices, folder / "prompts")
        return 0
    versions = manifest["prompt_versions"]
    if not args.dry_run:
        (results / "raw").mkdir(parents=True, exist_ok=True)
        if not (results / "experiment.toml").exists():
            (results / "experiment.toml").write_bytes(config_path.read_bytes())
    outcomes: Counter = Counter()
    for row, model, setup, number in pending:
        prompt = build_prompt(folder / "prompts", row, setup)
        if args.dry_run:
            print(f"--- {row['input_id']} {setup} {model['name']} attempt {number}\n{prompt}")
            continue
        record = make_record(config, manifest, row, model, setup, number, prompt, versions)
        append_record(results / "raw" / f"{model['name']}.jsonl", record)
        outcomes[record["outcome"]] += 1
    if not args.dry_run:
        print(f"{sum(outcomes.values())} new attempts: " + ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items())))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one experiment against its release.")
    parser.add_argument("--experiment", required=True, help="experiment id, the config file stem")
    parser.add_argument("--model", help="run only this AI model")
    parser.add_argument("--limit", type=int, help="stop after this many new attempts")
    parser.add_argument("--dry-run", action="store_true", help="print prompts, write nothing")
    parser.add_argument("--estimate", action="store_true", help="print attempts and worst-case cost")
    parser.add_argument("--releases", default="releases", type=Path)
    parser.add_argument("--configs", default="config/experiments", type=Path)
    parser.add_argument("--prices", default="config/prices.toml", type=Path)
    parser.add_argument("--results", default="results", type=Path)
    try:
        return run(parser.parse_args(argv))
    except (RunError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
