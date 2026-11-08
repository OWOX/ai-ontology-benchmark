# Spec: docs/specs/report.md
"""Writes the experiment report as one Markdown file. Reads the release manifest (for the
assessment hash) and takes everything else from the caller. Writes the file at `path`. It
is not part of the assessment, so changing its layout never needs a release.
"""

import json
import os
from collections import defaultdict
from pathlib import Path

from src.puzzles.cube import CUBE_CORRUPTION_TYPES
from src.puzzles.registry import ENGINES
from src.run.prompts import SETUPS
from src.validator import offered_reasons

NA = "n/a"
VALID_ROWS = [
    ("Precision", "precision", False),
    ("Coverage", "coverage", False),
    ("Hallucination rate", "hallucination_rate", False),
    ("Reason hallucination rate", "reason_hallucination_rate", True),
    ("False mismatch rate", "false_mismatch_rate", False),
    ("Malformed output rate", "malformed_output_rate", False),
    ("Truncation rate", "truncated_rate", False),
    ("Abstention rate", "abstention_rate", False),
    ("Format error rate", "format_error_rate", False),
    ("Cost per attempt", "cost_per_attempt", False),
]
INVALID_ROWS = [
    ("Precision", "precision", False),
    ("Coverage", "coverage", False),
    ("Mismatch detection rate", "mismatch_detection_rate", False),
    ("Diagnosis rate", "diagnosis_rate", True),
    ("Hallucination rate", "hallucination_rate", False),
    ("Reason hallucination rate", "reason_hallucination_rate", True),
    ("Malformed output rate", "malformed_output_rate", False),
    ("Truncation rate", "truncated_rate", False),
    ("Abstention rate", "abstention_rate", False),
    ("Format error rate", "format_error_rate", False),
]
METRIC_COLUMNS = [
    ("Precision", "precision"),
    ("Hallucination", "hallucination_rate"),
    ("Mismatch detection", "mismatch_detection_rate"),
    ("False mismatch", "false_mismatch_rate"),
    ("Malformed", "malformed_output_rate"),
    ("Truncated", "truncated_rate"),
    ("Abstention", "abstention_rate"),
    ("Format error", "format_error_rate"),
]


