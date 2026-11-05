# Spec: docs/specs/engine.md
"""Defines the puzzle engine interface. Reads nothing and writes nothing.

Every engine subclasses Engine and implements all nine methods. Callers catch
IllegalMoveError and ValidityMismatchError by name.
"""

from abc import ABC, abstractmethod
from typing import Any

# A state is whatever an engine uses to hold the colours on every face.
State = Any


class IllegalMoveError(Exception):
    """Raised by apply_move() when the move is not in legal_moves()."""


class ValidityMismatchError(Exception):
    """Raised by load_state() when a state disagrees with its validity label."""


class Engine(ABC):
    """The interface every puzzle engine implements."""

    @abstractmethod
    def legal_moves(self) -> list[str]:
        """Return the puzzle's move group in standard notation."""

    @abstractmethod
    def solved_state(self) -> State:
        """Return the solved state in its standard orientation."""

    @abstractmethod
    def load_state(self, input: dict) -> State:
        """Return the state and check it against the input's validity label.

        A disagreement raises ValidityMismatchError, never a silent relabel.
        """

    @abstractmethod
    def apply_move(self, state: State, move: str) -> State:
        """Return the new state.

        Accept only moves from legal_moves() and raise IllegalMoveError on
        anything else. The validator never uses it to decide whether a move is
        legal.
        """

    @abstractmethod
    def is_solved(self, state: State) -> bool:
        """Return true when every face shows a single colour.

        The orientation of the whole puzzle does not matter.
        """

    @abstractmethod
    def scramble(self, input_seed: int, depth: int) -> tuple[State, list[str]]:
        """Return the state and the move sequence that produced it.

        Both go into the frozen input. generate derives each input seed from
        the config seed and passes it in.
        """

    @abstractmethod
    def corrupt(self, state: State, input_seed: int) -> tuple[State, str]:
        """Return a state that cannot be reached from the solved state by legal moves.

        Also return a description of the corruption applied.
        """

    @abstractmethod
    def render(self, state: State) -> str:
        """Return the text form of the state for the prompt."""

    @abstractmethod
    def is_move_token(self, token: str) -> bool:
        """Return true when the token has the shape of a move in the puzzle's notation.

        Legal or not. The validator uses it only to tell impossible moves from prose.
        """
