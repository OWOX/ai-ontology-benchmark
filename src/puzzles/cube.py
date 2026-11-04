# Spec: docs/specs/cube.md
"""Cube engine for the 2x2 and 3x3. Reads nothing and writes nothing.

Stickers are placed in 3D, so a face turn is a rotation of the stickers in one
layer. All move tables, piece positions, and the 2x2 search tables derive from
that one placement.
"""

import random
import re
from functools import lru_cache

from src.puzzles.engine import Engine, IllegalMoveError, ValidityMismatchError

FACES = "URFDLB"
NORMAL = {"U": (0, 1, 0), "R": (1, 0, 0), "F": (0, 0, 1),
          "D": (0, -1, 0), "L": (-1, 0, 0), "B": (0, 0, -1)}
# Per face: the direction in which the row number and the column number grow.
READING = {"U": ((0, 0, 1), (1, 0, 0)), "R": ((0, -1, 0), (0, 0, -1)),
           "F": ((0, -1, 0), (1, 0, 0)), "D": ((0, 0, -1), (1, 0, 0)),
           "L": ((0, -1, 0), (0, 0, 1)), "B": ((0, -1, 0), (-1, 0, 0))}
# Corner and edge names list faces in this order, for example UFR and UF.
NAME_ORDER = {"U": 0, "D": 0, "F": 1, "B": 1, "R": 2, "L": 2}
# Whole-cube rotations of the 2x2, each written as two face turns.
# The shape of a cube move in Singmaster and WCA notation, legal or not: a face letter with an
# optional layer count and w, or a lower-case wide, slice, or rotation letter; then ' or 2 or both.
# The layer count goes with face letters only, so the puzzle name 2x2 in prose isn't a move token.
MOVE_TOKEN = re.compile(r"(?:[0-9]*[URFDLB]w?|[urfdlbMESxyz])(?:2'?|'2?)?")
ROTATIONS = (("R", "L'"), ("U", "D'"))


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _dot(u, v):
    return sum(a * b for a, b in zip(u, v))


def _turn_clockwise(vector, axis):
    """Rotate a vector a quarter turn clockwise as seen from the axis tip."""
    cross, dot = _cross(axis, vector), _dot(axis, vector)
    return tuple(axis[k] * dot - cross[k] for k in range(3))


@lru_cache(maxsize=None)
def _stickers(n):
    """Return (cubie position, normal) for every sticker, in state order."""
    out = []
    for face in FACES:
        row_dir, col_dir = READING[face]
        for row in range(n):
            for col in range(n):
                position = tuple((n - 1) * NORMAL[face][k] + (2 * row - n + 1) * row_dir[k]
                                 + (2 * col - n + 1) * col_dir[k] for k in range(3))
                out.append((position, NORMAL[face]))
    return out


@lru_cache(maxsize=None)
def _moves(n):
    """Return {move: source}, where the new state is [state[i] for i in source]."""
    stickers = _stickers(n)
    index = {sticker: i for i, sticker in enumerate(stickers)}
    table = {}
    for face in FACES:
        axis = NORMAL[face]
        source = list(range(len(stickers)))
        for i, (position, normal) in enumerate(stickers):
            if _dot(axis, position) == n - 1:
                target = (_turn_clockwise(position, axis), _turn_clockwise(normal, axis))
                source[index[target]] = i
        inverse = [0] * len(source)
        for j, i in enumerate(source):
            inverse[i] = j
        table[face] = tuple(source)
        table[face + "'"] = tuple(inverse)
        table[face + "2"] = tuple(source[i] for i in source)
    return table


def apply_move_to(n, state, move):
    return "".join(state[i] for i in _moves(n)[move])


