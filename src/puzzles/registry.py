# Spec: docs/specs/registry.md
"""Registry of puzzle engines. Reads nothing and writes nothing."""

from src.puzzles.cube import CubeEngine
from src.puzzles.engine import Engine

# The only list of puzzles in the code. 5x5 is added when open item 5 is settled.
ENGINES: dict[str, Engine] = {
    "2x2": CubeEngine(2),
    "3x3": CubeEngine(3),
}


def get_engine(name: str) -> Engine:
    """Return the engine for a puzzle name, or raise KeyError listing the known names."""
    if name not in ENGINES:
        known = ", ".join(ENGINES)
        raise KeyError(f"unknown puzzle {name!r}; known puzzles: {known}")
    return ENGINES[name]
