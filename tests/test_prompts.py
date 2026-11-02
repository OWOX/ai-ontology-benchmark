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


def test_templates_ask_for_json_and_are_not_placeholders(templates):
    for setup in SETUPS:
        for puzzle in ("2x2", "3x3"):
            text = (templates / setup / f"{puzzle}.txt").read_text()
            assert "PLACEHOLDER" not in text
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


def test_template_without_state_refused(templates):
    (templates / "no_model" / "2x2.txt").write_text("Solve the puzzle.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="state"):
        build_prompt(templates, INPUTS[0], "no_model")


def test_prescriptive_template_without_legal_moves_refused(templates):
    (templates / "prescriptive" / "2x2.txt").write_text("{state}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="legal_moves"):
        build_prompt(templates, INPUTS[0], "prescriptive")
    with pytest.raises(ValueError, match="legal_moves"):
        prompt_versions(templates, INPUTS)


def test_decision_state():
    from src.run.prompts import decision_state
    assert decision_state("P", []) == "P\n\nMoves so far: none"
    assert decision_state("P", ["R", "U'"]) == "P\n\nMoves so far: R U'"


def test_decision_questions_ids():
    from src.run.prompts import decision_questions
    q = decision_questions({"next_move": "n", "done": "d", "mismatch": "m"}, ["R", "U'"])
    assert q["next_move"] == {
        "type": "choice", "instructions": "n",
        "criteria": {"move_1": "R", "move_2": "U'", "done": "d"},
    }
    assert q["mismatch"] == {"type": "noul", "instructions": "m"}


def test_load_questions_reads_the_repo_file(templates):
    from src.run.prompts import load_questions
    q = load_questions(templates)
    assert set(q) == {"next_move", "done", "mismatch"}
    assert q["done"] == "The moves so far solve the puzzle."


def test_load_questions_missing_key(tmp_path):
    from src.run.prompts import load_questions
    (tmp_path / "decision").mkdir()
    (tmp_path / "decision" / "questions.txt").write_text("next_move: n\ndone: d\n")
    with pytest.raises(ValueError, match="mismatch"):
        load_questions(tmp_path)


def test_load_questions_missing_file(tmp_path):
    from src.run.prompts import load_questions
    with pytest.raises(ValueError, match="questions.txt"):
        load_questions(tmp_path)


def test_decision_versions_change_with_questions(templates):
    from src.run.prompts import decision_prompt_versions
    before = decision_prompt_versions(templates, INPUTS)
    llm_before = prompt_versions(templates, INPUTS)
    path = templates / "decision" / "questions.txt"
    path.write_text(path.read_text().replace("Pick done", "Choose done", 1))
    after = decision_prompt_versions(templates, INPUTS)
    assert set(after) == set(SETUPS)
    for setup in SETUPS:
        for puzzle in ("2x2", "3x3"):
            assert len(after[setup][puzzle]) == 12
            assert before[setup][puzzle] != after[setup][puzzle]
    assert prompt_versions(templates, INPUTS) == llm_before


def test_decision_versions_change_with_a_template(templates):
    from src.run.prompts import decision_prompt_versions
    before = decision_prompt_versions(templates, INPUTS)
    path = templates / "descriptive" / "3x3.txt"
    path.write_text(path.read_text().replace("Here", "Hers", 1))
    after = decision_prompt_versions(templates, INPUTS)
    for setup in SETUPS:
        for puzzle in ("2x2", "3x3"):
            assert (before[setup][puzzle] == after[setup][puzzle]) == ((setup, puzzle) != ("descriptive", "3x3"))


def test_decision_versions_follow_what_is_sent(templates, monkeypatch):
    from src.run import prompts
    before = prompts.decision_prompt_versions(templates, INPUTS)
    llm_before = prompt_versions(templates, INPUTS)
    original = prompts.decision_state
    monkeypatch.setattr(prompts, "decision_state", lambda p, moves: original(p, moves).replace("Moves so far", "Moves"))
    assert prompts.decision_prompt_versions(templates, INPUTS) != before
    assert prompt_versions(templates, INPUTS) == llm_before
    monkeypatch.setattr(prompts, "decision_state", original)
    assert prompts.decision_prompt_versions(templates, INPUTS) == before
    structure = prompts.decision_questions
    monkeypatch.setattr(prompts, "decision_questions",
                        lambda q, legal: {**structure(q, legal), "mismatch": {"type": "other"}})
    assert prompts.decision_prompt_versions(templates, INPUTS) != before
    assert prompt_versions(templates, INPUTS) == llm_before
