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

from src.evaluate.metrics import compute
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
    return tmp_path, inputs


def build(tree, changed_outcome=False) -> str:
    root, _ = tree
    release, path = root / "releases" / "1.0.0", root / "results" / "exp" / "1.0.0.md"
    rows = compute(records(changed_outcome), release, PRICES, ["M"])
    write_report(path, "exp", CONFIG, release, PRICES, *rows, torn_lines=2)
    return path.read_text(encoding="utf-8")


def test_matches_stored_expected_report(tree):
    text = build(tree)
    if os.environ.get("UPDATE_FIXTURES") == "1":
        EXPECTED.write_text(text, encoding="utf-8")
    assert text == EXPECTED.read_text(encoding="utf-8")


def test_relative_links_point_at_existing_files(tree):
    text = build(tree)
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
