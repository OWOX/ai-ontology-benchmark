# Spec: docs/specs/cube.md
"""Cube engine for the 2x2, 3x3, 4x4, and 5x5. Reads nothing and writes nothing.

Stickers are placed in 3D, so a face turn is a rotation of the stickers in one
layer. All move tables, piece positions, and the 2x2 search tables derive from
that one placement. The 4x4 and 5x5 add wide turns of the two outer layers on one side.
"""

import random
from collections import Counter, deque
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
        turns = [(face, n - 1)] + ([(face + "w", n - 3)] if n >= 4 else [])
        for name, depth in turns:
            source = list(range(len(stickers)))
            for i, (position, normal) in enumerate(stickers):
                if _dot(axis, position) >= depth:
                    target = (_turn_clockwise(position, axis), _turn_clockwise(normal, axis))
                    source[index[target]] = i
            inverse = [0] * len(source)
            for j, i in enumerate(source):
                inverse[i] = j
            table[name] = tuple(source)
            table[name + "'"] = tuple(inverse)
            table[name + "2"] = tuple(source[i] for i in source)
    return table


def apply_move_to(n, state, move):
    return "".join(state[i] for i in _moves(n)[move])


def _face_of(n, sticker):
    return FACES[sticker // (n * n)]


@lru_cache(maxsize=None)
def _cubies(n):
    """Return {cubie position: sticker indices}."""
    groups = {}
    for i, (position, _) in enumerate(_stickers(n)):
        groups.setdefault(position, []).append(i)
    return groups


@lru_cache(maxsize=None)
def _positions(n, size):
    """Return the corner (size 3) or middle edge (size 2) positions as sticker indices.

    A corner lists its up or down sticker first, then the others anticlockwise
    seen from outside. An edge lists its up or down sticker first, else its
    front or back sticker.
    """
    stickers = _stickers(n)
    result = []
    for position, group in _cubies(n).items():
        if len(group) != size or (size == 2 and 0 not in position):
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


def _wing_name(n, position):
    """Return the edge a wing sits on and the face whose end of the edge it is nearer, as UF near R."""
    cubie = _stickers(n)[position[0]][0]
    axis = next(k for k in range(3) if abs(cubie[k]) < n - 1)
    near = next(face for face in FACES if NORMAL[face][axis] == (1 if cubie[axis] > 0 else -1))
    return f"{_piece_name(n, position)} near {near}"


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


@lru_cache(maxsize=None)
def _destinations(n):
    """Return, for each move, where every sticker goes."""
    out = []
    for source in _moves(n).values():
        destination = [0] * len(source)
        for j, i in enumerate(source):
            destination[i] = j
        out.append(tuple(destination))
    return out


def _orbit(n, start, step):
    """Return everything reachable from start by applying step(item, destination) for each move."""
    seen, queue = {start}, deque([start])
    while queue:
        item = queue.popleft()
        for destination in _destinations(n):
            new = step(item, destination)
            if new not in seen:
                seen.add(new)
                queue.append(new)
    return seen


@lru_cache(maxsize=None)
def _wings(n):
    """Return the wing slots (4x4 and 5x5) as pairs of sticker indices.

    A wing is an edge piece off the middle of its edge. A pair lists the two
    stickers in the order that the first wing's pair reaches that slot, so a
    wing shows its colours in the same order in every slot it can reach.
    """
    slots = [sorted(group, key=lambda i: NAME_ORDER[_face_of(n, i)])
             for position, group in _cubies(n).items() if len(group) == 2 and 0 not in position]
    reach = _orbit(n, tuple(slots[0]), lambda pair, d: (d[pair[0]], d[pair[1]]))
    by_slot = {frozenset(pair): pair for pair in reach}
    return [by_slot[frozenset(slot)] for slot in slots]


@lru_cache(maxsize=None)
def _wing_colours(n):
    solved = _solved(n)
    return sorted((solved[x], solved[y]) for x, y in _wings(n))


@lru_cache(maxsize=None)
def _centre_orbits(n):
    """Return the groups of centre stickers that the moves exchange with each other."""
    orbits = []
    left = {group[0] for group in _cubies(n).values() if len(group) == 1}
    while left:
        orbit = _orbit(n, min(left), lambda i, d: d[i])
        orbits.append(sorted(orbit))
        left -= orbit
    return orbits


def _parity(permutation):
    inversions = sum(1 for i in range(len(permutation)) for j in range(i)
                     if permutation[j] > permutation[i])
    return inversions % 2


def _is_reachable(n, state):
    """Check that a state can be reached from the solved state by legal moves.

    The state holds colours only, so identical pieces are interchangeable. Corners
    need all eight pieces and a twist sum of zero. The 3x3 and 5x5 also keep their
    fixed centres, flip their middle edges evenly, and match corner and middle edge
    parity. The 4x4 and 5x5 wings keep their colour order and appear once each, and
    every other centre orbit shows each colour as often as when solved.
    """
    if len(state) != 6 * n * n or any(c not in FACES for c in state):
        return False
    corners = _piece_coords(n, state, 3)
    if corners is None or len(set(corners[0])) != 8 or sum(corners[1]) % 3 != 0:
        return False
    if n == 2:
        return True
    solved = _solved(n)
    if any(Counter(state[i] for i in orbit) != Counter(solved[i] for i in orbit)
           for orbit in _centre_orbits(n)):
        return False
    if n >= 4 and sorted((state[x], state[y]) for x, y in _wings(n)) != _wing_colours(n):
        return False
    if n == 4:
        return True
    edges = _piece_coords(n, state, 2)
    if edges is None or len(set(edges[0])) != 12 or sum(edges[1]) % 2 != 0:
        return False
    return _parity(corners[0]) == _parity(edges[0])


@lru_cache(maxsize=None)
def _search_tables():
    """Return the 2x2 search moves and the pruning tables, built once.

    With the DBL corner fixed, U, R, and F give the same distances in the
    half-turn metric. A move is (face, source, twist added). The tables hold
    the distance to solved for corner orientation (3^7) and permutation (7!).
    """
    moves = []
    for face in "URF":
        for suffix in ("", "'", "2"):
            permutation, twist = _piece_coords(2, apply_move_to(2, _solved(2), face + suffix), 3)
            moves.append((face, tuple(permutation), tuple(twist)))

    def distances(start, step):
        dist, queue = {start: 0}, deque([start])
        while queue:
            key = queue.popleft()
            for _, source, twist in moves:
                new = step(key, source, twist)
                if new not in dist:
                    dist[new] = dist[key] + 1
                    queue.append(new)
        return dist

    twist_dist = distances((0,) * 8, lambda k, s, t: tuple((k[s[j]] + t[j]) % 3 for j in range(8)))
    perm_dist = distances(tuple(range(8)), lambda k, s, t: tuple(k[s[j]] for j in range(8)))
    return moves, twist_dist, perm_dist


def _fix_dbl_corner(state):
    """Return the whole-cube rotation of a 2x2 state that has the DBL corner home."""
    solved = _solved(2)
    dbl = next(p for p in _positions(2, 3) if {_face_of(2, i) for i in p} == {"D", "B", "L"})
    seen, queue = {state}, deque([state])
    while queue:
        current = queue.popleft()
        if all(current[i] == solved[i] for i in dbl):
            return current
        for rotation in ROTATIONS:
            turned = apply_move_to(2, apply_move_to(2, current, rotation[0]), rotation[1])
            if turned not in seen:
                seen.add(turned)
                queue.append(turned)
    raise ValueError("no rotation puts the DBL corner home")


def _ida_star_2x2(state):
    moves, twist_dist, perm_dist = _search_tables()
    permutation, twist = _piece_coords(2, _fix_dbl_corner(state), 3)

    def search(perm, tw, depth, bound, last_face):
        estimate = max(twist_dist[tw], perm_dist[perm])
        if depth + estimate > bound:
            return False
        if estimate == 0:
            return True
        for face, source, added in moves:
            if face != last_face and search(
                    tuple(perm[s] for s in source),
                    tuple((tw[source[j]] + added[j]) % 3 for j in range(8)),
                    depth + 1, bound, face):
                return True
        return False

    perm, tw = tuple(permutation), tuple(twist)
    bound = max(twist_dist[tw], perm_dist[perm])
    while not search(perm, tw, 0, bound, ""):
        bound += 1
    return bound


class CubeEngine(Engine):
    """The engine for the 2x2, 3x3, 4x4, and 5x5 cubes."""

    def __init__(self, n: int):
        if n not in (2, 3, 4, 5):
            raise ValueError(f"unsupported cube size {n}")
        self.n = n

    def legal_moves(self) -> list[str]:
        turns = list(FACES) + ([face + "w" for face in FACES] if self.n >= 4 else [])
        return [turn + suffix for turn in turns for suffix in ("", "'", "2")]

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
        kind = rng.choice({2: (3,), 3: (3, 2), 4: (3, "wing"), 5: (3, 2, "wing")}[self.n])
        position = rng.choice(_wings(self.n) if kind == "wing" else _positions(self.n, kind))
        old = [state[i] for i in position]
        name = _wing_name(self.n, position) if kind == "wing" else _piece_name(self.n, position)
        if kind == "wing":
            new, description = old[::-1], f"flipped wing {name}"
        elif kind == 2:
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

    def reference_length(self, state: str) -> int:
        if not _is_reachable(self.n, state):
            raise ValueError("state cannot be reached from the solved state")
        if self.n != 2:
            raise NotImplementedError("no reference solver for this cube yet (AGENTS.md open item 2)")
        return _ida_star_2x2(state)
