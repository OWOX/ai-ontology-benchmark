# release

File: `src/release/release.py`.

## Purpose

The [`release`](../definitions.md#workflows) workflow. Freeze the current input set, prompt templates, and assessment into a new [release](../definitions.md#releases-and-experiments), check that what changed matches the version bump, then commit and tag it.

## Inputs

1. `--bump major|minor|patch`.
2. `--note TEXT`: one line saying why this release exists. Required.
3. `config/release.toml`, loaded with [config](config.md). Read only for a major bump.
4. `prompts/`: the working prompt templates.
5. The assessment files: `src/validator.py`, `src/puzzles/*.py`, `src/run/raw.py`, `src/evaluate/evaluate.py`, `src/evaluate/metrics.py`, `src/run/decision.py` (the decision loop), and `src/run/prompts.py` (the code that builds its states). `src/evaluate/report.py` is left out, so a change to report formatting never needs a release.
6. The latest folder in `releases/`, if there is one.
7. `--releases DIR`, default `releases/`. Tests point it at a temporary folder.

## Outputs

1. A new folder `releases/<MAJOR.MINOR.PATCH>/`, every file set read-only once written:
   1. `inputs.jsonl`. For a major bump, built by [generate](generate.md). Otherwise a byte-for-byte copy from the latest release.
   2. `prompts/<setup>/<puzzle>.txt` and `prompts/decision/questions.txt`. A copy of the working templates.
   3. `manifest.json`. It holds the release version, the input set id, the release config, the note, the creation time, the git commit it was built from, the sha256 of every other file in the folder, `prompt_versions` and `decision_prompt_versions` from [prompts](prompts.md), and `assessment_sha256`. That last one is the sha256 of the assessment files' contents, taken in sorted path order.
   4. `README.md`, for people. It holds the version, the note, and the date, a table of input counts by puzzle, depth, and validity, a table of prompt versions and a table of decision prompt versions by setup and puzzle, the assessment hash, and a link to the release before it.
2. A local git commit holding only the new folder, with the message `Release <version>: <note>`, and a local tag `release-<version>` on it. Nothing is pushed.

Bump rules, compared with the latest release. `release` exits with code 1 and writes nothing if any rule fails:

| Bump | Inputs | Prompt versions and decision prompt versions | Assessment |
|---|---|---|---|
| major | new input set, input set id = new major | any | any |
| minor | copied | at least one, in either table, differs | any |
| patch | copied | all equal in both tables | differs |

Against an old release without `decision_prompt_versions`, a missing field counts as different for a minor bump, so it is accepted on that field alone. A patch bump compares only `prompt_versions` there, so an assessment fix can still be released as a patch.

It also refuses when the git working tree has uncommitted changes, because the manifest's commit must describe the code exactly.

## How to test

All tests use a temporary releases folder inside a temporary git repo.

1. The first major bump writes `1.0.0` with every file above, every hash in the manifest matches its file, and tag `release-1.0.0` points at a commit holding only that folder.
2. A minor bump after a template edit writes `1.1.0` with an identical `inputs.jsonl`.
3. A minor bump with no template, `render()`, or `legal_moves()` change exits with code 1.
4. A patch bump after a validator edit writes `1.1.1`. Its inputs and prompt versions equal `1.1.0`, and only `assessment_sha256` differs.
5. A patch bump after a change to `render()` exits with code 1, because prompt versions changed.
6. A patch bump after a change only to `report.py` exits with code 1, because the assessment didn't change.
7. Uncommitted changes make every bump exit with code 1.
8. Files in the new release can't be opened for writing.
9. The manifest and README hold `decision_prompt_versions`, and `prompts/decision/questions.txt` is in `files`.
10. A minor bump after editing only `questions.txt` is accepted. A patch bump after the same edit exits with code 1.
11. A patch bump against an old manifest without `decision_prompt_versions`, with unchanged LLM prompts and a changed assessment, is accepted.
