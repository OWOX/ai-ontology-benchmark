# Spec: docs/specs/run.md
"""Sends every input of one release to the AI models of one experiment and appends one raw
record per attempt. Reads config/experiments/<ID>.toml, config/prices.toml, releases/<release>/,
the assessment files, and results/<ID>/raw/*.jsonl (to resume). Writes results/<ID>/experiment.toml
and appends to results/<ID>/raw/<model name>.jsonl. Unless --no-commit, it also commits the config
and results after every record to the local branch results/<ID>, and pushes that branch at exit.
"""

import argparse
import hashlib
import json
import os
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_experiment_config, load_prices
from src.release.release import assessment_sha256
from src.run.branch import BranchError, ResultsBranch
from src.run.budget import (BudgetError, check_prices, check_request_budget, check_spend,
                            print_estimate, worst_case_request_cost)
from src.run.models import InfrastructureError, call_model
from src.run.prompts import SETUPS, build_prompt, prompt_versions
from src.run.raw import read_raw
from src.validator import validate


class RunError(Exception):
    """A checked error. The message names the file or field at fault."""


def load_release(folder: Path) -> tuple[dict, list[dict]]:
    """Check the release against its manifest and the working tree. Return (manifest, inputs)."""
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise RunError(f"{manifest_path}: file not found")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError:
        raise RunError(f"{manifest_path}: not valid JSON") from None
    for field in ("files", "assessment_sha256", "prompt_versions", "input_set_id", "release_config"):
        if field not in manifest:
            raise RunError(f"{manifest_path}: field '{field}' is missing")
    if "seed" not in manifest["release_config"]:
        raise RunError(f"{manifest_path}: field 'release_config.seed' is missing")
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


def without_budget(data: bytes) -> dict:
    config = tomllib.loads(data.decode("utf-8"))
    config.pop("budget", None)
    return config


def check_experiment_copy(config_path: Path, results: Path) -> None:
    """The stored copy must equal the config apart from [budget]."""
    copy = results / "experiment.toml"
    if copy.exists() and without_budget(copy.read_bytes()) != without_budget(config_path.read_bytes()):
        raise RunError(f"{config_path}: differs from {copy}; an experiment never changes once it starts, except its [budget]")


def read_done(raw_path: Path) -> set[tuple]:
    """Return the (input_id, setup, model, attempt_number) keys already in a raw file."""
    records, _ = read_raw(raw_path)
    done = set()
    for record in records:
        try:
            done.add((record["input_id"], record["setup"], record["model"], record["attempt_number"]))
        except KeyError as error:
            raise RunError(f"{raw_path}: a record lacks field {error}") from None
    return done


def pending_attempts(config: dict, inputs: list[dict], raw_dir: Path, only_model: str | None):
    """Yield (input, model, setup, attempt_number) in loop order, skipping recorded attempts."""
    models = [m for m in config["models"] if only_model in (None, m["name"])]
    done = {m["name"]: read_done(raw_dir / f"{m['name']}.jsonl") for m in models}
    for row in inputs:
        if "puzzles" in config and row["puzzle"] not in config["puzzles"]:
            continue
        for model in models:
            for setup in SETUPS:
                for number in range(1, config["attempts"] + 1):
                    if (row["input_id"], setup, model["name"], number) not in done[model["name"]]:
                        yield row, model, setup, number


def call_with_retries(model: dict, prompt: str, config: dict, can_afford) -> tuple:
    """Return (reply or None, retry_input_tokens, retry_output_tokens, budget error or None).

    `can_afford(retry_in, retry_out)` raises BudgetError if another call would pass a budget.
    It runs before every call. A stop before the first call is raised; a stop after failed
    calls is returned, so the caller can record the paid retry tokens first. Retry only
    infrastructure errors.
    """
    retry_in = retry_out = 0
    for call_number in range(config["retry_cap"] + 1):
        try:
            can_afford(retry_in, retry_out)
        except BudgetError as stop:
            if call_number == 0:
                raise
            return None, retry_in, retry_out, stop
        try:
            return call_model(model, prompt, config["max_output_tokens"]), retry_in, retry_out, None
        except InfrastructureError as error:
            retry_in += error.input_tokens
            retry_out += error.output_tokens
    return None, retry_in, retry_out, None


