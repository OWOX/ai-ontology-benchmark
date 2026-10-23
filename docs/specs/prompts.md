# prompts

Files: `src/run/prompts.py`, `prompts/<setup>/<puzzle>.txt`.

## Purpose

Turn one input and one [setup](../definitions.md#setups) into the exact prompt text, and compute the [prompt version](../definitions.md#setups) of every setup and puzzle in a release. Every AI model gets the same text for the same input and setup.

## Inputs

1. An input, as one line of a release's `inputs.jsonl`.
2. A setup: `no_model`, `descriptive`, or `prescriptive`.
3. A templates folder with `<setup>/<puzzle>.txt`. [run](run.md) passes the release's frozen copy, `releases/<version>/prompts/`. [release](release.md) passes the working `prompts/` folder. A template holds plain text with the placeholder `{state}`. Prescriptive templates also hold `{legal_moves}`. No other placeholders are allowed.

## Outputs

1. `build_prompt(templates_dir, input, setup) -> str`. The template with `{state}` replaced by the engine's `render()` and, for the prescriptive setup, `{legal_moves}` replaced by `legal_moves()` joined with single spaces, in the order the engine returns them. There is no system prompt. The text goes to the AI model as one user message.
2. `prompt_versions(templates_dir, inputs) -> {setup: {puzzle: version}}`. For each setup and puzzle, the first 12 hex characters of one sha256 over every prompt built for it, in input order, each followed by a newline. A change to a template, to `render()`, or to `legal_moves()` changes the version.

Both raise `ValueError` if a template is missing, has an unknown placeholder, lacks `{state}`, or (for the prescriptive setup) lacks `{legal_moves}`. Templates are read as UTF-8.

## How to test

1. The same input and setup give byte-identical text on repeated calls.
2. The text never contains the input's scramble, joined with spaces, for any input in a test input set.
3. In the prescriptive text, the move list equals `" ".join(legal_moves())`.
4. Changing one character of a template changes the version of that setup and puzzle and no other.
5. Patching the engine's `render()` in a test changes every version for that puzzle.
6. A template with `{scramble}` raises `ValueError`.
7. A template without `{state}`, and a prescriptive template without `{legal_moves}`, each raise `ValueError`.

## Open

The template text for each setup ([open item 1](../../AGENTS.md#open)) is a draft until the project owner approves it. All three setups share the description of the state format and the closing instructions, so only the rules differ. The prescriptive setup carries the descriptive rules plus the move list.
