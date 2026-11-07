# prompts

Files: `src/run/prompts.py`, `prompts/<setup>/<puzzle>.txt`, `prompts/decision/questions.txt`.

## Purpose

Turn one input and one [setup](../definitions.md#setups) into the exact prompt text, and compute the [prompt version](../definitions.md#setups) and the [decision prompt version](../definitions.md#setups) of every setup and puzzle in a release. Every AI model gets the same text for the same input and setup.

## Inputs

1. An input, as one line of a release's `inputs.jsonl`.
2. A setup: `no_model`, `descriptive`, or `prescriptive`.
3. A templates folder with `<setup>/<puzzle>.txt`. [run](run.md) passes the release's frozen copy, `releases/<version>/prompts/`. [release](release.md) passes the working `prompts/` folder. A template holds plain text with the placeholder `{state}`. Prescriptive templates also hold `{legal_moves}`. A template may hold `{mismatch_reasons}`, and from the release that adds [mismatch reasons](../definitions.md#attempts-and-outcomes) every template holds it. No other placeholders are allowed.

## Outputs

1. `fill_template(template, input, setup) -> str`. The substitution part of `build_prompt`: the template text with `{state}` replaced by the engine's `render()` and, for the prescriptive setup, `{legal_moves}` replaced by `legal_moves()` joined with single spaces, in the order the engine returns them, and `{mismatch_reasons}` replaced by `offered_reasons(engine)` from the [validator](validator.md), each in backticks, joined with `, `. It reads no file.
2. `build_prompt(templates_dir, input, setup) -> str`. Reads the template and returns `fill_template` of it. There is no system prompt. The text goes to the AI model as one user message. Every LLM template ends by asking for the moves one per line, or the single line `MISMATCH` followed by one space and one reason from `{mismatch_reasons}`, as [invariant 9](../../AGENTS.md#invariants) says.

   Before: `If the state cannot be reached from the solved state by legal moves, reply with the single line MISMATCH and nothing else.`

   After: `If the state cannot be reached from the solved state by legal moves, reply with the single line MISMATCH, one space, and the reason, exactly as written in this list: {mismatch_reasons}. Use other when none of them fits. Write nothing else.`
3. `prompt_versions(templates_dir, inputs) -> {setup: {puzzle: version}}`. For each setup and puzzle, the first 12 hex characters of one sha256 over every prompt built for it, in input order, each followed by a newline. A change to a template, to `render()`, or to `legal_moves()` changes the version.

4. `parse_questions(text, source) -> {"next_move": str, "done": str, "mismatch": str}`. Reads the text of `decision/questions.txt`, one `key: text` per line. Raises `ValueError` naming `source` if a key is missing. It reads no file, so the UI can pass it text read from git.
5. `load_questions(templates_dir) -> {"next_move": str, "done": str, "mismatch": str}`. Reads `decision/questions.txt` and returns `parse_questions` of it with the file path as `source`. Raises `ValueError` naming the file if it is missing or lacks a key.
6. `decision_state(prompt, moves) -> str`. The prompt, a blank line, then `Moves so far: ` and the moves joined by single spaces, or `none`.
7. `decision_questions(questions, legal, reasons=None) -> dict`. The request's `questions` object: `next_move` of type `choice` whose `criteria` map `move_<n>` (the move's position in `legal` from 1) to the move string, then `done` to its description from the file. With `reasons`, `mismatch_<n>` (the reason's position in `reasons` from 1) follow, each mapped to the file's `mismatch` text, one space, and `Reason: <reason>.`. Without, `mismatch` follows, mapped to the file's text. It holds no other question.
8. `decision_prompt_versions(templates_dir, inputs) -> {setup: {puzzle: version}}`. For each setup and puzzle, the [decision prompt version](../definitions.md#setups): the first 12 hex characters of one sha256 over the questions file's bytes, then, for every input in order, `decision_state(prompt, [])` and `json.dumps(decision_questions(questions, legal, reasons), sort_keys=True)`, with `reasons` from `offered_reasons(engine)` when `uses_mismatch_reasons(templates_dir)` and `None` otherwise, each followed by a newline. A change to `questions.txt`, to the suffix `decision_state` adds, or to the request's structure changes the decision versions and no LLM version.
9. `uses_mismatch_reasons(templates_dir) -> bool`. True when every LLM template holds `{mismatch_reasons}`, false when none does. Raises `ValueError` naming the templates that differ when only some do. [release](release.md) writes it to the manifest as `mismatch_reasons`.

`build_prompt` and `prompt_versions` raise `ValueError` if a template is missing, has an unknown placeholder, lacks `{state}`, or (for the prescriptive setup) lacks `{legal_moves}`. Templates are read as UTF-8. Each template file is read once per process: the cache is keyed on the resolved path, the file's modification time, size, inode, and change time, and the setup, so an edited or replaced file is read again.

## How to test

1. The same input and setup give byte-identical text on repeated calls.
2. The text never contains the input's scramble, joined with spaces, for any input in a test input set.
3. In the prescriptive text, the move list equals `" ".join(legal_moves())`.
4. Changing one character of a template changes the version of that setup and puzzle and no other.
5. Patching the engine's `render()` in a test changes every version for that puzzle.
6. A template with `{scramble}` raises `ValueError`.
7. A template without `{state}`, and a prescriptive template without `{legal_moves}`, each raise `ValueError`.
8. `decision_state` gives `none` for no moves and the moves joined by spaces otherwise.
9. `decision_questions` names options `move_1`, `move_2`, and so on, then `done`, then `mismatch` without reasons, or `mismatch_1` to `mismatch_<k>` in `offered_reasons` order with them.
10. `load_questions` raises `ValueError` for a missing file and for a missing key.
11. `parse_questions` returns the three questions for good text, and raises `ValueError` naming `source` when a key is missing.
12. Editing `questions.txt` changes every decision version and leaves `prompt_versions` equal.

## Open

The template text for each setup ([open item 1](../../AGENTS.md#open)) was approved by the project owner on 2026-10-23. All three setups share the description of the state format, the notation name, and the closing instructions, so only the rules differ. The prescriptive setup carries the descriptive rules plus the move list. The text of `decision/questions.txt`, with `mismatch` as an option of `next_move`, was approved by the project owner on 2026-11-02. The closing line above, which asks for a [mismatch reason](../definitions.md#attempts-and-outcomes), was decided by the project owner on 2026-11-07, and its exact wording is still to be approved.
13. Changing the suffix `decision_state` adds, or the structure `decision_questions` builds, changes every decision version and leaves `prompt_versions` equal.
14. With `{mismatch_reasons}` in a template, the text lists every string of `offered_reasons(engine)` in order, `other` last, and the cube text names `twisted centre`.
15. `uses_mismatch_reasons` is true for templates that all hold the placeholder, false for none, and raises `ValueError` for a mix.