def make_record(config, manifest, row, model, setup, number, prompt, versions,
                reply, retry_in: int, retry_out: int) -> dict:
    """Build the raw record of one attempt from the reply (None after an infrastructure failure)."""
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
    if raw_path.exists() and raw_path.stat().st_size > 0:
        with open(raw_path, "rb") as probe:
            probe.seek(-1, 2)
            torn = probe.read(1) != b"\n"
        if torn:  # end the fragment as its own line; never rewrite it
            with open(raw_path, "ab") as fix:
                fix.write(b"\n")
    with open(raw_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()


def run(args: argparse.Namespace) -> int:
    config_path = args.configs / f"{args.experiment}.toml"
    config = load_experiment_config(config_path)
    names = [m["name"] for m in config["models"]]
    if args.model and args.model not in names:
        raise RunError(f"{config_path}: field 'models' has no model {args.model!r}")
    folder = args.releases / config["release"]
    manifest, inputs = load_release(folder)
    for name in config.get("puzzles", []):
        if name not in manifest["release_config"]["puzzles"]:
            raise RunError(f"{config_path}: field 'puzzles' names {name!r}, which release {config['release']} does not hold")
    results = args.results / config["experiment_id"]
    check_experiment_copy(config_path, results)
    prices = load_prices(args.prices)
    check_prices(config, prices, args.prices)
    pending = list(pending_attempts(config, inputs, results / "raw", args.model))
    if args.limit is not None:
        pending = pending[: args.limit]
    for row, model, setup, _ in pending:
        check_request_budget(config_path, config, model, build_prompt(folder / "prompts", row, setup), prices)
    if args.estimate:
        print_estimate(config, pending, prices, folder / "prompts", results / "raw")
        return 0
    versions = manifest["prompt_versions"]
    branch = None
    if not (args.dry_run or args.no_commit):
        branch = ResultsBranch(config_path, results, config["experiment_id"])  # before any write or call
    if not args.dry_run:
        (results / "raw").mkdir(parents=True, exist_ok=True)
        copy = results / "experiment.toml"
        if not copy.exists() or copy.read_bytes() != config_path.read_bytes():
            temp = copy.with_name(f".experiment.toml.{os.getpid()}.tmp")  # atomic: models started together
            temp.write_bytes(config_path.read_bytes())  # never read half a file
            os.replace(temp, copy)  # first run, or only [budget] changed
    outcomes: Counter = Counter()
    if branch:
        branch.commit(f"Results: experiment {config['experiment_id']}, start")
    try:
        play(args, config, manifest, folder, results, prices, versions, pending, outcomes, branch)
    finally:
        if branch:
            finish(branch, config["experiment_id"])
    if not args.dry_run:
        print(f"{sum(outcomes.values())} new attempts: " + ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items())))
    return 0


def finish(branch: ResultsBranch, experiment_id: str) -> None:
    """Commit what is left and push the branch once. Warn, never fail, so the run's own error stays last."""
    try:
        branch.commit(f"Results: experiment {experiment_id}, end")
    except BranchError as error:
        print(f"warning: commit to results/{experiment_id} failed: {error}", file=sys.stderr)
    problem = branch.push()
    if problem:
        print(f"warning: push of results/{experiment_id} failed: {problem}", file=sys.stderr)


def play(args, config, manifest, folder, results, prices, versions, pending, outcomes, branch) -> None:
    for left, (row, model, setup, number) in zip(range(len(pending), 0, -1), pending):
        prompt = build_prompt(folder / "prompts", row, setup)
        if args.dry_run:
            print(f"--- {row['input_id']} {setup} {model['name']} attempt {number}\n{prompt}")
            continue
        worst = worst_case_request_cost(prompt, config["max_output_tokens"], prices[model["name"]])
        price = prices[model["name"]]

        def can_afford(retry_in: int, retry_out: int) -> None:
            paid = (retry_in * price["price_input_per_mtok"] + retry_out * price["price_output_per_mtok"]) / 1e6
            check_spend(config, prices, results / "raw", model["name"], worst + paid, left)

        reply, retry_in, retry_out, stop = call_with_retries(model, prompt, config, can_afford)
        record = make_record(config, manifest, row, model, setup, number, prompt, versions,
                             reply, retry_in, retry_out)
        append_record(results / "raw" / f"{model['name']}.jsonl", record)
        outcomes[record["outcome"]] += 1
        if branch:
            branch.commit(f"Results: experiment {config['experiment_id']}, {model['name']} "
                          f"{row['input_id']} {setup} attempt {number}")
        if stop:
            raise stop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one experiment against its release.")
    parser.add_argument("--experiment", required=True, help="experiment id, the config file stem")
    parser.add_argument("--model", help="run only this AI model")
    parser.add_argument("--limit", type=int, help="stop after this many new attempts")
    parser.add_argument("--dry-run", action="store_true", help="print prompts, write nothing")
    parser.add_argument("--estimate", action="store_true", help="print attempts and worst-case cost")
    parser.add_argument("--no-commit", action="store_true", help="do not commit to results/<id> (for tests)")
    parser.add_argument("--releases", default="releases", type=Path)
    parser.add_argument("--configs", default="config/experiments", type=Path)
    parser.add_argument("--prices", default="config/prices.toml", type=Path)
    parser.add_argument("--results", default="results", type=Path)
    try:
        return run(parser.parse_args(argv))
    except (RunError, BudgetError, BranchError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
