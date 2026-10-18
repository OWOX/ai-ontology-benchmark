# Spec: docs/specs/report.md
"""Writes the experiment report as one Markdown file. Reads the release manifest (for the
assessment hash) and takes everything else from the caller. Writes the file at `path`. It
is not part of the assessment, so changing its layout never needs a release.
"""

import json
import os
from collections import defaultdict
from pathlib import Path

from src.run.prompts import SETUPS

NA = "n/a"
VALID_ROWS = [
    ("Success rate", "success_rate"),
    ("Hallucination rate", "hallucination_rate"),
    ("False mismatch rate", "false_mismatch_rate"),
    ("Malformed output rate", "malformed_output_rate"),
    ("Cost per success", "cost_per_success"),
]
INVALID_ROWS = [
    ("Success rate", "success_rate"),
    ("Mismatch detection rate", "mismatch_detection_rate"),
    ("Hallucination rate", "hallucination_rate"),
    ("Malformed output rate", "malformed_output_rate"),
]
METRIC_COLUMNS = [
    ("Success", "success_rate"),
    ("Hallucination", "hallucination_rate"),
    ("Mismatch detection", "mismatch_detection_rate"),
    ("False mismatch", "false_mismatch_rate"),
    ("Malformed", "malformed_output_rate"),
]


def cell(value: object) -> str:
    """Make a value safe for a Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def number(value: object, places: int) -> str:
    return NA if value == NA or value is None else f"{value:.{places}f}"


def rate_cell(row: dict, name: str) -> str:
    """Show a rate as `0.42 (0.30–0.55) n=60`."""
    if row[name] == NA:
        return f"{NA} n={row[name + '_n']}"
    low, high = row[name + "_low"], row[name + "_high"]
    return f"{row[name]:.2f} ({low:.2f}–{high:.2f}) n={row[name + '_n']}"


def value_cell(row: dict, name: str) -> str:
    return number(row[name], 4) if name == "cost_per_success" else rate_cell(row, name)


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        lines.append("| " + " | ".join(cell(c) for c in row) + " |")
    return lines + [""]


def release_section(link, release_dir: Path, experiment_config: dict) -> list[str]:
    version = release_dir.name
    manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    ran_on = experiment_config["release"]
    if version != ran_on:
        mirror = f"This report is a mirror of release {ran_on}."
    else:
        mirror = "This report is not a mirror."
    readme = link(release_dir / "README.md")
    return [
        f"Release: [{version}, tag `release-{version}`]({readme})", "",
        f"The experiment ran on release {ran_on}. {mirror}", "",
        f"Assessment hash: `{manifest['assessment_sha256']}`", "",
        f"Inputs: [inputs.jsonl]({link(release_dir / 'inputs.jsonl')}). "
        f"Prompts: [prompts/]({link(release_dir / 'prompts')}).", "",
    ]


def params_text(model: dict) -> str:
    """The model's params as `k=v, k=v`, or `provider defaults` when it sets none."""
    params = model.get("params", {})
    return ", ".join(f"{k}={v}" for k, v in sorted(params.items())) or "provider defaults"


def experiment_section(link, folder: Path, config: dict, prices: dict, rows: list[dict],
                       torn: int) -> list[str]:
    served = defaultdict(set)
    for row in rows:
        if row["served_model"]:
            served[row["model"]].add(row["served_model"])
    models = []
    for m in config["models"]:
        served_ids = ", ".join(sorted(served[m["name"]]))
        models.append([m["name"], m["provider"], m["api_model_id"], served_ids, params_text(m)])
    times = sorted(row["created_at"] for row in rows if row["created_at"])
    first, last = (times[0], times[-1]) if times else (NA, NA)
    config_link = link(folder / "experiment.toml")
    out = ["## Experiment", "", f"Config: [experiment.toml]({config_link})", ""]
    out += table(["AI model", "Provider", "API model id", "Served model ids", "Params"], models)
    out += [
        f"Attempts per input, model and setup: {config['attempts']}. "
        f"Retry cap: {config['retry_cap']}. "
        f"Maximum output tokens: {config['max_output_tokens']}.", "",
        f"First and last attempt: {first} to {last}.", "",
        f"Torn raw lines skipped: {torn}.", "",
        f"Token prices per million tokens, from [prices.toml]({link(folder / 'prices.toml')}):", "",
    ]
    price_rows = []
    for m in config["models"]:
        price = prices[m["name"]]
        price_rows.append(
            [m["name"], price["price_input_per_mtok"], price["price_output_per_mtok"]])
    return out + table(["AI model", "Input", "Output"], price_rows)


