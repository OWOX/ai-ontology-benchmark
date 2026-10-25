# Spec: docs/specs/ui.md
"""Reads one experiment branch (`results/<id>` on a git ref) into attempt rows, bundle rows, and
detail metrics. Reads the branch's config, raw files, prices, and report, and the release inputs
through GitData. Writes nothing. The maths is `src.evaluate.metrics`.
"""

import csv
import io
import json
import re
import tomllib
from collections import defaultdict

from src.config import parse_experiment_config
from src.evaluate.evaluate import REQUIRED
from src.evaluate.metrics import (KEY, NA, EvalError, group_metrics, make_attempt_rows,
                                  metric_sort_key, rates, sorted_keys, summary_sort_key)
from src.puzzles.registry import ENGINES
from src.release.release import parse_version
from ui.gitdata import GitData
from ui.pooling import RATES, pooled_rates, pooled_summary, total

SCOPES = ("all", "valid", "invalid")
REPORT_CSV = re.compile(r"(\d+\.\d+\.\d+)\.metrics\.csv")
TEXT_COLUMNS = ("puzzle", "setup", "model", "validity")
NO_PRICE = {"price_input_per_mtok": 0.0, "price_output_per_mtok": 0.0}


def parse_raw(text: str) -> tuple[list[dict], int]:
    """Same rules as `src.run.raw.read_raw`, on text: lines that are not JSON objects are skipped and counted."""
    records, skipped = [], 0
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            skipped += 1
    return records, skipped


def read_inputs(git: GitData, ref: str, release: str) -> list[dict]:
    text = git.show(ref, f"releases/{release}/inputs.jsonl") or ""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def csv_value(column: str, text: str) -> object:
    if column in TEXT_COLUMNS or text == NA:
        return text
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    return text


def load_experiment(git: GitData, experiment_id: str, ref: str, main_ref: str) -> dict:
    base = f"results/{experiment_id}"
    exp = {"id": experiment_id, "ref": ref, "sha": git.sha(ref), "config": None, "records": {},
           "skipped": 0, "prices": {}, "report_version": None, "csv_rows": None,
           "report_md": None, "error": None}
    try:
        text = git.show(ref, f"{base}/experiment.toml")
        if text is None:
            raise ValueError(f"{base}/experiment.toml: file not found")
        exp["config"] = parse_experiment_config(text, experiment_id, f"{base}/experiment.toml")
        saved = git.show(ref, f"{base}/prices.toml")
        exp["prices"] = tomllib.loads(saved if saved is not None
                                      else git.show(main_ref, "config/prices.toml") or "")
        for name in sorted(n for n in git.ls(ref, f"{base}/raw") if n.endswith(".jsonl")):
            found, torn = parse_raw(git.show(ref, f"{base}/raw/{name}") or "")
            exp["skipped"] += torn
            for record in found:
                missing = [f for f in REQUIRED if f not in record]
                if missing:
                    raise EvalError(f"{base}/raw/{name}: a record lacks field '{missing[0]}'")
            exp["records"][name[:-len(".jsonl")]] = found
    except (ValueError, EvalError, tomllib.TOMLDecodeError) as error:
        exp["error"] = str(error)
        return exp
    versions = [m.group(1) for n in git.ls(ref, base) if (m := REPORT_CSV.fullmatch(n))]
    if versions:
        newest = max(versions, key=parse_version)
        text = git.show(ref, f"{base}/{newest}.metrics.csv") or ""
        exp["report_version"] = newest
        exp["csv_rows"] = [{k: csv_value(k, v) for k, v in row.items()}
                           for row in csv.DictReader(io.StringIO(text))]
        exp["report_md"] = git.show(ref, f"{base}/{newest}.md")
    return exp


def model_names(exp: dict) -> list[str]:
    config = exp["config"]
    return [m["name"] for m in config["models"]] if config else sorted(exp["records"])


def attempt_rows(exp: dict, inputs: list[dict]) -> list[dict]:
    """Every record re-validated. A record that cannot be scored sets `exp["error"]` and gives no rows."""
    if exp["error"]:
        return []
    prices = {m: NO_PRICE for m in exp["records"]} | exp["prices"]
    records = [r for found in exp["records"].values() for r in found]
    try:
        return make_attempt_rows(records, inputs, prices, {})
    except (EvalError, KeyError) as error:
        exp["error"] = str(error.args[0]) if error.args else str(error)
        return []


