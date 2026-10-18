# Spec: docs/specs/generate.md
"""Tests for generate. They use small in-memory configs and touch no files."""

import json

from src.generate.generate import build_inputs
from src.puzzles.registry import get_engine

CONFIG = {
    "seed": 7,
    "puzzles": ["2x2", "3x3"],
    "scramble_depths": [3, 6],
    "scramble_count": 4,
    "valid_invalid_split": 0.5,
}


def parse(text):
    return [json.loads(line) for line in text.splitlines()]


def test_same_config_gives_identical_text():
    assert build_inputs(CONFIG, "1") == build_inputs(CONFIG, "1")


def test_line_count_follows_split():
    text = build_inputs(CONFIG, "1")
    per_cell = 4 + round(0.5 * 4)
    assert len(text.splitlines()) == 2 * 2 * per_cell
    assert text.endswith("\n")
    odd = dict(CONFIG, scramble_count=5, valid_invalid_split=0.3)
    assert len(build_inputs(odd, "1").splitlines()) == 2 * 2 * (5 + round(0.3 * 5))


def test_every_input_loads_and_sources_exist():
    rows = parse(build_inputs(CONFIG, "2"))
    ids = {row["input_id"] for row in rows}
    for row in rows:
        get_engine(row["puzzle"]).load_state(row)
        assert row["input_set_id"] == "2"
        if row["validity"] == "invalid":
            assert row["source_input_id"] in ids
            assert row["input_id"] == row["source_input_id"] + "-x"
            assert row["corruption"]
        else:
            assert row["source_input_id"] is None and row["corruption"] is None


def test_ids_and_seeds_are_unique_and_order_is_right():
    rows = parse(build_inputs(CONFIG, "1"))
    assert len({r["input_id"] for r in rows}) == len(rows)
    assert len({r["input_seed"] for r in rows}) == len(rows)
    assert rows[0]["input_id"] == "2x2-d3-001"
    assert rows[1]["input_id"] == "2x2-d3-001-x"
    assert rows[2]["input_id"] == "2x2-d3-002"
    assert rows[3]["input_id"] == "2x2-d3-002-x"
    assert rows[4]["input_id"] == "2x2-d3-003"
    assert rows[6]["input_id"] == "2x2-d6-001"
