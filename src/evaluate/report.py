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
VALID_ROWS = [("Success rate", "success_rate"), ("Hallucination rate", "hallucination_rate"),
              ("False mismatch rate", "false_mismatch_rate"),
              ("Malformed output rate", "malformed_output_rate"), ("Cost per success", "cost_per_success")]
INVALID_ROWS = [("Success rate", "success_rate"), ("Mismatch detection rate", "mismatch_detection_rate"),
                ("Hallucination rate", "hallucination_rate"), ("Malformed output rate", "malformed_output_rate")]
METRIC_COLUMNS = [("Success", "success_rate"), ("Hallucination", "hallucination_rate"),
                  ("Mismatch detection", "mismatch_detection_rate"), ("False mismatch", "false_mismatch_rate"),
                  ("Malformed", "malformed_output_rate")]


def cell(value: object) -> str:
    """Make a value safe for a Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def number(value: object, places: int) -> str:
    return NA if value == NA or value is None else f"{value:.{places}f}"


def rate_cell(row: dict, name: str) -> str:
    """Show a rate as `0.42 (0.30–0.55) n=60`."""
    if row[name] == NA:
        return f"{NA} n={row[name + '_n']}"
    return f"{row[name]:.2f} ({row[name + '_low']:.2f}–{row[name + '_high']:.2f}) n={row[name + '_n']}"


def value_cell(row: dict, name: str) -> str:
    return number(row[name], 4) if name == "cost_per_success" else rate_cell(row, name)


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return lines + ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows] + [""]


def release_section(link, release_dir: Path, experiment_config: dict) -> list[str]:
    version = release_dir.name
    manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    ran_on = experiment_config["release"]
    mirror = f"This report is a mirror of release {ran_on}." if version != ran_on else "This report is not a mirror."
    return [f"Release: [{version}, tag `release-{version}`]({link(release_dir / 'README.md')})", "",
            f"The experiment ran on release {ran_on}. {mirror}", "",
            f"Assessment hash: `{manifest['assessment_sha256']}`", "",
            f"Inputs: [inputs.jsonl]({link(release_dir / 'inputs.jsonl')}). "
            f"Prompts: [prompts/]({link(release_dir / 'prompts')}).", ""]


def experiment_section(link, folder: Path, config: dict, prices: dict, rows: list[dict], torn: int) -> list[str]:
    served = defaultdict(set)
    for row in rows:
        if row["served_model"]:
            served[row["model"]].add(row["served_model"])
    models = []
    for m in config["models"]:
        params = ", ".join(f"{k}={v}" for k, v in sorted(m.get("params", {}).items())) or "provider defaults"
        models.append([m["name"], m["provider"], m["api_model_id"], ", ".join(sorted(served[m["name"]])), params])
    times = sorted(row["created_at"] for row in rows if row["created_at"])
    out = ["## Experiment", "", f"Config: [experiment.toml]({link(folder / 'experiment.toml')})", ""]
    out += table(["AI model", "Provider", "API model id", "Served model ids", "Params"], models)
    out += [f"Attempts per input, model and setup: {config['attempts']}. Retry cap: {config['retry_cap']}. "
            f"Maximum output tokens: {config['max_output_tokens']}.", "",
            f"First and last attempt: {times[0] if times else NA} to {times[-1] if times else NA}.", "",
            f"Torn raw lines skipped: {torn}.", "",
            f"Token prices per million tokens, from [prices.toml]({link(folder / 'prices.toml')}):", ""]
    price_rows = [[m["name"], prices[m["name"]]["price_input_per_mtok"], prices[m["name"]]["price_output_per_mtok"]]
                  for m in config["models"]]
    return out + table(["AI model", "Input", "Output"], price_rows)


def summary_section(config: dict, summary_rows: list[dict]) -> list[str]:
    by_key = {(r["model"], r["setup"], r["validity"]): r for r in summary_rows}
    setups = [s for s in SETUPS if any(r["setup"] == s for r in summary_rows)]
    out = ["## Summary", ""]
    for model in config["models"]:
        out += [f"### {model['name']}", ""]
        for validity, label, rows in (("valid", "Valid inputs", VALID_ROWS), ("invalid", "Invalid inputs", INVALID_ROWS)):
            body = []
            for title, name in rows:
                cells = [value_cell(by_key[(model["name"], s, validity)], name)
                         if (model["name"], s, validity) in by_key else NA for s in setups]
                body.append([title] + cells)
            out += [f"#### {label}", ""] + table(["Metric"] + setups, body)
    return out


def metrics_section(metric_rows: list[dict]) -> list[str]:
    out = ["## Metrics", ""]
    header = (["Setup", "AI model", "Depth", "Validity", "Attempts", "Infra failures"] + [t for t, _ in METRIC_COLUMNS]
              + ["Efficiency", "Consistency", "Latency (s)", "Input tokens", "Output tokens", "Cost per success"])
    puzzles = list(dict.fromkeys(r["puzzle"] for r in metric_rows))
    for puzzle in puzzles:
        body = []
        for r in (r for r in metric_rows if r["puzzle"] == puzzle):
            body.append([r["setup"], r["model"], r["scramble_depth"], r["validity"], r["attempts"],
                         r["infrastructure_failure_count"]] + [rate_cell(r, n) for _, n in METRIC_COLUMNS]
                        + [number(r["efficiency"], 2), number(r["consistency"], 2), number(r["latency_per_attempt_s"], 2),
                           number(r["input_tokens_per_attempt"], 1), number(r["output_tokens_per_attempt"], 1),
                           number(r["cost_per_success"], 4)])
        out += [f"### {puzzle}", ""] + table(header, body)
    return out


def attempts_section(link, release_dir: Path, attempt_rows: list[dict]) -> list[str]:
    out = ["## Attempts", ""]
    by_input = defaultdict(list)
    for r in attempt_rows:
        by_input[r["input_id"]].append(r)
    for input_id, rows in by_input.items():
        first = rows[0]
        url = f"{link(release_dir / 'inputs.jsonl')}#L{first['input_line']}"
        out += [f"### [{input_id}]({url}) ({first['validity']}, depth {first['scramble_depth']})", ""]
        body = []
        for r in rows:
            outcome = r["outcome"] if r["outcome"] == r["stored_outcome"] else f"{r['stored_outcome']} → {r['outcome']}"
            body.append([r["model"], r["setup"], r["attempt_number"], outcome, " ".join(r["parsed_moves"]),
                         str(r["mismatch"]).lower(), r["input_tokens"], r["output_tokens"], number(r["latency_s"], 2)])
        out += table(["AI model", "Setup", "Attempt", "Outcome", "Moves", "Mismatch", "Input tokens",
                      "Output tokens", "Latency (s)"], body)
    return out


def write_report(path, experiment_id, experiment_config, release_dir, prices, attempt_rows, metric_rows,
                 summary_rows, torn_lines: int = 0) -> None:
    path, release_dir = Path(path), Path(release_dir)

    def link(target: Path) -> str:
        """A link relative to the report, so it works on GitHub."""
        return os.path.relpath(target, path.parent).replace(os.sep, "/")

    lines = [f"# Experiment {experiment_id} on release {release_dir.name}", ""]
    lines += release_section(link, release_dir, experiment_config)
    lines += experiment_section(link, path.parent, experiment_config, prices, attempt_rows, torn_lines)
    lines += summary_section(experiment_config, summary_rows)
    lines += metrics_section(metric_rows)
    lines += attempts_section(link, release_dir, attempt_rows)
    lines += ["## Raw responses", "", f"Not copied here. See [raw/]({link(path.parent / 'raw')}).", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
