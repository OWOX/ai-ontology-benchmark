# Spec: docs/specs/evaluate.md
"""Metric maths for evaluate: re-validates raw records against the release inputs and groups
the attempts. Reads the release's inputs.jsonl and writes nothing. It is part of the assessment.
"""

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import combinations
from operator import itemgetter
from pathlib import Path

from src.puzzles.cube import CUBE_CORRUPTION_TYPES
from src.puzzles.registry import ENGINES
from src.run.prompts import SETUPS
from src.run.raw import is_decision_record
from src.validator import offered_reasons, validate

NA = "n/a"
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = "bootstrap-v1"
PAIRED_METRICS = ("precision", "hallucination_rate", "mismatch_detection_rate", "diagnosis_rate")
ALPHA = 0.05
PAIRED_COLUMNS = (
    "model", "puzzle", "validity", "metric", "setup_a", "setup_b", "inputs_paired", "a_higher",
    "b_higher", "mean_difference", "p_value", "p_holm", "significant")
KEY = ("puzzle", "setup", "model", "scramble_depth", "validity")
PUZZLE_ORDER = list(ENGINES)  # the report sort order of puzzles


class EvalError(Exception):
    """A checked error. The message names the file or field at fault."""


def mean(values: list) -> object:
    return sum(values) / len(values) if values else NA


def bootstrap_rng(key: str) -> random.Random:
    """A generator seeded from the key alone, so the result never depends on group order."""
    digest = hashlib.sha256(f"{BOOTSTRAP_SEED}|{key}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest, "big"))


def percentiles(draws: list[float]) -> tuple:
    """Nearest-rank 2.5th and 97.5th percentiles of the draw rates."""
    draws = sorted(draws)
    return draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]


def bootstrap_interval(cells: list[tuple[int, int]], key: str) -> tuple:
    """Return (rate, low, high) for one rate. `cells` holds one (hits, attempts) pair per input, in a
    stable order. Inputs are drawn with replacement, keeping all their attempts."""
    hits = sum(h for h, _ in cells)
    attempts = sum(a for _, a in cells)
    if attempts == 0:
        return NA, NA, NA
    rate = hits / attempts
    if len(cells) < 2:
        return rate, NA, NA
    if hits == 0 or hits == attempts:
        return rate, rate, rate  # every draw gives the same rate
    rng = bootstrap_rng(key)
    count = len(cells)
    draws = []
    for _ in range(BOOTSTRAP_DRAWS):
        picked = [cells[i] for i in rng.choices(range(count), k=count)]
        total = sum(a for _, a in picked)
        draws.append(sum(h for h, _ in picked) / total if total else 0.0)
    low, high = percentiles(draws)
    return rate, low, high


def input_cells(rows: list[dict], hit) -> list[tuple[int, int]]:
    """One (hits, attempts) pair per input, sorted by input id."""
    per_input = defaultdict(lambda: [0, 0])
    for r in rows:
        cell = per_input[r["input_id"]]
        cell[0] += bool(hit(r))
        cell[1] += 1
    return [tuple(per_input[i]) for i in sorted(per_input)]


def rate_columns(row: dict, name: str, cells: list[tuple[int, int]], key: str) -> None:
    row[name], row[name + "_low"], row[name + "_high"] = bootstrap_interval(cells, f"{key}|{name}")
    row[name + "_n"] = sum(a for _, a in cells)
    row[name + "_inputs"] = len(cells)


def gave_moves(row: dict) -> bool:
    """True when the attempt returned at least one parsed move: the denominator of the hallucination rate."""
    return bool(row.get("parsed_moves"))


def answer_class(row: dict) -> str | None:
    """The class of a classified answer: `tp`, `fp`, `tn`, or `fn`, or None for an attempt that is
    not one (abstention, format error, truncated, malformed output, infrastructure failure). An
    attempt claims the puzzle can't be solved when its mismatch flag is on or it has no parsed
    moves, and claims a solution otherwise. Reads `outcome`, `mismatch`, `parsed_moves`,
    `mismatch_reason`, `reasons`, and the input's `corruption`."""
    outcome = row["outcome"]
    if outcome not in ("success", "failure", "hallucination"):
        return None
    flagged = bool(row.get("mismatch"))
    if not flagged and gave_moves(row):
        return "tp" if outcome == "success" else "fp"
    corruption = row.get("corruption")
    if flagged and corruption and (not row.get("reasons") or row.get("mismatch_reason") == corruption_type(corruption)):
        return "tn"
    return "fn"