def all_scope_rates(done: list[dict]) -> dict:
    """Pooled over valid and invalid: detection over the invalid rows, false mismatch over the valid ones."""
    out = rates(done, "valid")
    invalid = rates([r for r in done if r["validity"] == "invalid"], "invalid")
    valid = rates([r for r in done if r["validity"] == "valid"], "valid")
    out.update({k: v for k, v in invalid.items() if k.startswith("mismatch_detection_rate")})
    out.update({k: v for k, v in valid.items() if k.startswith("false_mismatch_rate")})
    return out


def scope_rates(rows: list[dict], scope: str) -> dict:
    if scope != "all":
        return group_metrics(rows, scope, False)
    done = [r for r in rows if r["outcome"] != "infrastructure_failure"]
    out = {"attempts": len(rows), "infrastructure_failure_count": len(rows) - len(done)}
    return out | all_scope_rates(done)


def cell(value: object) -> object:
    return None if value == NA else value


def experiment_rows(exp: dict, inputs: list[dict]) -> list[dict]:
    config = exp["config"]
    rows = attempt_rows(exp, inputs)
    source = "report" if exp["csv_rows"] is not None else "computed"
    models = {m["name"]: m for m in config["models"]} if config else {}
    base = {"id": exp["id"], "release": config["release"] if config else None,
            "metrics_source": source, "report_version": exp["report_version"],
            "differs_from_catalogue": False, "pushed": False, "running": False,
            "error": exp["error"], "branch": None}
    empty = {"attempts": None, "infrastructure_failures": None, "total_tokens": None, "cost_usd": None,
             "served_models": [], **{r: None for r in RATES}}
    if exp["error"]:
        return [{**base, **empty, "model": n, "puzzle": None, "validity": "all",
                 "provider": models.get(n, {}).get("provider"),
                 "api_model_id": models.get(n, {}).get("api_model_id")}
                for n in list(models) or [None]]
    out = []
    for name in model_names(exp):
        mine = [r for r in rows if r["model"] == name]
        for puzzle in sorted({r["puzzle"] for r in mine}, key=list(ENGINES).index):
            for scope in SCOPES:
                part = [r for r in mine if r["puzzle"] == puzzle and scope in ("all", r["validity"])]
                out.append({**base, "model": name, "puzzle": puzzle, "validity": scope,
                            "provider": models[name]["provider"], "api_model_id": models[name]["api_model_id"],
                            **numbers(exp, name, puzzle, scope, part)})
    return out


def numbers(exp: dict, model: str, puzzle: str, scope: str, part: list[dict]) -> dict:
    if exp["csv_rows"] is not None:
        pick = [r for r in exp["csv_rows"] if r["model"] == model and r["puzzle"] == puzzle
                and scope in ("all", r["validity"])]
        stats = {"attempts": total(pick, "attempts"),
                 "infrastructure_failure_count": total(pick, "infrastructure_failure_count")} | pooled_rates(pick)
    else:
        stats = scope_rates(part, scope)
    tokens = sum(r["input_tokens"] + r["output_tokens"] + r["retry_input_tokens"]
                 + r["retry_output_tokens"] for r in part)
    priced = model in exp["prices"]
    return {"attempts": stats["attempts"], "infrastructure_failures": stats["infrastructure_failure_count"],
            **{r: cell(stats[r]) for r in RATES}, "total_tokens": tokens,
            "cost_usd": sum(r["cost"] for r in part) if priced else None,
            "served_models": sorted({r["served_model"] for r in part if r["served_model"]})}


def detail_metrics(exp: dict, inputs: list[dict]) -> tuple[list[dict], list[dict], str]:
    """(metric_rows, summary_rows, metrics_source): the report CSV when there is one, else computed."""
    order = model_names(exp)
    rows = attempt_rows(exp, inputs)
    if exp["csv_rows"] is not None:
        return exp["csv_rows"], pooled_summary(exp["csv_rows"], order, rows), "report"
    groups, pooled = defaultdict(list), defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in KEY)].append(r)
        pooled[(r["model"], r["setup"], r["validity"])].append(r)
    metric_rows = [dict(zip(KEY, key)) | group_metrics(groups[key], key[4], True)
                   for key in sorted_keys(groups, metric_sort_key, order)]
    summary_rows = [dict(zip(("model", "setup", "validity"), key)) | group_metrics(pooled[key], key[2], False)
                    for key in sorted_keys(pooled, summary_sort_key, order)]
    return metric_rows, summary_rows, "computed"


def impossible_moves(row: dict, legal: list[str]) -> list[str]:
    """The parsed moves of one attempt row that are not legal moves, in order."""
    return [m for m in row.get("parsed_moves") or [] if m not in legal]
