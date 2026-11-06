# Spec: docs/specs/report.md
"""Tests for report. A small tree (one release, one experiment, two inputs, one AI model, three
setups) is built in tmp_path and write_report is called with what compute() returns. Set
UPDATE_FIXTURES=1 to regenerate tests/fixtures/report_expected.md.
"""

import json
import os
import re
from pathlib import Path

import pytest

from src.evaluate.metrics import compute, detection_rows, paired_tests
from src.evaluate.report import write_report
from src.run.prompts import SETUPS
from test_evaluate import answer, make_inputs, raw

EXPECTED = Path(__file__).parent / "fixtures" / "report_expected.md"
PROMPT_MARKER = "SECRET-PROMPT-TEXT"
CONFIG = {
    "release": "1.0.0", "attempts": 2, "retry_cap": 1, "max_output_tokens": 100,
    "budget": {"per_request_usd": 0.5, "per_model_usd": 5.0, "per_experiment_usd": 10.0},
    "models": [{"name": "M", "provider": "fake", "api_model_id": "m-1", "kind": "system-2", "params": {"temperature": 0.5}}],
}
PRICES = {"M": {"price_input_per_mtok": 1000.0, "price_output_per_mtok": 2000.0}}


def records(changed_outcome: bool = False) -> list[dict]:
    out = []
    for setup in SETUPS:
        out += [
            raw("2x2-d1-001", 1, answer(["R"]), "success", 1.5, setup=setup),
            raw("2x2-d1-001", 2, answer(["U"]), "failure", 2.0, setup=setup),
            raw("2x2-d1-001-x", 1, answer([]), "success", 0.5, setup=setup),
            raw("2x2-d1-001-x", 2, " \n", "malformed_output", 0.5, setup=setup),
        ]
    if changed_outcome:
        out[1]["outcome"] = "success"
    return out