def has_reasons(rows: list[dict]) -> bool:
    """True when the rows come from a release with mismatch reasons."""
    return bool(rows) and all(r["reasons"] for r in rows)


def is_diagnosis(row: dict) -> bool:
    """A flagged answer whose mismatch reason is the input's corruption type."""
    corruption = row.get("corruption")
    return bool(row["mismatch"] and corruption and row.get("mismatch_reason") == corruption_type(corruption))


def is_hit(row: dict, metric: str) -> bool:
    if metric == "mismatch_detection_rate":
        return bool(row["mismatch"])
    if metric == "hallucination_rate":
        return bool(row["impossible_move"])
    if metric == "precision":
        return row["answer_class"] in ("tp", "tn")
    if metric == "diagnosis_rate":
        return is_diagnosis(row)
    return row["outcome"] == metric.removesuffix("_rate")


def rates(rows: list[dict], validity: str, key: str) -> dict:
    """Rates over the attempts that are not infrastructure failures (`rows` holds only those).
    `key` names the group, and seeds each rate's bootstrap."""
    out: dict = {}

    def add(name: str, hit, use_rows: list | None = None) -> None:
        use = rows if use_rows is None else use_rows
        rate_columns(out, name, input_cells(use, hit), key)

    def outcome_is(outcome: str):
        return lambda r: r["outcome"] == outcome

    reasons = has_reasons(rows)
    add("precision", lambda r: is_hit(r, "precision"), [r for r in rows if r["answer_class"]])
    add("coverage", lambda r: r["answer_class"] is not None)
    # a decision model can't return an impossible move
    decision = bool(rows) and all(r["decision"] for r in rows)
    add("hallucination_rate", lambda r: r["impossible_move"], [] if decision else [r for r in rows if gave_moves(r)])
    flagged = lambda r: r["mismatch"]
    add("mismatch_detection_rate", flagged, rows if validity == "invalid" else [])
    add("false_mismatch_rate", flagged, [] if validity == "invalid" else rows)
    add("malformed_output_rate", outcome_is("malformed_output"))
    add("truncated_rate", outcome_is("truncated"))
    add("abstention_rate", outcome_is("abstention"))
    add("format_error_rate", outcome_is("format_error"))
    add("reason_hallucination_rate", lambda r: r["decoy"],
        [r for r in rows if r["mismatch_reason"] is not None] if reasons else [])
    add("diagnosis_rate", is_diagnosis, rows if reasons and validity == "invalid" else [])
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


def group_metrics(rows: list[dict], validity: str, full: bool, key: str) -> dict:
    """Metrics for one group of attempt rows. `full` adds the columns the summary leaves out."""
    done = [r for r in rows if r["outcome"] != "infrastructure_failure"]
    out = {"attempts": len(rows), "infrastructure_failure_count": len(rows) - len(done)}
    out.update(rates(done, validity, key))
    out["cost_per_attempt"] = mean([r["cost"] for r in rows])
    if full:
        out["consistency"] = consistency(done)
        latencies = [r["latency_s"] for r in done if r["latency_s"] is not None]
        out["latency_per_attempt_s"] = mean(latencies)
        in_tokens = [r["input_tokens"] + r["retry_input_tokens"] for r in rows]
        out_tokens = [r["output_tokens"] + r["retry_output_tokens"] for r in rows]
        out["input_tokens_per_attempt"] = mean(in_tokens)
        out["output_tokens_per_attempt"] = mean(out_tokens)
    return out


def attempt_cost(raw: dict, price: dict) -> float:
    input_tokens = raw["input_tokens"] + raw["retry_input_tokens"]
    output_tokens = raw["output_tokens"] + raw["retry_output_tokens"]
    return (input_tokens * price["price_input_per_mtok"]
            + output_tokens * price["price_output_per_mtok"]) / 1e6