def summary_cell(by_key: dict, model: str, setup: str, validity: str, name: str) -> str:
    """One summary cell, or n/a when the AI model has no row for that setup and validity."""
    row = by_key.get((model, setup, validity))
    return NA if row is None else value_cell(row, name)


def summary_section(config: dict, summary_rows: list[dict]) -> list[str]:
    by_key = {(r["model"], r["setup"], r["validity"]): r for r in summary_rows}
    used = {r["setup"] for r in summary_rows}
    setups = [s for s in SETUPS if s in used]
    blocks = (("valid", "Valid inputs", VALID_ROWS), ("invalid", "Invalid inputs", INVALID_ROWS))
    out = ["## Summary", ""]
    for model in config["models"]:
        out += [f"### {model['name']}", ""]
        for validity, label, rows in blocks:
            body = []
            for title, name in rows:
                cells = [summary_cell(by_key, model["name"], s, validity, name) for s in setups]
                body.append([title] + cells)
            out += [f"#### {label}", ""] + table(["Metric"] + setups, body)
    return out


def metric_line(r: dict) -> list:
    """One row of a puzzle's metrics table."""
    line = [r["setup"], r["model"], r["scramble_depth"], r["validity"], r["attempts"],
            r["infrastructure_failure_count"]]
    for _, name in METRIC_COLUMNS:
        line.append(rate_cell(r, name))
    line += [
        number(r["efficiency"], 2), number(r["consistency"], 2),
        number(r["latency_per_attempt_s"], 2), number(r["input_tokens_per_attempt"], 1),
        number(r["output_tokens_per_attempt"], 1), number(r["cost_per_success"], 4),
    ]
    return line


def metrics_section(metric_rows: list[dict]) -> list[str]:
    out = ["## Metrics", ""]
    header = ["Setup", "AI model", "Depth", "Validity", "Attempts", "Infra failures"]
    header += [title for title, _ in METRIC_COLUMNS]
    header += ["Efficiency", "Consistency", "Latency (s)", "Input tokens", "Output tokens",
               "Cost per success"]
    puzzles = list(dict.fromkeys(r["puzzle"] for r in metric_rows))
    for puzzle in puzzles:
        body = []
        for r in metric_rows:
            if r["puzzle"] == puzzle:
                body.append(metric_line(r))
        out += [f"### {puzzle}", ""] + table(header, body)
    return out


def outcome_text(r: dict) -> str:
    """The current outcome, or `stored → current` when re-validation changed it."""
    if r["outcome"] == r["stored_outcome"]:
        return r["outcome"]
    return f"{r['stored_outcome']} → {r['outcome']}"


def attempts_section(link, release_dir: Path, attempt_rows: list[dict]) -> list[str]:
    out = ["## Attempts", ""]
    header = ["AI model", "Setup", "Attempt", "Outcome", "Moves", "Mismatch",
              "Input tokens (excl. retries)", "Output tokens (excl. retries)", "Latency (s)"]
    by_input = defaultdict(list)
    for r in attempt_rows:
        by_input[r["input_id"]].append(r)
    for input_id, rows in by_input.items():
        first = rows[0]
        url = f"{link(release_dir / 'inputs.jsonl')}#L{first['input_line']}"
        label = f"({first['validity']}, depth {first['scramble_depth']})"
        out += [f"### [{input_id}]({url}) {label}", ""]
        body = []
        for r in rows:
            body.append([
                r["model"], r["setup"], r["attempt_number"], outcome_text(r),
                " ".join(r["parsed_moves"]), str(r["mismatch"]).lower(),
                r["input_tokens"], r["output_tokens"], number(r["latency_s"], 2),
            ])
        out += table(header, body)
    return out


def write_report(path, experiment_id, experiment_config, release_dir, prices, attempt_rows,
                 metric_rows, summary_rows, torn_lines: int = 0) -> None:
    path, release_dir = Path(path), Path(release_dir)

    def link(target: Path) -> str:
        """A link relative to the report, so it works on GitHub."""
        return os.path.relpath(target, path.parent).replace(os.sep, "/")

    lines = [f"# Experiment {experiment_id} on release {release_dir.name}", ""]
    lines += release_section(link, release_dir, experiment_config)
    lines += experiment_section(link, path.parent, experiment_config, prices, attempt_rows,
                                torn_lines)
    lines += summary_section(experiment_config, summary_rows)
    lines += metrics_section(metric_rows)
    lines += attempts_section(link, release_dir, attempt_rows)
    lines += ["## Raw responses", "",
              f"Not copied here. See [raw/]({link(path.parent / 'raw')}).", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
