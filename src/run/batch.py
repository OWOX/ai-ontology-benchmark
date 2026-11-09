# Spec: docs/specs/run.md
"""Batch mode of `run`: submits the attempts of batched AI models to the provider's Message Batches API,
tracks the open batches, collects their results, and appends one raw record per attempt. Reads the
state files results/<ID>/batches/<model name>.jsonl and the raw files, and calls the batch functions of
src/run/models.py. Appends to the state files and the raw files, never rewrites a line. Every batch line
carries build_request(), the body a direct call sends, and results are matched by custom_id only.
"""

import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import re
import signal
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.puzzles.registry import get_engine
from src.run.branch import BranchError
from src.run.budget import (TOLERANCE, BudgetError, batch_state_path, held_by_model, is_batched, open_batches,
                            read_state, spent_by_model, unresolved_submits, worst_case_request_cost)
from src.run.models import (BatchRejectedError, BatchTooLargeError, InfrastructureError, RequestError, UnreadableReply, batch_done, batch_results, build_request,
                            submit_batch)
from src.run.raw import parse_raw_text
from src.run.run import RunError, append_record, make_record, read_done, safe_commit
from src.validator import offered_reasons

POLL_S = 60  # seconds between two checks of the open batches; tests patch it

# Per chunk: (requests, bytes). The fake provider's limit is tiny so that tests exercise chunking.
LIMITS = {"anthropic": (10000, 200_000_000), "openai": (10000, 150_000_000),
          "google": (2000, 15_000_000), "fake": (3, 15_000_000)}
CUSTOM_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def custom_id(input_id: str, setup: str, number: int, retry: int) -> str:
    """The id that ties a batch line to its attempt: `<input id>_<setup>_a<attempt number>_r<retry index>`."""
    value = f"{input_id}_{setup}_a{number}_r{retry}"
    if not CUSTOM_ID.match(value):
        raise ValueError(f"custom id {value!r} has characters or a length a batch API refuses")
    return value


def submission_counts(events: list[dict]) -> dict[tuple, int]:
    """How many times each attempt (input id, setup, attempt number) has been submitted. A submission
    that ended in a RequestError (listed in its `collected` event) does not count toward the retry cap."""
    rejected = {e["batch_id"]: set(e.get("request_errors", ())) for e in events if e.get("event") == "collected"}
    counts: dict[tuple, int] = {}
    for event in events:
        if event.get("event") == "submitted":
            for item in event["requests"]:
                if item["custom_id"] in rejected.get(event["batch_id"], ()):
                    continue
                key = (item["input_id"], item["setup"], item["attempt_number"])
                counts[key] = counts.get(key, 0) + 1
    return counts


def in_flight_keys(events: list[dict]) -> set[tuple]:
    """The attempts (input id, setup, attempt number) of the unresolved submits: they may be in a batch at the
    provider, so none goes into a new chunk, whatever its retry index."""
    return {(item["input_id"], item["setup"], item["attempt_number"])
            for event in unresolved_submits(events) for item in event["requests"]}


class ModelBatches:
    """The batch work of one AI model: its state file, its attempts still to run, and its batch limits."""

    def __init__(self, model: dict, attempts: list[tuple], state_path: Path) -> None:
        self.model, self.attempts, self.path = model, attempts, state_path
        self.name = model["name"]
        self.failures = 0  # consecutive transient errors talking to the provider
        self.blocked: BudgetError | None = None
        self.max_requests = LIMITS[model["provider"]][0]  # halved when the provider refuses a chunk as too large


