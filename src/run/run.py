# Spec: docs/specs/run.md
"""Sends every input of one release to the AI models of one experiment and appends one raw
record per attempt. Reads config/experiments/<ID>.toml (or stdin with --config -), config/prices.toml, releases/<release>/,
the assessment files, and results/<ID>/raw/*.jsonl (to resume). Writes results/<ID>/experiment.toml
and appends to results/<ID>/raw/<model name>.jsonl. Unless --no-commit, it also commits the config
and results after every record to the local branch results/<ID>, and pushes that branch at exit.
It shows live progress through src/run/progress.py.
"""

import argparse
import hashlib
import json
import os
import signal
import sys
import tomllib
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_experiment_config, load_prices, max_moves, parse_experiment_config
from src.release.release import assessment_sha256
from src.run.branch import BranchError, ResultsBranch
from src.run.budget import (BudgetError, check_prices, check_request_budget, check_spend,
                            print_estimate, spent_by_model, worst_case_request_cost)
from src.run.decision import DecisionResult, run_decision_attempt
from src.run.models import DECISION_PROVIDERS, InfrastructureError, call_model
from src.run.progress import Progress
from src.run.prompts import (SETUPS, both_prompt_versions, build_prompt, decision_questions, decision_state,
                             load_questions, prompt_versions, worst_request)
from src.run.raw import read_raw
from src.puzzles.registry import get_engine
from src.validator import validate


class RunError(Exception):
    """A checked error. The message names the file or field at fault."""


def load_release(folder: Path, needs_decision: bool = False) -> tuple[dict, list[dict]]:
    """Check the release against its manifest and the working tree. Return (manifest, inputs).
    A release without decision_prompt_versions is checked as before, and is refused only when
    needs_decision is true."""
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
    if needs_decision and "decision_prompt_versions" not in manifest:
        raise RunError(f"{manifest_path}: field 'decision_prompt_versions' is missing; "
                       "decision models need a release cut after they were added")
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
    if "decision_prompt_versions" in manifest:
        plain, decision = both_prompt_versions(folder / "prompts", inputs)
    else:
        plain, decision = prompt_versions(folder / "prompts", inputs), None
    if plain != manifest["prompt_versions"]:
        raise RunError(f"{manifest_path}: field 'prompt_versions' differs from the prompts the working tree renders")
    if decision is not None and decision != manifest["decision_prompt_versions"]:
        raise RunError(
            f"{manifest_path}: field 'decision_prompt_versions' differs from the prompts the working tree renders")
    return manifest, inputs


def without_budget(data: bytes) -> dict:
    config = tomllib.loads(data.decode("utf-8"))
    config.pop("budget", None)
    return config


def check_experiment_copy(source: str, config_bytes: bytes, results: Path) -> None:
    """The stored copy must equal the config apart from [budget]."""
    copy = results / "experiment.toml"
    if copy.exists() and without_budget(copy.read_bytes()) != without_budget(config_bytes):
        raise RunError(f"{source}: differs from {copy}; an experiment never changes once it starts, except its [budget]")


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
                reply, retry_in: int, retry_out: int, decision: DecisionResult | None = None) -> dict:
    """Build the raw record of one attempt from the reply (None after an infrastructure failure).
    A decision model passes its DecisionResult instead, and the raw response is the array of its calls."""
    if decision is not None:
        text, stop, served = json.dumps(decision.calls), decision.stop_reason, decision.served_model
        tokens_in, tokens_out, latency = decision.input_tokens, decision.output_tokens, decision.latency_s
        retry_in, retry_out = decision.retry_input_tokens, decision.retry_output_tokens
        if not decision.calls and stop == "infrastructure_failure":
            text = ""
    elif reply is None:
        text, stop, served, tokens_in, tokens_out, latency = "", "infrastructure_failure", "", 0, 0, None
    else:
        text, stop, served = reply.text, reply.stop_reason, reply.served_model
        tokens_in, tokens_out, latency = reply.input_tokens, reply.output_tokens, reply.latency_s
    verdict = validate(row, text, stop, decision=decision is not None)
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
        "decision": decision is not None, "requested_model": model["api_model_id"],
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