def make_attempt_row(raw: dict, line: int, source: dict, verdict, cost: float,
                     decision: bool = False, reasons: bool = False) -> dict:
    row = {
        "input_id": raw["input_id"], "input_line": line, "puzzle": source["puzzle"],
        "scramble_depth": source["scramble_depth"], "validity": source["validity"],
        "setup": raw["setup"], "model": raw["model"], "attempt_number": raw["attempt_number"],
        "stored_outcome": raw["outcome"], "outcome": verdict.outcome,
        "parsed_moves": verdict.parsed_moves, "mismatch": verdict.mismatch,
        "move_count": verdict.move_count,
        "input_tokens": raw["input_tokens"], "output_tokens": raw["output_tokens"],
        "retry_input_tokens": raw["retry_input_tokens"],
        "retry_output_tokens": raw["retry_output_tokens"], "latency_s": raw["latency_s"],
        "served_model": raw["served_model"], "created_at": raw["created_at"], "cost": cost,
        "decision": decision, "corruption": source.get("corruption"), "reasons": reasons,
        "impossible_move": verdict.impossible_move, "mismatch_reason": verdict.mismatch_reason,
        "decoy": verdict.decoy,
    }
    row["answer_class"] = answer_class(row)
    return row


def make_attempt_rows(raw_records, inputs, prices, decision_models=frozenset(), reasons: bool = False) -> list[dict]:
    by_id = {row["input_id"]: (number, row) for number, row in enumerate(inputs, start=1)}
    rows = []
    for raw in raw_records:
        if raw["input_id"] not in by_id:
            raise EvalError(
                f"raw record {raw['input_id']!r}: field 'input_id' is not in inputs.jsonl")
        if raw["model"] not in prices:
            raise EvalError(f"prices: no prices for model {raw['model']!r}")
        line, source = by_id[raw["input_id"]]
        decision = is_decision_record(raw, decision_models)
        offered = offered_reasons(ENGINES[source["puzzle"]]) if reasons else None
        verdict = validate(source, raw["raw_response"], raw["stop_reason"], decision=decision, reasons=offered)
        cost = attempt_cost(raw, prices[raw["model"]])
        rows.append(make_attempt_row(raw, line, source, verdict, cost, decision, reasons))
    return rows


def model_order(rows: list[dict], models: list[str] | None) -> list[str]:
    """The AI model sort order: config order when given, else the names found in `rows`."""
    return models or sorted({r["model"] for r in rows})


def model_rank(order: list[str], name: str) -> tuple:
    return (order.index(name) if name in order else len(order), name)


def attempt_sort_key(row: dict, order: list[str]) -> tuple:
    return (row["input_line"], model_rank(order, row["model"]),
            SETUPS.index(row["setup"]), row["attempt_number"])


def metric_sort_key(key: tuple, order: list[str]) -> tuple:
    """Key is (puzzle, setup, model, depth, validity)."""
    puzzle, setup, model, depth, validity = key
    return (PUZZLE_ORDER.index(puzzle), SETUPS.index(setup), model_rank(order, model),
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
    manifest = json.loads((Path(release_dir) / "manifest.json").read_text(encoding="utf-8"))
    rows = make_attempt_rows(raw_records, inputs, prices, decision_models,
                             bool(manifest.get("mismatch_reasons", False)))
    order = model_order(rows, models)
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
        row.update(group_metrics(groups[key], key[4], True, "|".join(map(str, key))))
        metric_rows.append(row)
    summary_rows = []
    for key in sorted_keys(pooled, summary_sort_key, order):
        row = dict(zip(("model", "setup", "validity"), key))
        row.update(group_metrics(pooled[key], key[2], False, "summary|" + "|".join(key)))
        summary_rows.append(row)
    return rows, metric_rows, summary_rows


def sign_test(a: int, b: int) -> float:
    """Exact two-sided sign test on `a` against `b` discordant inputs. 1.0 when there are none."""
    n = a + b
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(a, b) + 1))
    return min(1.0, 2 * tail / 2 ** n)


