# engine

File: `src/puzzles/engine.py`.

## Purpose

Define the [puzzle engine interface](../../AGENTS.md#puzzle-engine-interface) once, so every engine has the same methods and nothing else in the code needs to know which puzzle it is handling.

## Inputs

None.

## Outputs

An abstract base class `Engine` with the nine abstract methods from AGENTS.md, in the same order: `legal_moves`, `solved_state`, `load_state`, `apply_move`, `is_solved`, `scramble`, `corrupt`, `render`, and `is_move_token`. Each method's docstring repeats its line from AGENTS.md. The class has no logic.

Two exception classes live here too, so that callers can catch them by name:

1. `IllegalMoveError`, raised by `apply_move()`.
2. `ValidityMismatchError`, raised by `load_state()` when a state disagrees with its validity label.

## How to test

1. A subclass that implements all nine methods can be instantiated.
2. A subclass that leaves out any one method raises `TypeError` on instantiation. One test for each method.
