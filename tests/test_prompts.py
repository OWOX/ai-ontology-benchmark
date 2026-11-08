# Spec: docs/specs/prompts.md
"""Tests for prompts. They copy the repo templates into a temporary folder and call no AI model."""

import json
import shutil
from pathlib import Path

import pytest

from src.generate.generate import build_inputs
from src.puzzles.cube import CubeEngine
from src.puzzles.registry import ENGINES, get_engine
from src.run.prompts import (SETUPS, build_prompt, decision_prompt_versions, decision_questions, fill_template,
                             prompt_versions, uses_mismatch_reasons)
from src.validator import offered_reasons

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


def test_fill_template_equals_build_prompt(templates):
    for row in INPUTS:
        for setup in SETUPS:
            text = (templates / setup / f"{row['puzzle']}.txt").read_text(encoding="utf-8")
            assert fill_template(text, row, setup) == build_prompt(templates, row, setup)


def test_prompt_never_contains_scramble(templates):
    for row in INPUTS:
        for setup in SETUPS:
            assert " ".join(row["scramble"]) not in build_prompt(templates, row, setup)


def test_prescriptive_lists_legal_moves(templates):
    for row in INPUTS:
        text = build_prompt(templates, row, "prescriptive")
        assert " ".join(get_engine(row["puzzle"]).legal_moves()) in text
        assert "{" not in text


def test_templates_ask_for_lines_and_are_not_placeholders(templates):
    for setup in SETUPS:
        for puzzle in ("2x2", "3x3"):
            text = (templates / setup / f"{puzzle}.txt").read_text()
            assert "PLACEHOLDER" not in text
            assert text.endswith(
                "If the state cannot be reached from the solved state by legal moves, reply with the single line "
                "MISMATCH, one space, and the reason, exactly as written in this list: {mismatch_reasons}. Use other "
                "when none of them fits. Write nothing else.\nOtherwise reply with the moves that solve it, in the order they are "
                "applied, one move per line, and nothing else.\n")
            assert "JSON" not in text


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
        "criteria": {"move_1": "R", "move_2": "U'", "done": "d", "mismatch": "m"},
    }
    assert list(q) == ["next_move"]


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
                        lambda q, legal, reasons=None: {**structure(q, legal, reasons), "mismatch": {"type": "other"}})
    assert prompts.decision_prompt_versions(templates, INPUTS) != before
    assert prompt_versions(templates, INPUTS) == llm_before


def test_parse_questions_reads_text_and_names_the_source():
    from src.run.prompts import parse_questions
    text = "next_move: pick one\ndone: solved\nmismatch: unreachable\n"
    assert parse_questions(text, "here") == {"next_move": "pick one", "done": "solved", "mismatch": "unreachable"}
    with pytest.raises(ValueError, match="here.*mismatch"):
        parse_questions("next_move: a\ndone: b\n", "here")


def test_every_puzzle_has_a_template_under_each_setup():
    root = Path(__file__).resolve().parent.parent / "prompts"
    for setup in SETUPS:
        for puzzle in ENGINES:
            text = (root / setup / f"{puzzle}.txt").read_text(encoding="utf-8")
            assert "{state}" in text
            assert ("{legal_moves}" in text) == (setup == "prescriptive")


def test_template_is_read_once_and_reread_after_an_edit(templates, monkeypatch):
    reads = []
    original = Path.read_text

    def counting(self, *args, **kwargs):
        reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    inp = next(i for i in INPUTS if i["puzzle"] == "2x2")
    first = build_prompt(templates, inp, "descriptive")
    assert build_prompt(templates, inp, "descriptive") == first
    assert len(reads) == 1
    path = templates / "descriptive" / "2x2.txt"
    path.write_text(path.read_text(encoding="utf-8") + "Extra line.\n", encoding="utf-8")
    assert build_prompt(templates, inp, "descriptive") == first + "Extra line.\n"


def test_decision_questions_with_reasons():
    q = decision_questions({"next_move": "n", "done": "d", "mismatch": "m"}, ["R"], ["a", "other"])
    assert q["next_move"]["criteria"] == {
        "move_1": "R", "done": "d", "mismatch_1": "m Reason: a.", "mismatch_2": "m Reason: other."}


def test_text_lists_every_offered_reason_in_order(templates):
    for puzzle in ("2x2", "3x3"):
        row = next(r for r in INPUTS if r["puzzle"] == puzzle)
        engine = get_engine(puzzle)
        reasons = offered_reasons(engine)
        listed = ", ".join(f"`{r}`" for r in reasons)
        for setup in SETUPS:
            text = build_prompt(templates, row, setup)
            assert "{mismatch_reasons}" not in text
            assert f"in this list: {listed}." in text
            assert reasons[-1] == "other"
    assert "`twisted centre`" in build_prompt(templates, next(r for r in INPUTS if r["puzzle"] == "3x3"), "no_model")


def strip_reasons(templates, names=None):
    for path in templates.glob("*/*.txt"):
        if names is None or f"{path.parent.name}/{path.name}" in names:
            path.write_text(path.read_text().replace("{mismatch_reasons}", "the listed reason"))


def test_uses_mismatch_reasons(templates):
    assert uses_mismatch_reasons(templates) is True
    strip_reasons(templates, {"no_model/2x2.txt"})
    with pytest.raises(ValueError, match="no_model/2x2.txt"):
        uses_mismatch_reasons(templates)
    strip_reasons(templates)
    assert uses_mismatch_reasons(templates) is False


def test_decision_versions_without_placeholder_use_the_plain_mismatch_option(templates):
    with_reasons = decision_prompt_versions(templates, INPUTS)
    strip_reasons(templates)
    without = decision_prompt_versions(templates, INPUTS)
    assert without != with_reasons
    for setup in SETUPS:
        for puzzle in ("2x2", "3x3"):
            assert without[setup][puzzle] != with_reasons[setup][puzzle]