def cell(value: object) -> str:
    """Make a value safe for a Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def number(value: object, places: int) -> str:
    return NA if value == NA or value is None else f"{value:.{places}f}"


def p_text(value: object) -> str:
    """Show a p-value to 3 places, or `<0.001` when it is smaller."""
    return f"<0.001" if isinstance(value, float) and value < 0.001 else number(value, 3)


def rate_cell(row: dict, name: str) -> str:
    """Show a rate as `0.42 (0.30–0.55) n=60, 20 inputs`, or `0.42 (n/a) n=60, 1 input` with no interval."""
    k = row[name + "_inputs"]
    counts = f"n={row[name + '_n']}, {k} input{'' if k == 1 else 's'}"
    if row[name] == NA:
        return f"{NA} {counts}"
    low, high = row[name + "_low"], row[name + "_high"]
    if low == NA:
        return f"{row[name]:.2f} ({NA}) {counts}"
    return f"{row[name]:.2f} ({low:.2f}–{high:.2f}) {counts}"


def interval_cell(row: dict, name: str) -> str:
    """Show a value as `0.75 (0.50–1.00)`, or just `0.75` with no interval, `n/a` when missing."""
    low, high = row[name + "_low"], row[name + "_high"]
    if row[name] == NA or low == NA:
        return number(row[name], 2)
    return f"{row[name]:.2f} ({low:.2f}–{high:.2f})"


def balanced_cell(row: dict) -> str:
    return interval_cell(row, "balanced_accuracy")


def has_reasons(attempt_rows) -> bool:
    """True when the attempts come from a release with mismatch reasons."""
    return bool(attempt_rows) and all(r["reasons"] for r in attempt_rows)


def value_cell(row: dict, name: str) -> str:
    return number(row[name], 4) if name == "cost_per_attempt" else rate_cell(row, name)


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
        served[row["model"]].update(filter(None, row["served_model"].split(",")))
    models = []
    for m in config["models"]:
        served_ids = ", ".join(sorted(served[m["name"]]))
        models.append([m["name"], m["provider"], m["api_model_id"], m.get("kind", "not set"), served_ids,
                       params_text(m)])
    times = sorted(row["created_at"] for row in rows if row["created_at"])
    first, last = (times[0], times[-1]) if times else (NA, NA)
    config_link = link(folder / "experiment.toml")
    out = ["## Experiment", "", f"Config: [experiment.toml]({config_link})", ""]
    out += table(["AI model", "Provider", "API model id", "Kind", "Served model ids", "Params"], models)
    if "puzzles" in config:
        out += [f"Puzzles: {', '.join(config['puzzles'])}", ""]
    out += [
        f"Attempts per input, model and setup: {config['attempts']}. "
        f"Retry cap: {config['retry_cap']}. "
        f"Maximum output tokens: {config['max_output_tokens']}. "
        f"Reasoning effort: {config.get('reasoning_effort') or 'provider default'}.", "",
        f"First and last attempt: {first} to {last}.", "",
        f"Torn raw lines skipped: {torn}.", "",
        f"Token prices per million tokens, from [prices.toml]({link(folder / 'prices.toml')}):", "",
    ]
    price_rows = []
    for m in config["models"]:
        price = prices[m["name"]]
        price_rows.append(
            [m["name"], price["price_input_per_mtok"], price["price_output_per_mtok"]])
    out += table(["AI model", "Input", "Output"], price_rows)
    return out + budget_lines(config, rows)


def budget_lines(config: dict, rows: list[dict]) -> list[str]:
    """The budgets in force, and the cost spent per AI model and in total, at the prices used."""
    budget = config["budget"]
    spent = {m["name"]: sum(r["cost"] for r in rows if r["model"] == m["name"])
             for m in config["models"]}
    out = [
        f"Budgets in force (USD): request {budget['per_request_usd']}, "
        f"AI model {budget['per_model_usd']}, experiment {budget['per_experiment_usd']}.", "",
        "Cost spent, at the prices above (USD):", "",
    ]
    body = [[name, number(cost, 4)] for name, cost in spent.items()]
    body.append(["Total", number(sum(spent.values()), 4)])
    return out + table(["AI model", "Spent"], body)


def summary_cell(by_key: dict, model: str, setup: str, validity: str, name: str) -> str:
    """One summary cell, or n/a when the AI model has no row for that setup and validity."""
    row = by_key.get((model, setup, validity))
    return NA if row is None else value_cell(row, name)


def headline_table(model: str, detection_rows, reasons: bool, definitions_link: str) -> list[str]:
    """The headline table of one AI model: one row per puzzle and setup."""
    header = ["Puzzle", "Setup", "Balanced precision", "Coverage"]
    if reasons:
        header.append("Critical thinking")
    header.append("Cost efficiency")
    body = []
    for r in detection_rows:
        if r["model"] != model:
            continue
        line = [r["puzzle"], r["setup"], interval_cell(r, "balanced_precision"), rate_cell(r, "coverage")]
        if reasons:
            line.append(interval_cell(r, "critical_thinking"))
        line.append(number(r["cost_efficiency"], 4))
        body.append(line)
    return table(header, body) if body else []


def summary_section(config: dict, summary_rows: list[dict], detection_rows=(), reasons: bool = False,
                    definitions_link: str = "") -> list[str]:
    by_key = {(r["model"], r["setup"], r["validity"]): r for r in summary_rows}
    used = {r["setup"] for r in summary_rows}
    setups = [s for s in SETUPS if s in used]
    blocks = (("valid", "Valid inputs", VALID_ROWS), ("invalid", "Invalid inputs", INVALID_ROWS))
    out = ["## Summary", ""]
    for model in config["models"]:
        out += [f"### {model['name']}", ""]
        out += headline_table(model["name"], detection_rows, reasons, definitions_link)
        for validity, label, rows in blocks:
            body = []
            for title, name, needs_reasons in rows:
                if needs_reasons and not reasons:
                    continue
                cells = [summary_cell(by_key, model["name"], s, validity, name) for s in setups]
                body.append([title] + cells)
            out += [f"#### {label}", ""] + table(["Metric"] + setups, body)
    return out


def significant_text(value: object) -> str:
    return NA if value == NA else "yes" if value else "no"


def comparison_section(definitions_link: str, config: dict, paired_rows) -> list[str]:
    """The paired setup test: one table per AI model and puzzle."""
    out = ["## Setup comparison", "",
           f"Each row is a [paired setup test]({definitions_link}#metrics) of two setups on the "
           "same inputs.", ""]
    header = ["Validity", "Metric", "Setups", "Inputs paired", "A higher", "B higher",
              "Mean difference", "p", "Holm p", "Significant"]
    for model in config["models"]:
        rows = [r for r in paired_rows if r["model"] == model["name"]]
        if not rows:
            continue
        out += [f"### {model['name']}", ""]
        for puzzle in dict.fromkeys(r["puzzle"] for r in rows):
            body = [[r["validity"], r["metric"], f"{r['setup_a']} vs {r['setup_b']}",
                     r["inputs_paired"], r["a_higher"], r["b_higher"],
                     number(r["mean_difference"], 2), p_text(r["p_value"]),
                     p_text(r["p_holm"]), significant_text(r["significant"])]
                    for r in rows if r["puzzle"] == puzzle]
            out += [f"#### {puzzle}", ""] + table(header, body)
    return out


def detection_section(definitions_link: str, config: dict, detection_rows, reasons: bool = False) -> list[str]:
    """Mismatch detection as balanced accuracy: one table per AI model."""
    out = ["## Mismatch detection", "",
           f"[Balanced accuracy]({definitions_link}#metrics) is the mean of the detection rate and "
           "one minus the false mismatch rate. Answering MISMATCH always, or never, scores 0.50.", ""]
    header = ["Puzzle", "Setup", "Detection rate", "False mismatch rate", "Balanced accuracy"]
    if reasons:
        header += [f"[Diagnosis rate]({definitions_link}#metrics)",
                   f"[Critical thinking]({definitions_link}#metrics)"]
    for model in config["models"]:
        rows = [r for r in detection_rows if r["model"] == model["name"]]
        if not rows:
            continue
        body = []
        for puzzle in dict.fromkeys(r["puzzle"] for r in rows):
            puzzle_rows = [r for r in rows if r["puzzle"] == puzzle]
            for r in puzzle_rows:
                line = [puzzle, r["setup"], rate_cell(r, "detection_rate"),
                        rate_cell(r, "false_mismatch_rate"), balanced_cell(r)]
                if reasons:
                    line += [rate_cell(r, "diagnosis_rate"), interval_cell(r, "critical_thinking")]
                body.append(line)
            body.append([puzzle, "always MISMATCH (baseline)", "1.00", "1.00", "0.50"]
                        + (["0.00", "0.00"] if reasons else []))
            fixed = puzzle_rows[0]["fixed_answer_reason"]
            if reasons and fixed != NA:
                critical = puzzle_rows[0]["fixed_answer_critical_thinking"]
                body.append([puzzle, f"always MISMATCH {fixed} (baseline)", "1.00", "1.00", "0.50",
                             number(critical * 2, 2), number(critical, 2)])
        out += [f"### {model['name']}", ""] + table(header, body)
    return out


def config_models(config: dict) -> list[str]:
    return [m["name"] for m in config["models"]]


def corruption_section(models: list[str], corruption_rows, reasons: bool = False) -> list[str]:
    """Mismatch detection split by corruption type: one table per AI model."""
    out = ["## Detection by corruption type", "",
           "The detection rate on invalid inputs, split by the kind of corruption applied.", ""]
    header = ["Puzzle", "Setup", "Corruption type", "Detection rate"] + (["Diagnosis rate"] if reasons else [])
    for model in models:
        rows = [r for r in corruption_rows if r["model"] == model]
        if rows:
            body = [[r["puzzle"], r["setup"], r["corruption_type"], rate_cell(r, "detection_rate")]
                    + ([rate_cell(r, "diagnosis_rate")] if reasons else []) for r in rows]
            out += [f"### {model}", ""] + table(header, body)
    return out


def reasons_section(models: list[str], reason_rows) -> list[str]:
    """Expected corruption type against the reason given: one table per AI model, puzzle, and setup."""
    out = ["## Mismatch reasons", "",
           "Attempts by the corruption type the input has (rows) and the mismatch reason the AI model "
           "gave (columns).", ""]
    kinds = ["none", *CUBE_CORRUPTION_TYPES]
    for model in models:
        rows = [r for r in reason_rows if r["model"] == model]
        if not rows:
            continue
        out += [f"### {model}", ""]
        for puzzle in dict.fromkeys(r["puzzle"] for r in rows):
            engine = ENGINES[puzzle]
            offered = ["none", *offered_reasons(engine)]
            decoys = set(engine.decoy_reasons())
            puzzle_rows = [r for r in rows if r["puzzle"] == puzzle]
            out += [f"#### {puzzle}", ""]
            for setup in dict.fromkeys(r["setup"] for r in puzzle_rows):
                cells = {(r["expected"], r["reason"]): r["attempts"] for r in puzzle_rows if r["setup"] == setup}
                expected = {e for e, _ in cells}
                given = {g for _, g in cells}
                expected_order = [e for e in kinds if e in expected] + sorted(expected - set(kinds))
                reason_order = [g for g in offered if g in given] + sorted(given - set(offered))
                header = ["Expected"] + ["no reason" if g == "none" else f"{g} (decoy)" if g in decoys else g
                                         for g in reason_order]
                body = [["valid input" if e == "none" else e] + [cells.get((e, g), "") or "" for g in reason_order]
                        for e in expected_order]
                out += [f"##### {setup}", ""] + table(header, body)
    return out


def metric_line(r: dict) -> list:
    """One row of a puzzle's metrics table."""
    line = [r["setup"], r["model"], r["scramble_depth"], r["validity"], r["attempts"],
            r["infrastructure_failure_count"]]
    for _, name in METRIC_COLUMNS:
        line.append(rate_cell(r, name))
    line += [
        number(r["consistency"], 2),
        number(r["latency_per_attempt_s"], 2), number(r["input_tokens_per_attempt"], 1),
        number(r["output_tokens_per_attempt"], 1), number(r["cost_per_attempt"], 4),
    ]
    return line