def make_progress(config: dict, prices: dict, raw_dir: Path, pending: list, only_model: str | None, console=None) -> Progress:
    """Totals are the attempts already recorded plus those still to run, for the models of this process."""
    names = [m["name"] for m in config["models"] if only_model in (None, m["name"])]
    prior = [r for name in names for r in read_raw(raw_dir / f"{name}.jsonl")[0]]
    totals = Counter((r["model"], r["puzzle"]) for r in prior)
    totals.update((model["name"], row["puzzle"]) for row, model, _, _ in pending)
    return Progress(config, prices, totals, prior, console)


def run(args: argparse.Namespace) -> int:
    if args.config == "-":
        source, config_path = "<stdin>", None
        text = sys.stdin.read()
        config = parse_experiment_config(text, args.experiment, source)
        config_bytes = text.encode("utf-8")
    else:
        config_path = args.configs / f"{args.experiment}.toml"
        source = str(config_path)
        config = load_experiment_config(config_path)
        config_bytes = config_path.read_bytes()
    names = [m["name"] for m in config["models"]]
    if args.model and args.model not in names:
        raise RunError(f"{source}: field 'models' has no model {args.model!r}")
    folder = args.releases / config["release"]
    needs_decision = any(m["provider"] in DECISION_PROVIDERS for m in config["models"])
    manifest, inputs = load_release(folder, needs_decision)
    for name in config.get("puzzles", []):
        if name not in manifest["release_config"]["puzzles"]:
            raise RunError(f"{source}: field 'puzzles' names {name!r}, which release {config['release']} does not hold")
    results = args.results / config["experiment_id"]
    check_experiment_copy(source, config_bytes, results)
    prices = load_prices(args.prices)
    check_prices(config, prices, args.prices)
    pending = list(pending_attempts(config, inputs, results / "raw", args.model))
    if args.limit is not None:
        pending = pending[: args.limit]
    cap = max_moves(config, manifest["release_config"])
    questions = load_questions(folder / "prompts") if any(
        m["provider"] in DECISION_PROVIDERS for _, m, _, _ in pending) else None
    for row, model, setup, _ in pending:
        prompt = build_prompt(folder / "prompts", row, setup)
        if model["provider"] in DECISION_PROVIDERS:  # the longest request any call of the attempt sends
            prompt = worst_request(prompt, get_engine(row["puzzle"]).legal_moves(), cap, questions)
        check_request_budget(source, config, model, prompt, prices)
    if args.estimate:
        print_estimate(config, pending, prices, folder / "prompts", results / "raw", cap)
        return 0
    versions = manifest["prompt_versions"]
    branch = None
    if not (args.dry_run or args.no_commit):
        branch = ResultsBranch(config_path, results, config["experiment_id"])  # before any write or call
        branch.check_results([args.model] if args.model else names)
    if not args.dry_run:
        (results / "raw").mkdir(parents=True, exist_ok=True)
        copy = results / "experiment.toml"
        if not copy.exists() or copy.read_bytes() != config_bytes:
            temp = copy.with_name(f".experiment.toml.{os.getpid()}.tmp")  # atomic: models started together
            temp.write_bytes(config_bytes)  # never read half a file
            os.replace(temp, copy)  # first run, or only [budget] changed
    outcomes: Counter = Counter()
    progress = None if args.dry_run else make_progress(config, prices, results / "raw", pending, args.model)
    try:
        safe_commit(branch, f"Results: experiment {config['experiment_id']}, start")
        with progress or nullcontext():
            play(args, config, manifest, folder, results, prices, versions, pending, outcomes, branch, progress)
    finally:
        if branch:
            finish(branch, config["experiment_id"])
    if not args.dry_run:
        print(f"{sum(outcomes.values())} new attempts: " + ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items())))
    return 0


