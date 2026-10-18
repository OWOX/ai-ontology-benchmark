# registry

File: `src/puzzles/registry.py`.

## Purpose

Map each puzzle name to its engine. This is the only list of puzzles in the code.

## Inputs

A puzzle name, such as `"3x3"`.

## Outputs

1. `ENGINES`: a dict, for example `{"2x2": CubeEngine(2), "3x3": CubeEngine(3)}`. The 5x5 is added when [open item 5](../../AGENTS.md#open) is settled.
2. `get_engine(name) -> Engine`. It raises `KeyError` with a message that lists the known names when `name` isn't one of them.

Adding a puzzle adds one line to `ENGINES`.

## How to test

1. Every name in `ENGINES` resolves to an `Engine` instance.
2. `get_engine("4x4")` raises `KeyError`, and the message contains `"2x2"`.