def play_batched(*, config, manifest, results, prices, versions, pending, outcomes, branch, progress,
                 with_reasons, rows, prompt_for, only_model=None) -> None:
    """Run every attempt in `pending` (all of them for batched AI models) through batches.

    `rows` maps an input id to its input, and `prompt_for(input_id, setup)` returns the rendered prompt.
    The models advance round-robin, so their batches run at the same time: a model with an open batch
    is checked each poll, a model without one submits the next chunk. A chunk is as large as the
    provider limits and the budgets allow. A failed request goes into a later chunk until the retry
    cap, then gets an `infrastructure_failure` record; a reply the provider billed but run can't read gets
    that record at once, with its tokens, and is never resent. A rejection of a whole batch (BatchRejectedError)
    closes the batch before the run stops; any other RequestError leaves it open and held. A RequestError
    on a single request stops the run after its batch has been collected and committed. Interrupts leave
    open batches open."""
    work: dict[str, ModelBatches] = {}
    for model in config["models"]:  # config order; a model with an open batch is collected even with nothing pending
        if is_batched(config, model) and only_model in (None, model["name"]):
            if model["name"] in {m["name"] for _, m, _, _ in pending} or open_batches(
                    read_state(batch_state_path(results, model["name"]))):
                work[model["name"]] = ModelBatches(model, [], batch_state_path(results, model["name"]))
    for row, model, setup, number in pending:
        work[model["name"]].attempts.append((row, setup, number))
    context = dict(config=config, manifest=manifest, results=results, prices=prices, versions=versions,
                   outcomes=outcomes, branch=branch, progress=progress, rows=rows, prompt_for=prompt_for,
                   with_reasons=with_reasons, work=work, push_outstanding=False)
    finished: set[str] = set()
    while True:
        retry_push(context)
        moved = False
        for name, state in work.items():
            if name not in finished and state.blocked is None:
                done, progressed = step(state, context)
                moved = moved or progressed
                if done:
                    finished.add(name)
        if all(n in finished or s.blocked is not None for n, s in work.items()):
            break
        if not moved:
            time.sleep(POLL_S)
    blocked = [s.blocked for s in work.values() if s.blocked is not None]
    if blocked:
        raise blocked[0]


def worst(config: dict, price: dict, prompt: str) -> float:
    return worst_case_request_cost(prompt, config["max_output_tokens"], price, True)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def transient(state: ModelBatches, config: dict, error: Exception, what: str) -> None:
    """Count a provider error that may pass, to try again at the next poll. Raise RequestError past the retry cap."""
    state.failures += 1
    log(f"infrastructure error: {state.name} {what} try {state.failures}: {' '.join(str(error).split())[:200]}")
    if state.failures > config["retry_cap"]:
        raise RequestError(f"{state.name}: {what} failed {state.failures} times in a row: {error}") from error


def step(state: ModelBatches, context: dict) -> tuple[bool, bool]:
    """Advance one model by one action. Return (model finished, something happened)."""
    config = context["config"]
    try:
        events = read_state(state.path)
        is_open = open_batches(events)
        if is_open:
            batch = is_open[0]
            try:
                finished = batch_done(state.model, batch["batch_id"])
            except RequestError as error:  # 401, 403 or 404 may only mean a wrong or rotated key: the batch stays open
                raise stop_open(state, context, batch, error, "can't be checked") from error
            if not finished:
                state.failures = 0
                return False, False
            collect(state, context, batch, events)
            state.failures = 0
            return False, True
        with experiment_lock(context):  # from the first read of the state until the `submitted` line is appended
            events = read_state(state.path)  # read again under the lock: another process may have submitted
            if open_batches(events):
                return False, False
            unresolved = unresolved_submits(events)
            if unresolved:  # under the lock, so a send in progress in another process is not mistaken for one
                raise unresolved_error(state, context, unresolved)
            settle_exhausted(state, context, events)
            remaining = remaining_attempts(state, context, events)
            if not remaining:
                return True, False
            chunk = size_chunk(state, context, remaining, events)
            if not chunk:
                others = [m["name"] for m in config["models"] if m["name"] not in context["work"]
                          and open_batches(read_state(batch_state_path(context["results"], m["name"])))]
                if any(open_batches(read_state(batch_state_path(context["results"], n)))
                       for n in context["work"] if n != state.name):
                    return False, False  # a batch this process collects is open: wait, then look again
                state.blocked = budget_stop(state, context, remaining, others)
                return False, True
            submit(state, context, chunk)
        state.failures = 0
        return False, True
    except InfrastructureError as error:
        transient(state, config, error, "batch call")
        return False, False


