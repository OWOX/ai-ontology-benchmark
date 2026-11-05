# Spec: docs/specs/registry.md
"""Tests for the puzzle registry. They read nothing and write nothing."""

import pytest

from src.puzzles.engine import Engine
from src.puzzles.registry import ENGINES, get_engine


def test_every_name_resolves_to_an_engine():
    assert set(ENGINES) == {"2x2", "3x3", "4x4", "5x5"}
    for name in ENGINES:
        assert isinstance(get_engine(name), Engine)


def test_unknown_name_lists_known_names():
    with pytest.raises(KeyError) as error:
        get_engine("6x6")
    assert "2x2" in str(error.value)
    assert "3x3" in str(error.value)
    assert "5x5" in str(error.value)