def holm(p_values: list[float]) -> list[float]:
    """Holm-adjusted p-values, in the order given."""
    m = len(p_values)
    adjusted, running = [0.0] * m, 0.0
    for rank, index in enumerate(sorted(range(m), key=lambda i: p_values[i])):
        running = max(running, min(1.0, (m - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def input_shares(rows: list[dict], metric: str) -> dict:
    """Share of hits per (input, setup), leaving out infrastructure failures. Precision also leaves out
    attempts that are not classified answers, and the hallucination rate those that gave no moves, so an
    (input, setup) with none has no share."""
    counts = defaultdict(lambda: [0, 0])
    for r in rows:
        if (r["outcome"] == "infrastructure_failure"
                or (metric == "hallucination_rate" and not gave_moves(r))
                or (metric == "precision" and r["answer_class"] is None)):
            continue
        cell = counts[(r["input_id"], r["setup"])]
        cell[0] += is_hit(r, metric)
        cell[1] += 1
    return {key: Fraction(hits, n) for key, (hits, n) in counts.items()}


def compare_setups(shares: dict, setup_a: str, setup_b: str) -> dict:
    """Return the pair's counts, mean difference and p-value over the inputs paired."""
    inputs = sorted({i for i, s in shares if s == setup_a} & {i for i, s in shares if s == setup_b})
    diffs = [shares[(i, setup_b)] - shares[(i, setup_a)] for i in inputs]
    a_higher, b_higher = sum(d < 0 for d in diffs), sum(d > 0 for d in diffs)
    return {"inputs_paired": len(inputs), "a_higher": a_higher, "b_higher": b_higher,
            "mean_difference": float(sum(diffs) / len(diffs)) if diffs else NA,
            "p_value": sign_test(a_higher, b_higher) if diffs else NA}


def paired_tests(attempt_rows: list[dict], models: list[str] | None = None) -> list[dict]:
    """Return the paired setup test rows, pooled over scramble depths and never over validity."""
    order = model_order(attempt_rows, models)
    groups = defaultdict(list)
    for r in attempt_rows:
        groups[(r["model"], r["puzzle"], r["validity"])].append(r)
    keys = sorted(groups, key=lambda k: (model_rank(order, k[0]), PUZZLE_ORDER.index(k[1]),
                                         k[2] != "valid"))
    pairs = list(combinations(SETUPS, 2))
    result = []
    for model, puzzle, validity in keys:
        for metric in PAIRED_METRICS:
            if metric in ("mismatch_detection_rate", "diagnosis_rate") and validity != "invalid":
                continue
            if metric == "diagnosis_rate" and not has_reasons(groups[(model, puzzle, validity)]):
                continue
            if metric == "hallucination_rate" and all(r["decision"] for r in groups[(model, puzzle, validity)]):
                continue
            shares = input_shares(groups[(model, puzzle, validity)], metric)
            rows = []
            for setup_a, setup_b in pairs:
                row = {"model": model, "puzzle": puzzle, "validity": validity, "metric": metric,
                       "setup_a": setup_a, "setup_b": setup_b}
                row.update(compare_setups(shares, setup_a, setup_b))
                rows.append(row)
            family = [r for r in rows if r["inputs_paired"]]
            for r, adjusted in zip(family, holm([r["p_value"] for r in family])):
                r["p_holm"], r["significant"] = adjusted, adjusted < ALPHA
            for r in rows:
                if not r["inputs_paired"]:
                    r["p_holm"] = r["significant"] = NA
            result += [{k: r[k] for k in PAIRED_COLUMNS} for r in rows]
    return result


def stratified_interval(rows: list[dict], key: str, valid_hit, invalid_hit, complement: bool = True) -> tuple:
    """Return (low, high) for a score that averages a valid side and an invalid side, by a stratified
    bootstrap over inputs: valid and invalid inputs are drawn separately, each side as many as it has.
    The score of a draw is (invalid rate + (1 − valid rate)) / 2, or the plain mean of the two rates when
    `complement` is false. A draw where a side has no attempt is left out. n/a when either side has
    under 2 inputs."""
    valid = input_cells([r for r in rows if r["validity"] == "valid"], valid_hit)
    invalid = input_cells([r for r in rows if r["validity"] == "invalid"], invalid_hit)
    if len(valid) < 2 or len(invalid) < 2:
        return NA, NA
    rng = bootstrap_rng(key)
    draws = []
    for _ in range(BOOTSTRAP_DRAWS):
        v = [valid[i] for i in rng.choices(range(len(valid)), k=len(valid))]
        x = [invalid[i] for i in rng.choices(range(len(invalid)), k=len(invalid))]
        v_total, x_total = sum(a for _, a in v), sum(a for _, a in x)
        if not v_total or not x_total:
            continue
        valid_rate, invalid_rate = sum(h for h, _ in v) / v_total, sum(h for h, _ in x) / x_total
        draws.append((invalid_rate + (1 - valid_rate if complement else valid_rate)) / 2)
    return percentiles(draws) if draws else (NA, NA)


def interval_for_balanced_accuracy(rows: list[dict]) -> tuple:
    """Return (low, high) for the balanced accuracy of one group by a stratified bootstrap over inputs."""
    first = rows[0]
    key = f"{first['model']}|{first['puzzle']}|{first['setup']}|balanced_accuracy"
    flagged = lambda r: r["mismatch"]
    return stratified_interval(rows, key, flagged, flagged)


RATE_NAMES = ("detection_rate", "false_mismatch_rate", "diagnosis_rate", "coverage")
DETECTION_COLUMNS = (
    "model", "puzzle", "setup",
    "detection_rate", "detection_rate_low", "detection_rate_high", "detection_rate_n", "detection_rate_inputs",
    "false_mismatch_rate", "false_mismatch_rate_low", "false_mismatch_rate_high", "false_mismatch_rate_n",
    "false_mismatch_rate_inputs", "balanced_accuracy", "balanced_accuracy_low", "balanced_accuracy_high",
    "diagnosis_rate", "diagnosis_rate_low", "diagnosis_rate_high", "diagnosis_rate_n", "diagnosis_rate_inputs",
    "critical_thinking", "critical_thinking_low", "critical_thinking_high",
    "fixed_answer_reason", "fixed_answer_critical_thinking",
    "balanced_precision", "balanced_precision_low", "balanced_precision_high",
    "coverage", "coverage_low", "coverage_high", "coverage_n", "coverage_inputs", "cost_efficiency")


def share(rows: list[dict], hit) -> object:
    """The share of rows that are a hit, n/a for none."""
    return sum(1 for r in rows if hit(r)) / len(rows) if rows else NA


def mean_of_two(a: object, b: object, complement: bool = False) -> object:
    """The mean of two rates, with `b` as one minus itself when `complement`. n/a when either is."""
    if NA in (a, b):
        return NA
    return (a + (1 - b if complement else b)) / 2


def fixed_answer(attempt_rows: list[dict], puzzle: str) -> tuple:
    """Return (reason, critical thinking) of the best fixed answer for a puzzle: MISMATCH with the most
    common corruption type among its invalid inputs, ties broken by `CORRUPTION_TYPES` order."""
    kinds = {}
    for r in attempt_rows:
        if r["puzzle"] == puzzle and r["validity"] == "invalid" and r.get("corruption"):
            kinds[r["input_id"]] = corruption_type(r["corruption"])
    if not kinds:
        return NA, NA
    counts = Counter(kinds.values())
    best = max(counts, key=lambda k: (counts[k], -(CORRUPTION_TYPES.index(k) if k in CORRUPTION_TYPES
                                                   else len(CORRUPTION_TYPES))))
    return best, counts[best] / len(kinds) / 2


def detection_rows(attempt_rows: list[dict], models: list[str] | None = None) -> list[dict]:
    """Return one headline row per AI model, puzzle, and setup, pooled over depths. `attempt_rows` carry
    their `cost`, which cost efficiency needs."""
    order = model_order(attempt_rows, models)
    groups = defaultdict(list)
    for r in attempt_rows:
        groups[(r["model"], r["puzzle"], r["setup"])].append(r)
    keys = sorted(groups, key=lambda k: (model_rank(order, k[0]), PUZZLE_ORDER.index(k[1]),
                                         SETUPS.index(k[2])))
    result = []
    for model, puzzle, setup in keys:
        everything = groups[(model, puzzle, setup)]
        rows = [r for r in everything if r["outcome"] != "infrastructure_failure"]
        if not rows:
            continue
        reasons = has_reasons(everything)
        invalid = [r for r in rows if r["validity"] == "invalid"]
        valid = [r for r in rows if r["validity"] == "valid"]
        key = f"{model}|{puzzle}|{setup}"
        row = {"model": model, "puzzle": puzzle, "setup": setup}
        rate_columns(row, "detection_rate", input_cells(invalid, lambda r: r["mismatch"]), key)
        rate_columns(row, "false_mismatch_rate", input_cells(valid, lambda r: r["mismatch"]), key)
        detection, false_mismatch = row["detection_rate"], row["false_mismatch_rate"]
        low, high = interval_for_balanced_accuracy(rows) if NA not in (detection, false_mismatch) else (NA, NA)
        row.update(balanced_accuracy=mean_of_two(detection, false_mismatch, True),
                   balanced_accuracy_low=low, balanced_accuracy_high=high)
        rate_columns(row, "diagnosis_rate", input_cells(invalid, is_diagnosis) if reasons else [], key)
        diagnosis = row["diagnosis_rate"]
        row["critical_thinking"] = mean_of_two(diagnosis, false_mismatch, True)
        row["critical_thinking_low"] = row["critical_thinking_high"] = NA
        if row["critical_thinking"] != NA:
            row["critical_thinking_low"], row["critical_thinking_high"] = stratified_interval(
                rows, key + "|critical_thinking", lambda r: r["mismatch"], is_diagnosis)
        row["fixed_answer_reason"], row["fixed_answer_critical_thinking"] = (
            fixed_answer(attempt_rows, puzzle) if reasons else (NA, NA))
        classified = [r for r in rows if r["answer_class"]]
        precise = lambda r: r["answer_class"] in ("tp", "tn")
        balanced = mean_of_two(*(share([r for r in classified if r["validity"] == label], precise)
                                 for label in ("valid", "invalid")))
        row["balanced_precision"] = balanced
        row["balanced_precision_low"] = row["balanced_precision_high"] = NA
        if balanced != NA:
            row["balanced_precision_low"], row["balanced_precision_high"] = stratified_interval(
                classified, key + "|balanced_precision", precise, precise, complement=False)
        rate_columns(row, "coverage", input_cells(rows, lambda r: r["answer_class"] is not None), key)
        denominator = NA if balanced == NA or row["coverage"] == NA else balanced * row["coverage"]
        row["cost_efficiency"] = (mean([r["cost"] for r in everything]) / denominator
                                  if denominator not in (NA, 0) else NA)
        result.append(row)
    return result


CORRUPTION_TYPES = CUBE_CORRUPTION_TYPES  # one list of corruption types, in report order

CORRUPTION_COLUMNS = ("model", "puzzle", "setup", "corruption_type", "detection_rate", "detection_rate_low",
                      "detection_rate_high", "detection_rate_n", "detection_rate_inputs",
                      "diagnosis_rate", "diagnosis_rate_low", "diagnosis_rate_high", "diagnosis_rate_n",
                      "diagnosis_rate_inputs")


def corruption_type(description: str) -> str:
    """Return the corruption type: the first two words of a corruption description."""
    return " ".join(description.split()[:2])


def corruption_rows(attempt_rows: list[dict], models: list[str] | None = None) -> list[dict]:
    """Return one detection and diagnosis row per AI model, puzzle, setup, and corruption type, over invalid
    inputs."""
    order = model_order(attempt_rows, models)
    groups = defaultdict(list)
    for r in attempt_rows:
        if r["validity"] == "invalid" and r["outcome"] != "infrastructure_failure" and r.get("corruption"):
            groups[(r["model"], r["puzzle"], r["setup"], corruption_type(r["corruption"]))].append(r)

    def sort_key(k):
        kind = CORRUPTION_TYPES.index(k[3]) if k[3] in CORRUPTION_TYPES else len(CORRUPTION_TYPES)
        return (model_rank(order, k[0]), PUZZLE_ORDER.index(k[1]), SETUPS.index(k[2]), kind, k[3])

    result = []
    for key in sorted(groups, key=sort_key):
        model, puzzle, setup, kind = key
        rows = groups[key]
        row = {"model": model, "puzzle": puzzle, "setup": setup, "corruption_type": kind}
        rate_columns(row, "detection_rate", input_cells(rows, lambda r: r["mismatch"]), "|".join(key))
        rate_columns(row, "diagnosis_rate", input_cells(rows, is_diagnosis) if has_reasons(rows) else [],
                     "|".join(key))
        result.append(row)
    return result


REASON_COLUMNS = ("model", "puzzle", "setup", "expected", "reason", "attempts")


def reason_rows(attempt_rows: list[dict], models: list[str] | None = None) -> list[dict]:
    """Return the count of attempts per AI model, puzzle, setup, expected corruption type (`none` for a valid
    input), and reason given (`none` for no reason). Empty under a release without mismatch reasons."""
    order = model_order(attempt_rows, models)
    counts = Counter()
    for r in attempt_rows:
        if r["outcome"] == "infrastructure_failure" or not r["reasons"]:
            continue
        expected = corruption_type(r["corruption"]) if r["validity"] == "invalid" and r.get("corruption") else "none"
        counts[(r["model"], r["puzzle"], r["setup"], expected, r["mismatch_reason"] or "none")] += 1

    def sort_key(k):
        model, puzzle, setup, expected, reason = k
        kinds = ["none", *CORRUPTION_TYPES]
        offered = ["none", *offered_reasons(ENGINES[puzzle])]
        return (model_rank(order, model), PUZZLE_ORDER.index(puzzle), SETUPS.index(setup),
                kinds.index(expected) if expected in kinds else len(kinds), expected,
                offered.index(reason) if reason in offered else len(offered), reason)

    return [dict(zip(REASON_COLUMNS, key), attempts=counts[key]) for key in sorted(counts, key=sort_key)]