def metrics_section(metric_rows: list[dict]) -> list[str]:
    out = ["## Metrics", ""]
    header = ["Setup", "AI model", "Depth", "Validity", "Attempts", "Infra failures"]
    header += [title for title, _ in METRIC_COLUMNS]
    header += ["Consistency", "Latency (s)", "Input tokens", "Output tokens",
               "Cost per attempt"]
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


def attempts_section(link, release_dir: Path, attempt_rows: list[dict], reasons: bool = False) -> list[str]:
    out = ["## Attempts", ""]
    header = ["AI model", "Setup", "Attempt", "Outcome", "Moves", "Mismatch"]
    if reasons:
        header.append("Mismatch reason")
    header += ["Input tokens (excl. retries)", "Output tokens (excl. retries)", "Latency (s)"]
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
                *([r["mismatch_reason"] or ""] if reasons else []),
                r["input_tokens"], r["output_tokens"], number(r["latency_s"], 2),
            ])
        out += table(header, body)
    return out


def write_report(path, experiment_id, experiment_config, release_dir, prices, attempt_rows,
                 metric_rows, summary_rows, torn_lines: int = 0, paired_rows=(), detection_rows=(),
                 corruption_rows=(), reason_rows=()) -> None:
    path, release_dir = Path(path), Path(release_dir)

    def link(target: Path) -> str:
        """A link relative to the report, so it works on GitHub."""
        return os.path.relpath(target, path.parent).replace(os.sep, "/")

    lines = [f"# Experiment {experiment_id} on release {release_dir.name}", ""]
    lines += release_section(link, release_dir, experiment_config)
    lines += experiment_section(link, path.parent, experiment_config, prices, attempt_rows,
                                torn_lines)
    definitions = link(release_dir.parent.parent / "docs" / "definitions.md")
    reasons = has_reasons(attempt_rows)
    lines += summary_section(experiment_config, summary_rows, detection_rows, reasons, definitions)
    if detection_rows:
        lines += detection_section(definitions, experiment_config, detection_rows, reasons)
    if corruption_rows:
        lines += corruption_section(config_models(experiment_config), corruption_rows, reasons)
    if reason_rows:
        lines += reasons_section(config_models(experiment_config), reason_rows)
    if paired_rows:
        lines += comparison_section(definitions, experiment_config, paired_rows)
    lines += metrics_section(metric_rows)
    lines += attempts_section(link, release_dir, attempt_rows, reasons)
    lines += ["## Raw responses", "",
              f"Not copied here. See [raw/]({link(path.parent / 'raw')}).", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