def _face_of(n, sticker):
    return FACES[sticker // (n * n)]


@lru_cache(maxsize=None)
def _positions(n, size):
    """Return the corner (size 3) or edge (size 2) positions as sticker indices.

    A corner lists its up or down sticker first, then the others anticlockwise
    seen from outside. An edge lists its up or down sticker first, else its
    front or back sticker.
    """
    stickers = _stickers(n)
    groups = {}
    for i, (position, _) in enumerate(stickers):
        groups.setdefault(position, []).append(i)
    result = []
    for group in groups.values():
        if len(group) != size:
            continue
        if size == 2:
            group.sort(key=lambda i: NAME_ORDER[_face_of(n, i)])
        else:
            first = next(i for i in group if stickers[i][1][1] != 0)
            a, b = [i for i in group if i != first]
            if _dot(stickers[first][1], _cross(stickers[a][1], stickers[b][1])) < 0:
                a, b = b, a
            group = [first, a, b]
        result.append(tuple(group))
    return result


def _piece_name(n, position):
    return "".join(sorted((_face_of(n, i) for i in position), key=NAME_ORDER.get))


def _solved(n):
    return "".join(face * n * n for face in FACES)


def _piece_coords(n, state, size):
    """Return (permutation, orientation) of corners or edges, or None if impossible.

    The orientation is where the piece's reference colour sits in its position:
    its up or down colour, else its front or back colour.
    """
    solved = _solved(n)
    home = {}
    for number, position in enumerate(_positions(n, size)):
        colours = tuple(solved[i] for i in position)
        home[frozenset(colours)] = (number, colours)
    permutation, orientation = [], []
    for position in _positions(n, size):
        found = tuple(state[i] for i in position)
        if len(set(found)) != size or frozenset(found) not in home:
            return None
        number, colours = home[frozenset(found)]
        shift = found.index(colours[0])
        if any(found[(shift + j) % size] != colours[j] for j in range(size)):
            return None
        permutation.append(number)
        orientation.append(shift)
    return permutation, orientation


def _parity(permutation):
    inversions = sum(1 for i in range(len(permutation)) for j in range(i)
                     if permutation[j] > permutation[i])
    return inversions % 2


def _is_reachable(n, state):
    """Check well-formedness, corner twist sum, edge flip sum, and permutation parity."""
    if len(state) != 6 * n * n or any(c not in FACES for c in state):
        return False
    corners = _piece_coords(n, state, 3)
    if corners is None or len(set(corners[0])) != 8 or sum(corners[1]) % 3 != 0:
        return False
    if n == 2:
        return True
    if any(state[f * 9 + 4] != FACES[f] for f in range(6)):
        return False
    edges = _piece_coords(n, state, 2)
    if edges is None or len(set(edges[0])) != 12 or sum(edges[1]) % 2 != 0:
        return False
    return _parity(corners[0]) == _parity(edges[0])


class CubeEngine(Engine):
    """The engine for the 2x2 and 3x3 cubes."""

    def __init__(self, n: int):
        if n == 5:
            raise NotImplementedError("5x5 move group is undecided (AGENTS.md open item 5)")
        if n not in (2, 3):
            raise ValueError(f"unsupported cube size {n}")
        self.n = n

    def legal_moves(self) -> list[str]:
        return [face + suffix for face in FACES for suffix in ("", "'", "2")]

    def solved_state(self) -> str:
        return _solved(self.n)

    def load_state(self, input: dict) -> str:
        state, label = input["state"], input["validity"]
        if label not in ("valid", "invalid") or _is_reachable(self.n, state) != (label == "valid"):
            raise ValidityMismatchError(f"state labelled {label!r} disagrees with the reachability check")
        return state

    def apply_move(self, state: str, move: str) -> str:
        if move not in self.legal_moves():
            raise IllegalMoveError(f"not a legal move: {move!r}")
        return apply_move_to(self.n, state, move)

    def is_solved(self, state: str) -> bool:
        size = self.n * self.n
        return all(len(set(state[f * size:(f + 1) * size])) == 1 for f in range(6))

    def scramble(self, input_seed: int, depth: int) -> tuple[str, list[str]]:
        if depth < 1:
            raise ValueError("scramble depth must be at least 1")
        rng = random.Random(input_seed)
        while True:
            state, moves = self.solved_state(), []
            for _ in range(depth):
                options = [m for m in self.legal_moves() if not moves or m[0] != moves[-1][0]]
                moves.append(rng.choice(options))
                state = self.apply_move(state, moves[-1])
            if not self.is_solved(state):
                return state, moves

    def corrupt(self, state: str, input_seed: int) -> tuple[str, str]:
        rng = random.Random(input_seed)
        size = rng.choice((3,) if self.n == 2 else (3, 2))
        position = rng.choice(_positions(self.n, size))
        old = [state[i] for i in position]
        name = _piece_name(self.n, position)
        if size == 2:
            new, description = old[::-1], f"flipped edge {name}"
        elif rng.random() < 0.5:
            new, description = [old[1], old[2], old[0]], f"twisted corner {name} clockwise"
        else:
            new, description = [old[2], old[0], old[1]], f"twisted corner {name} anticlockwise"
        chars = list(state)
        for i, colour in zip(position, new):
            chars[i] = colour
        return "".join(chars), description

    def render(self, state: str) -> str:
        size = self.n * self.n
        blocks = []
        for f, face in enumerate(FACES):
            rows = [" ".join(state[f * size + r * self.n:f * size + (r + 1) * self.n])
                    for r in range(self.n)]
            blocks.append("\n".join([face] + rows))
        return "\n\n".join(blocks)

    def is_move_token(self, token: str) -> bool:
        return MOVE_TOKEN.fullmatch(token) is not None
