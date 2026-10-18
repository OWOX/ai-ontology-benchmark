# Spec: docs/specs/prompts.md
"""Tests for prompts. They copy the repo templates into a temporary folder and call no AI model."""

import json
import shutil

import pytest

from src.generate.generate import build_inputs
from src.puzzles.cube import CubeEngine
from src.puzzles.registry import get_engine
from src.run.prompts import SETUPS, build_prompt, prompt_versions

CONFIG = {
    "seed": 3,
    "puzzles": ["2x2", "3x3"],
    "scramble_depths": [4, 8],
    "scramble_count": 3,
    "valid_invalid_split": 0.5,
}
INPUTS = [json.loads(line) for line in build_inputs(CONFIG, "1").splitlines()]


@pytest.fixture
def templates(tmp_path):
    target = tmp_path / "prompts"
    shutil.copytree("prompts", target)
    return target


def test_repeated_calls_are_identical(templates):
    for setup in SETUPS:
        assert build_prompt(templates, INPUTS[0], setup) == build_prompt(templates, INPUTS[0], setup)


def test_prompt_never_contains_scramble(templates):
    for row in INPUTS:
        for setup in SETUPS:
            assert " ".join(row["scramble"]) not in build_prompt(templates, row, setup)


def test_prescriptive_lists_legal_moves(templates):
    for row in INPUTS:
        text = build_prompt(templates, row, "prescriptive")
        assert " ".join(get_engine(row["puzzle"]).legal_moves()) in text
        assert "{" not in text.replace('{"moves": [...], "mismatch": true|false}', "")


def test_templates_ask_for_json_and_start_with_placeholder_line(templates):
    for setup in SETUPS:
        for puzzle in ("2x2", "3x3"):
            text = (templates / setup / f"{puzzle}.txt").read_text()
            assert text.startswith("PLACEHOLDER: real text pending open item 1.\n")
            assert '{"moves": [...], "mismatch": true|false}' in text


def test_changing_a_template_changes_only_its_version(templates):
    before = prompt_versions(templates, INPUTS)
    path = templates / "descriptive" / "3x3.txt"
    path.write_text(path.read_text().replace("Here", "Hers", 1))
    after = prompt_versions(templates, INPUTS)
    for setup in SETUPS:
        for puzzle in ("2x2", "3x3"):
            same = before[setup][puzzle] == after[setup][puzzle]
            assert same == ((setup, puzzle) != ("descriptive", "3x3"))
    assert all(len(v) == 12 for s in after.values() for v in s.values())


def test_patching_render_changes_every_version_for_that_puzzle(templates, monkeypatch):
    before = prompt_versions(templates, INPUTS)
    monkeypatch.setattr(CubeEngine, "render", lambda self, state: "changed " + state)
    after = prompt_versions(templates, INPUTS)
    for setup in SETUPS:
        for puzzle in ("2x2", "3x3"):
            assert before[setup][puzzle] != after[setup][puzzle]


def test_patching_render_for_one_puzzle_leaves_the_other(templates, monkeypatch):
    before = prompt_versions(templates, INPUTS)
    engine = get_engine("2x2")
    monkeypatch.setattr(engine, "render", lambda state: "changed")
    after = prompt_versions(templates, INPUTS)
    for setup in SETUPS:
        assert before[setup]["2x2"] != after[setup]["2x2"]
        assert before[setup]["3x3"] == after[setup]["3x3"]


def test_unknown_placeholder_raises(templates):
    path = templates / "no_model" / "2x2.txt"
    path.write_text(path.read_text() + "\n{scramble}\n")
    row = next(r for r in INPUTS if r["puzzle"] == "2x2")
    with pytest.raises(ValueError):
        build_prompt(templates, row, "no_model")
    with pytest.raises(ValueError):
        prompt_versions(templates, INPUTS)


def test_legal_moves_placeholder_only_in_prescriptive(templates):
    path = templates / "descriptive" / "2x2.txt"
    path.write_text(path.read_text() + "\n{legal_moves}\n")
    row = next(r for r in INPUTS if r["puzzle"] == "2x2")
    with pytest.raises(ValueError):
        build_prompt(templates, row, "descriptive")


def test_missing_template_raises(templates):
    (templates / "prescriptive" / "3x3.txt").unlink()
    row = next(r for r in INPUTS if r["puzzle"] == "3x3")
    with pytest.raises(ValueError):
        build_prompt(templates, row, "prescriptive")
    with pytest.raises(ValueError):
        prompt_versions(templates, INPUTS)
