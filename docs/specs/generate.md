# generate

File: `src/generate/generate.py`.

## Purpose

The [`generate`](../definitions.md#workflows) workflow. Build one input set from `config/release.toml`. It never talks to an AI model. Only [release](release.md) calls it, for a major release. It has no command line of its own.

## Inputs

1. The release config, loaded with [config](config.md).
2. `input_set_id`: the major number of the new release, as a string, for example `"1"`.

## Outputs

`build_inputs(release_config, input_set_id) -> str`: the full text of `inputs.jsonl`, one input per line, as JSON with sorted keys.

| Field | Value |
|---|---|
| `input_id` | `<puzzle>-d<depth>-<n>`, for example `3x3-d10-007`. An invalid copy adds `-x`: `3x3-d10-007-x`. |
| `input_set_id` | as passed in |
| `input_seed` | `int(sha256(f"{seed}:{input_id}").hexdigest()[:16], 16)` |
| `puzzle` | the puzzle name |
| `state` | the engine's state |
| `scramble` | the scramble's moves, as a list |
| `scramble_depth` | the depth |
| `validity` | `"valid"` or `"invalid"` |
| `source_input_id` | for an invalid input, the id it was made from. Otherwise `null`. |
| `corruption` | for an invalid input, the engine's description. Otherwise `null`. |

Order: by puzzle as listed in config, then by depth, then by `n` from 1. For each puzzle and depth, the first `round(valid_invalid_split × scramble_count)` valid inputs each get an invalid copy, written straight after its source.

## How to test

1. Two calls with the same config give identical text.
2. The line count equals puzzles × depths × scramble count × (1 + split), with the split part rounded per puzzle and depth.
3. Every input passes `load_state()` for its puzzle, and every invalid input's `source_input_id` exists in the text.
4. Input ids are unique, and so are input seeds.