@contextlib.contextmanager
def experiment_lock(context: dict):
    """An exclusive lock on the whole experiment, shared by every process that runs it. It sits in the git
    common dir with the branch lock; a run without a branch keeps it in the system temporary folder."""
    branch = context["branch"]
    if branch:
        path = branch.batch_lock_path
    else:
        key = hashlib.sha256(str(Path(context["results"]).resolve()).encode()).hexdigest()[:16]
        path = Path(tempfile.gettempdir()) / f"results-{context['config']['experiment_id']}-{key}.batch.lock"
    with open(path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def done_keys(context: dict, state: ModelBatches) -> set:
    return read_done(context["results"] / "raw" / f"{state.name}.jsonl")


def remaining_attempts(state: ModelBatches, context: dict, events: list[dict]) -> list[tuple]:
    """(row, setup, number, retry index) for each pending attempt of the model with no record yet."""
    done = done_keys(context, state)
    counts = submission_counts(events)
    flying = in_flight_keys(events)
    return [(row, setup, number, counts.get((row["input_id"], setup, number), 0))
            for row, setup, number in state.attempts
            if (row["input_id"], setup, state.name, number) not in done
            and (row["input_id"], setup, number) not in flying]


def settle_exhausted(state: ModelBatches, context: dict, events: list[dict]) -> None:
    """Record infrastructure_failure for an attempt submitted retry_cap + 1 times with no record (a crash left it)."""
    cap = context["config"]["retry_cap"]
    for row, setup, number, submitted in remaining_attempts(state, context, events):
        if submitted >= cap + 1:
            write_record(state, context, row, setup, number, None)


def write_record(state: ModelBatches, context: dict, row: dict, setup: str, number: int, reply,
                 paid: tuple[int, int] = (0, 0)) -> dict:
    """Append one raw record (reply None: infrastructure failure), count it, and show it. `paid` are the
    tokens of a billed reply that couldn't be read, stored as retry tokens so that cost counts them."""
    config, model = context["config"], state.model
    if reply is not None:
        reply = dataclasses.replace(reply, latency_s=None)  # a batch has no latency of its own
    reasons = offered_reasons(get_engine(row["puzzle"])) if context["with_reasons"] else None
    record = make_record(config, context["manifest"], row, model, setup, number,
                                    context["versions"], reply, paid[0], paid[1], None, reasons, batch=True)
    append_record(context["results"] / "raw" / f"{state.name}.jsonl", record)
    context["outcomes"][record["outcome"]] += 1
    context["progress"].update(record)
    return record


def line_size(cid: str, body: dict) -> int:
    """The UTF-8 bytes of one batch line, with a margin for each provider's own wrapper."""
    return len(json.dumps({"custom_id": cid, "params": body}).encode("utf-8")) + 200


def size_chunk(state: ModelBatches, context: dict, remaining: list[tuple], events: list[dict]) -> list[tuple]:
    """The first attempts of `remaining`, in order, that fit the provider limits and both budgets
    together with the open batches. Stops at the first that does not fit."""
    config, name = context["config"], state.name
    max_bytes = LIMITS[state.model["provider"]][1]
    max_requests = state.max_requests
    spent = spent_by_model(config, context["prices"], context["results"] / "raw")
    held = held_by_model(config, context["prices"], context["results"], context["prompt_for"])
    budget = config["budget"]
    model_total = spent[name] + held[name]
    experiment_total = sum(spent.values()) + sum(held.values())
    chunk, size = [], 0
    for row, setup, number, retry in remaining:
        prompt = context["prompt_for"](row["input_id"], setup)
        body = build_request(state.model, prompt, config["max_output_tokens"], config.get("reasoning_effort"))
        cost = worst(config, context["prices"][name], prompt)
        cid = custom_id(row["input_id"], setup, number, retry)
        length = line_size(cid, body)
        if length > max_bytes:
            raise RunError(f"{name} {cid}: request larger than the {state.model['provider']} batch limit")
        if (len(chunk) >= max_requests or size + length > max_bytes
                or model_total + cost > budget["per_model_usd"] + TOLERANCE
                or experiment_total + cost > budget["per_experiment_usd"] + TOLERANCE):
            break
        chunk.append((row, setup, number, retry, body))
        model_total += cost
        experiment_total += cost
        size += length
    return chunk


def budget_stop(state: ModelBatches, context: dict, remaining: list[tuple], others: list[str]) -> BudgetError:
    """The BudgetError for a model whose next request fits no budget while no batch this process collects
    is open. `others` are models outside this run (--model) whose open batches hold part of the budget."""
    config, name = context["config"], state.name
    spent = spent_by_model(config, context["prices"], context["results"] / "raw")
    row, setup, _, _ = remaining[0]
    cost = worst(config, context["prices"][name], context["prompt_for"](row["input_id"], setup))
    budget = config["budget"]
    left = len(remaining)
    if others:
        return BudgetError(f"budget reached: spent plus the open batches of {', '.join(others)} exceed "
                           f"per_experiment_usd {budget['per_experiment_usd']}; run without --model to collect them", left)
    if spent[name] + cost > budget["per_model_usd"] + TOLERANCE:
        return BudgetError(f"budget reached: per_model_usd {budget['per_model_usd']} for model {name} "
                           f"(spent {spent[name]:.4f}, next request up to {cost:.4f})", left)
    return BudgetError(f"budget reached: per_experiment_usd {budget['per_experiment_usd']} "
                       f"(spent {sum(spent.values()):.4f}, next request up to {cost:.4f})", left)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def deferred_signals():
    """Hold SIGINT and SIGTERM until the block ends, then restore the handlers and deliver the signal again.
    Outside the main thread nothing is deferred."""
    caught: list[int] = []
    old = {}
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            old[number] = signal.signal(number, lambda signum, frame: caught.append(signum))
    except ValueError:
        old = {}
    try:
        yield
    finally:
        for number, handler in old.items():
            signal.signal(number, handler)
        if caught:
            signal.raise_signal(caught[0])


def unresolved_error(state: ModelBatches, context: dict, unresolved: list[dict]) -> RequestError:
    """The RequestError that stops a model with a send that may have made a batch no state line names."""
    event = unresolved[0]
    experiment = context["config"]["experiment_id"]
    return RequestError(
        f"{state.name}: submit {event['submit_id']} of {len(event['requests'])} requests, started at "
        f"{event['created_at']}, has no result: the provider may have created a batch that no state line names, "
        f"and its cost is held; check the provider console for a batch created at that time, cancel it if it "
        f"exists or wait for it, then run --experiment {experiment} --resolve-submit {event['submit_id']} "
        "--as abandoned")


def abandon(state_path: Path, submit_id: str) -> None:
    """Append `abandoned` for a submit: it holds nothing, and its attempts are pending again."""
    append_record(state_path, {"event": "abandoned", "submit_id": submit_id, "created_at": now()})


def resolve_submit(args) -> int:
    """`run --resolve-submit <submit id> --as abandoned`: append `abandoned` for the unresolved submit, commit,
    and push. It reads no config and calls no provider."""
    from src.run.branch import ResultsBranch

    results = args.results / args.experiment
    config_path = args.configs / f"{args.experiment}.toml"
    branch = None if args.no_commit else ResultsBranch(config_path if config_path.is_file() else None, results,
                                                       args.experiment)
    context = {"branch": branch, "results": results, "config": {"experiment_id": args.experiment}}
    with experiment_lock(context):
        for path in sorted((results / "batches").glob("*.jsonl")):
            if any(e["submit_id"] == args.resolve_submit for e in unresolved_submits(read_state(path))):
                break
        else:
            raise RunError(f"{results / 'batches'}: no unresolved submit {args.resolve_submit!r}")
        abandon(path, args.resolve_submit)
    print(f"{path.stem}: submit {args.resolve_submit} abandoned; its attempts are pending again", file=sys.stderr)
    if branch:
        safe_commit(branch, f"Results: experiment {args.experiment}, {path.stem} submit {args.resolve_submit} abandoned")
        problem = branch.push()
        if problem and problem != "no remote origin":
            print(f"warning: push of results/{args.experiment} failed: {problem}", file=sys.stderr)
    return 0


def submit(state: ModelBatches, context: dict, chunk: list[tuple]) -> None:
    """Write and commit a `submitting` line, send the chunk as one batch, then write and commit a `submitted`
    line before anything waits, and push. A send that fails, or is interrupted, with no `submitted` line leaves
    the `submitting` line unresolved, and its worst-case cost stays held, because the provider may have made
    the batch: `run` stops for the model until `--resolve-submit` abandons it. Only an error before the
    provider could have made a batch (a RequestError or ValueError) abandons it here. A signal that arrives
    from the send to the commit waits until the commit is done, so the batch is never paid for without a
    record of it. A failed commit stops the run: before the send it abandons the submit, and after it a push
    without the state file would let another machine submit the same requests."""
    lines = [(custom_id(row["input_id"], setup, number, retry), body) for row, setup, number, retry, body in chunk]
    experiment = context["config"]["experiment_id"]
    worst_usd = sum(worst(context["config"], context["prices"][state.name], context["prompt_for"](row["input_id"], setup))
                    for row, setup, _, _, _ in chunk)
    requests = [{"custom_id": cid, "input_id": row["input_id"], "setup": setup, "attempt_number": number,
                 "retry": retry} for cid, (row, setup, number, retry, _) in zip((c for c, _ in lines), chunk)]
    submit_id, started = uuid.uuid4().hex, now()
    state.path.parent.mkdir(parents=True, exist_ok=True)
    with deferred_signals():
        append_record(state.path, {"event": "submitting", "submit_id": submit_id, "provider": state.model["provider"],
                                   "created_at": started, "worst_usd": worst_usd, "requests": requests})
        if context["branch"]:
            try:
                context["branch"].commit(f"Results: experiment {experiment}, {state.name} submit {submit_id} started")
            except (BranchError, OSError) as error:
                abandon(state.path, submit_id)  # nothing was sent
                message = f"{state.name}: committing the state file before a batch submit failed: {error}; nothing was sent"
                log(message)
                raise RunError(message) from error
        context["push_outstanding"] = True  # best effort: another machine sees the held amount before the send
        retry_push(context)
        try:
            batch_id = submit_batch(state.model, lines)
        except (RequestError, ValueError):  # refused before any batch could exist
            abandon(state.path, submit_id)
            raise
        except InfrastructureError as error:
            message = (f"{state.name}: the batch submit failed after sending ({' '.join(str(error).split())[:200]}); "
                       f"the provider may have created the batch, so check its console before running again for a "
                       f"batch created at {started}; submit {submit_id} of {len(chunk)} requests stays unresolved "
                       f"and held until you run --experiment {experiment} --resolve-submit {submit_id} --as abandoned")
            log(message)  # a signal held until the block ends would otherwise hide it
            raise RequestError(message) from error
        append_record(state.path, {
            "event": "submitted", "batch_id": batch_id, "submit_id": submit_id, "provider": state.model["provider"],
            "created_at": now(), "worst_usd": worst_usd, "requests": requests})
        log(f"batch {state.name} {batch_id}: submitted {len(chunk)} requests")
        if context["branch"]:
            try:
                context["branch"].commit(f"Results: experiment {experiment}, {state.name} batch {batch_id} submitted")
            except (BranchError, OSError) as error:
                message = (f"{state.name}: batch {batch_id} is open at the provider, but committing its state file "
                           f"failed: {error}; stopping, because another machine could submit the same requests; "
                           f"fix the branch, then run again to collect it")
                log(message)
                raise RunError(message) from error
    context["push_outstanding"] = True  # a fresh clone sees the open batch even if this machine dies
    retry_push(context)


def retry_push(context: dict) -> None:
    """Push the results branch while a push is outstanding, and clear the flag once it succeeds. A failure
    only warns, and the push is tried again at the next poll and after the next collect commit."""
    branch = context["branch"]
    if branch and context["push_outstanding"]:
        problem = branch.push()
        if problem:
            print(f"warning: push of results/{context['config']['experiment_id']} failed: {problem}", file=sys.stderr)
        if not problem or problem == "no remote origin":  # with no remote there is nothing to retry
            context["push_outstanding"] = False


def collect(state: ModelBatches, context: dict, batch: dict, events: list[dict]) -> None:
    """Read a finished batch, append a record for every request that has an answer or ran out of
    retries, append `collected`, and commit. Only custom ids this batch holds are read."""
    config, batch_id = context["config"], batch["batch_id"]

    every = [item["custom_id"] for item in batch["requests"]]
    try:
        answers = batch_results(state.model, batch_id)
    except BatchTooLargeError as error:  # the queue was full: nothing is spent, and no retry is used
        close_batch(state, context, batch, every)
        if len(every) == 1:
            raise RequestError(f"{state.name}: the provider refuses even one request: {error}") from error
        state.max_requests = max(1, min(state.max_requests, len(every)) // 2)
        log(f"batch {state.name} {batch_id}: refused as too large, sending chunks of up to {state.max_requests} requests")
        return
    except BatchRejectedError:  # the provider's verdict: nothing was billed, so a restart must not read it again
        close_batch(state, context, batch, every)
        raise
    except RequestError as error:  # the batch may be live and billed: leave it open, held, and stop
        raise stop_open(state, context, batch, error, "can't be read") from error
    done = done_keys(context, state)
    counts = submission_counts(events)
    succeeded = retrying = failed = 0
    stop, rejected = None, []
    for item in batch["requests"]:
        key = (item["input_id"], item["setup"], item["attempt_number"])
        if (key[0], key[1], state.name, key[2]) in done:
            continue  # recorded before a crash
        row = context["rows"][item["input_id"]]
        answer = answers.get(item["custom_id"])
        if isinstance(answer, RequestError):
            stop = stop or answer
            rejected.append(item["custom_id"])
        elif isinstance(answer, UnreadableReply):  # billed, so never resent
            log(f"batch {state.name} {item['custom_id']}: {answer.message}")
            write_record(state, context, row, item["setup"], item["attempt_number"], None,
                         (answer.input_tokens, answer.output_tokens))
            failed += 1
        elif answer is None or isinstance(answer, InfrastructureError):
            if counts[key] >= config["retry_cap"] + 1:
                write_record(state, context, row, item["setup"], item["attempt_number"], None)
                failed += 1
            else:
                retrying += 1
        else:
            write_record(state, context, row, item["setup"], item["attempt_number"], answer)
            succeeded += 1
    close_batch(state, context, batch, rejected)
    log(f"batch {state.name} {batch_id}: collected {succeeded} succeeded, {retrying} to retry, {failed} failed")
    if stop:
        raise stop


def stop_open(state: ModelBatches, context: dict, batch: dict, error: Exception, what: str) -> RequestError:
    """Push the branch and return the RequestError that stops the run with the batch left open, so its
    worst_usd stays held and nothing is sent again."""
    context["push_outstanding"] = True
    retry_push(context)
    return RequestError(f"{state.name}: batch {batch['batch_id']} {what} ({' '.join(str(error).split())[:200]}); "
                        "it stays open and may still be billed, so check the provider console before running again; "
                        "the next run checks it again")


def close_batch(state: ModelBatches, context: dict, batch: dict, rejected: list[str]) -> None:
    """Append `collected` for the batch, commit, and push if a push is outstanding. The custom ids in
    `rejected` don't count toward the retry cap."""
    event = {"event": "collected", "batch_id": batch["batch_id"], "created_at": now()}
    if rejected:
        event["request_errors"] = rejected
    append_record(state.path, event)
    safe_commit(context["branch"], f"Results: experiment {context['config']['experiment_id']}, "
                                   f"{state.name} batch {batch['batch_id']} collected")
    retry_push(context)
