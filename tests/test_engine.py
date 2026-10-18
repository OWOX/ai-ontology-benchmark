# Spec: docs/specs/engine.md
"""Tests for the engine interface. Reads and writes no files."""

import pytest

from src.puzzles.engine import Engine, IllegalMoveError, ValidityMismatchError

METHODS = [
    "legal_moves",
    "solved_state",
    "load_state",
    "apply_move",
    "is_solved",
    "scramble",
    "corrupt",
    "render",
    "reference_length",
]


def make_subclass(skip: str | None = None) -> type:
    """Build an Engine subclass that implements every method except `skip`."""
    namespace = {name: (lambda self, *args: None) for name in METHODS if name != skip}
    return type("Fake", (Engine,), namespace)


def test_full_subclass_instantiates() -> None:
    assert isinstance(make_subclass()(), Engine)


@pytest.mark.parametrize("missing", METHODS)
def test_missing_method_raises_type_error(missing: str) -> None:
    with pytest.raises(TypeError):
        make_subclass(skip=missing)()


def test_abstract_methods_are_the_nine_in_order() -> None:
    assert sorted(Engine.__abstractmethods__) == sorted(METHODS)


def test_exceptions_are_exceptions() -> None:
    assert issubclass(IllegalMoveError, Exception)
    assert issubclass(ValidityMismatchError, Exception)