def safe_commit(branch: ResultsBranch | None, message: str) -> None:
    """Commit to the results branch. A failure warns and the run goes on, so a budget stop stays the last line."""
    if not branch:
        return
    try:
        branch.commit(message)
    except (BranchError, OSError) as error:
        print(f"warning: commit of {branch.branch} failed: {error}", file=sys.stderr)


def finish(branch: ResultsBranch, experiment_id: str) -> None:
    """Commit what is left and push the branch once. Warn, never fail, so the run's own error stays last."""
    safe_commit(branch, f"Results: experiment {experiment_id}, end")
    problem = branch.push()
    if problem:
        print(f"warning: push of results/{experiment_id} failed: {problem}", file=sys.stderr)
    branch.gc()


def play(args, config, manifest, folder, results, prices, versions, pending, outcomes, branch, progress) -> None:
    cap = max_moves(config, manifest["release_config"])
    questions = load_questions(folder / "prompts") if any(
        m["provider"] in DECISION_PROVIDERS for _, m, _, _ in pending) else None  # once per run
    for left, (row, model, setup, number) in zip(range(len(pending), 0, -1), pending):
        prompt = build_prompt(folder / "prompts", row, setup)
        is_decision = model["provider"] in DECISION_PROVIDERS
        legal = get_engine(row["puzzle"]).legal_moves() if is_decision else []
        if args.dry_run:
            print(f"--- {row['input_id']} {setup} {model['name']} attempt {number}")
            if is_decision:
                asked = decision_questions(questions, legal)
                print(f"{decision_state(prompt, [])}\n--- questions\n{json.dumps(asked, indent=2)}")
            else:
                print(prompt)
            continue
        price = prices[model["name"]]
        worst = worst_case_request_cost(worst_request(prompt, legal, cap, questions) if is_decision else prompt,
                                        config["max_output_tokens"], price)

        snapshot: dict = {}  # a decision attempt reads the spent cost once, before its first call

        def can_afford(retry_in: int, retry_out: int) -> None:
            paid = (retry_in * price["price_input_per_mtok"] + retry_out * price["price_output_per_mtok"]) / 1e6
            if is_decision and "spent" not in snapshot:
                snapshot["spent"] = spent_by_model(config, prices, results / "raw")
            check_spend(config, prices, results / "raw", model["name"], worst + paid, left,
                        snapshot.get("spent"))

        result = None
        if is_decision:
            result = run_decision_attempt(model, prompt, legal, questions,
                                          cap, config["retry_cap"], can_afford)
            reply, retry_in, retry_out, stop = None, result.retry_input_tokens, result.retry_output_tokens, result.budget_stop
        else:
            reply, retry_in, retry_out, stop = call_with_retries(model, prompt, config, can_afford)
        record = make_record(config, manifest, row, model, setup, number, prompt,
                             manifest["decision_prompt_versions"] if is_decision else versions,
                             reply, retry_in, retry_out, result)
        append_record(results / "raw" / f"{model['name']}.jsonl", record)
        outcomes[record["outcome"]] += 1
        progress.update(record)
        safe_commit(branch, f"Results: experiment {config['experiment_id']}, {model['name']} "
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
    parser.add_argument("--config", choices=["-"], help="read the experiment config from stdin")
    parser.add_argument("--configs", default="config/experiments", type=Path)
    parser.add_argument("--prices", default="config/prices.toml", type=Path)
    parser.add_argument("--results", default="results", type=Path)
    args = parser.parse_args(argv)

    def terminate(signum, frame):
        raise SystemExit(128 + signum)  # unwinds through run's finally, then exits non-zero

    try:
        previous = signal.signal(signal.SIGTERM, terminate)
    except ValueError:  # not the main thread
        previous = None
    try:
        return run(args)
    except (RunError, BudgetError, BranchError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