@pytest.fixture
def tree(tmp_path):
    release = tmp_path / "releases" / "1.0.0"
    (release / "prompts" / "no_model").mkdir(parents=True)
    (release / "prompts" / "no_model" / "2x2.txt").write_text(PROMPT_MARKER + " {state}", encoding="utf-8")
    (release / "README.md").write_text("# Release 1.0.0\n", encoding="utf-8")
    inputs = [row for row in make_inputs() if row["input_id"].startswith("2x2-d1-001")]
    (release / "inputs.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in inputs), encoding="utf-8")
    (release / "manifest.json").write_text(json.dumps({"assessment_sha256": "abc123"}), encoding="utf-8")
    results = tmp_path / "results" / "exp"
    (results / "raw").mkdir(parents=True)
    (results / "experiment.toml").write_text("release = '1.0.0'\n", encoding="utf-8")
    (results / "prices.toml").write_text("[M]\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "definitions.md").write_text("# Definitions\n", encoding="utf-8")
    return tmp_path, inputs


def build(tree, changed_outcome=False, paired_rows=(), with_paired=False, detection=(), corruption=(), config=CONFIG) -> str:
    root, _ = tree
    release, path = root / "releases" / "1.0.0", root / "results" / "exp" / "1.0.0.md"
    rows = compute(records(changed_outcome), release, PRICES, ["M"])
    if with_paired:
        paired_rows = paired_tests(rows[0], ["M"])
        detection = detection_rows(rows[0], ["M"])
    write_report(path, "exp", config, release, PRICES, *rows, torn_lines=2, paired_rows=paired_rows,
                 detection_rows=detection, corruption_rows=corruption)
    return path.read_text(encoding="utf-8")


def test_matches_stored_expected_report(tree):
    text = build(tree, with_paired=True)
    if os.environ.get("UPDATE_FIXTURES") == "1":
        EXPECTED.write_text(text, encoding="utf-8")
    assert text == EXPECTED.read_text(encoding="utf-8")


def test_relative_links_point_at_existing_files(tree):
    text = build(tree, with_paired=True)
    assert "../../docs/definitions.md#metrics" in text
    folder = tree[0] / "results" / "exp"
    links = re.findall(r"\]\(([^)]+)\)", text)
    assert links
    for link in links:
        assert not link.startswith("/") and "://" not in link
        assert (folder / link.split("#")[0]).resolve().exists(), link
    assert "../../releases/1.0.0/inputs.jsonl#L2" in text  # the invalid input is on line 2


def test_no_prompt_text_and_no_rendered_state(tree):
    text = build(tree)
    assert PROMPT_MARKER not in text
    for row in tree[1]:
        assert row["state"] not in text


def test_title_and_release_lines(tree):
    lines = build(tree).splitlines()
    assert lines[0] == "# Experiment exp on release 1.0.0"
    assert "[1.0.0, tag `release-1.0.0`](../../releases/1.0.0/README.md)" in lines[2]
    assert "Assessment hash: `abc123`" in build(tree)


def test_summary_tables_never_mix_validity(tree):
    text = build(tree)
    summary = text.split("## Summary")[1].split("## Metrics")[0]
    valid, invalid = summary.split("#### Invalid inputs")
    assert "False mismatch rate" in valid and "Cost per success" in valid and "Mismatch detection" not in valid
    assert "Mismatch detection rate" in invalid and "False mismatch" not in invalid and "Cost" not in invalid
    assert "n=2" in valid and "n=2" in invalid


def test_changed_outcome_shown_as_stored_arrow_current(tree):
    assert "→" not in build(tree)
    assert "| success → failure |" in build(tree, changed_outcome=True)


def test_experiment_section_shows_budgets_and_spend(tree):
    text = build(tree)
    assert "Budgets in force (USD): request 0.5, AI model 5.0, experiment 10.0." in text
    spent = sum(r["cost"] for r in compute(records(), tree[0] / "releases" / "1.0.0", PRICES, ["M"])[0])
    assert f"| M | {spent:.4f} |" in text and f"| Total | {spent:.4f} |" in text


def test_puzzles_line_only_when_the_config_sets_it(tree, monkeypatch):
    assert "Puzzles:" not in build(tree)
    monkeypatch.setitem(CONFIG, "puzzles", ["2x2", "3x3"])
    assert "\nPuzzles: 2x2, 3x3\n" in build(tree)


def test_kind_column_shows_the_config_value_or_not_set(tree):
    assert "| M | fake | m-1 | system-2 | m-1 | temperature=0.5 |" in build(tree)
    model = {k: v for k, v in CONFIG["models"][0].items() if k != "kind"}
    root, _ = tree
    release, path = root / "releases" / "1.0.0", root / "results" / "exp" / "1.0.0.md"
    rows = compute(records(), release, PRICES, ["M"])
    write_report(path, "exp", dict(CONFIG, models=[model]), release, PRICES, *rows, torn_lines=0)
    text = path.read_text(encoding="utf-8")
    assert "| AI model | Provider | API model id | Kind | Served model ids | Params |" in text
    assert "| M | fake | m-1 | not set | m-1 | temperature=0.5 |" in text


def paired(**over) -> dict:
    row = {"model": "M", "puzzle": "2x2", "validity": "valid", "metric": "success_rate",
           "setup_a": "no_model", "setup_b": "descriptive", "inputs_paired": 10, "a_higher": 2,
           "b_higher": 8, "mean_difference": 0.3, "p_value": 0.109375, "p_holm": 0.328125,
           "significant": False}
    row.update(over)
    return row


def test_setup_comparison_absent_without_paired_rows(tree):
    text = build(tree)
    assert "Setup comparison" not in text
    assert text == build(tree, paired_rows=[])


def test_setup_comparison_sits_between_summary_and_metrics(tree):
    text = build(tree, paired_rows=[paired()])
    assert text.index("## Summary") < text.index("## Setup comparison") < text.index("## Metrics")
    assert "[paired setup test](../../docs/definitions.md#metrics)" in text
    assert "### M\n\n#### 2x2\n\n" in text.split("## Setup comparison")[1]
    assert ("| Validity | Metric | Setups | Inputs paired | A higher | B higher | Mean difference "
            "| p | Holm p | Significant |") in text
    assert "| valid | success_rate | no_model vs descriptive | 10 | 2 | 8 | 0.30 | 0.109 | 0.328 | no |" in text


def test_setup_comparison_shows_yes_and_na(tree):
    rows = [paired(significant=True),
            paired(metric="hallucination_rate", inputs_paired=0, a_higher=0, b_higher=0,
                   mean_difference="n/a", p_value="n/a", p_holm="n/a", significant="n/a")]
    text = build(tree, paired_rows=rows)
    assert "| 0.30 | 0.109 | 0.328 | yes |" in text
    assert "| 0 | 0 | 0 | n/a | n/a | n/a | n/a |" in text


def test_setup_comparison_shows_small_p_as_less_than(tree):
    text = build(tree, paired_rows=[paired(p_value=1.9e-06, p_holm=0.0005), paired(metric="x", p_value=0.001, p_holm=0.04)])
    assert "| <0.001 | <0.001 | yes |" not in text
    assert "| <0.001 | <0.001 |" in text
    assert "| 0.001 | 0.040 |" in text


def detection_row(**over) -> dict:
    row = {"model": "M", "puzzle": "2x2", "setup": "no_model", "detection_rate": 0.75,
           "detection_rate_low": 0.5, "detection_rate_high": 1.0, "detection_rate_n": 4, "detection_rate_inputs": 4,
           "false_mismatch_rate": 0.25, "false_mismatch_rate_low": "n/a", "false_mismatch_rate_high": "n/a",
           "false_mismatch_rate_n": 4, "false_mismatch_rate_inputs": 1,
           "balanced_accuracy": 0.75, "balanced_accuracy_low": "n/a", "balanced_accuracy_high": "n/a"}
    row.update(over)
    return row


def test_mismatch_detection_sits_after_summary_with_baseline_row(tree):
    text = build(tree, detection=[detection_row()])
    assert text.index("## Summary") < text.index("## Mismatch detection") < text.index("## Metrics")
    assert "[Balanced accuracy](../../docs/definitions.md#metrics)" in text
    assert "| Puzzle | Setup | Detection rate | False mismatch rate | Balanced accuracy |" in text
    assert "| 2x2 | no_model | 0.75 (0.50–1.00) n=4, 4 inputs | 0.25 (n/a) n=4, 1 input | 0.75 |" in text
    assert "| 2x2 | always MISMATCH (baseline) | 1.00 | 1.00 | 0.50 |" in text


def test_mismatch_detection_absent_without_rows(tree):
    assert "## Mismatch detection" not in build(tree)


def test_mismatch_detection_shows_na(tree):
    text = build(tree, detection=[detection_row(detection_rate="n/a", detection_rate_low="n/a", detection_rate_high="n/a", detection_rate_n=0, detection_rate_inputs=0, balanced_accuracy="n/a")])
    assert "| 2x2 | no_model | n/a n=0, 0 inputs | 0.25 (n/a) n=4, 1 input | n/a |" in text


def test_detection_by_corruption_type_sits_after_mismatch_detection(tree):
    row = {"model": "M", "puzzle": "2x2", "setup": "no_model", "corruption_type": "twisted corner",
           "detection_rate": 0.5, "detection_rate_low": 0.25, "detection_rate_high": 0.75,
           "detection_rate_n": 4, "detection_rate_inputs": 2}
    text = build(tree, detection=[detection_row()], corruption=[row])
    assert text.index("## Mismatch detection") < text.index("## Detection by corruption type") < text.index("## Metrics")
    assert "| Puzzle | Setup | Corruption type | Detection rate |" in text
    assert "| 2x2 | no_model | twisted corner | 0.50 (0.25\u20130.75) n=4, 2 inputs |" in text
    assert "## Detection by corruption type" not in build(tree)


def test_experiment_section_names_the_reasoning_effort(tree):
    assert "Reasoning effort: provider default." in build(tree)
    assert "Reasoning effort: medium." in build(tree, config=dict(CONFIG, reasoning_effort="medium"))


def test_decision_served_models_are_listed_one_by_one(tree):
    root, _ = tree
    release, path = root / "releases" / "1.0.0", root / "results" / "exp" / "1.0.0.md"
    recs = records()
    recs[0]["served_model"] = "a,b"
    recs[1]["served_model"] = "b"
    rows = compute(recs, release, PRICES, ["M"])
    write_report(path, "exp", CONFIG, release, PRICES, *rows, torn_lines=0)
    assert "| M | fake | m-1 | system-2 | a, b, m-1 | temperature=0.5 |" in path.read_text(encoding="utf-8")
