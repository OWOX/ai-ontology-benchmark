# Script specs

One spec per script. Each spec lists the script's inputs, its outputs, and how to test it. A reader who doesn't know the project should be able to check a script against its spec without reading anything else. Terms are defined in [definitions.md](../definitions.md).

## Rules for every script

1. The first line is a comment that links to the script's spec, for example `# Spec: docs/specs/generate.md`. The second line starts a docstring that says what the script reads and what it writes.
2. A script stays under about 200 lines. It uses plain functions, type hints, and the standard library where it can. No metaprogramming, no clever one-liners.
3. Names in code follow [definitions.md](../definitions.md).
4. A command-line script uses `argparse`. It exits with code 0 on success and 1 on a checked error, and the error message names the file and the field at fault.
5. Each script has one test file, `tests/test_<spec name>.py`, run with `pytest`. Tests never call a real AI model API.
6. File formats: TOML for config, read with the standard library's `tomllib`. JSONL for inputs and raw records. Markdown and CSV for reports.

## Getting results

1. Run `./ui/start.sh`. It creates `.venv` and installs on the first run, then opens the UI server. Add the API keys on the Models page and start experiments from New Experiment. The CLI commands below stay available for terminal use, with `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY` exported.
2. Make a release. The script commits the new release folder and tags it `release-1.0.0` locally:
   ```
   python -m src.release.release --bump major --note "First input set"
   ```
3. Write `config/experiments/<id>.toml` naming the release, the AI models, their sampling `params`, and optionally a `[budget]` (defaults: 2.00 USD per request, 25.00 USD per AI model, 50.00 USD per experiment). Check the prompts and the cost, then run. If a budget stops the run, raise it in the config and run the same command again. Each AI model can run in its own terminal:
   ```
   python -m src.run.run --experiment <id> --dry-run
   python -m src.run.run --experiment <id> --estimate
   python -m src.run.run --experiment <id> --model <name>
   ```
4. Score it, then commit `results/<id>/`:
   ```
   python -m src.evaluate.evaluate --experiment <id>
   ```
5. To fix the assessment, commit the fix, then make a patch release and score the old experiment under it. No AI model is called again, and the old report stays as it was:
   ```
   python -m src.release.release --bump patch --note "Fix: ..."
   python -m src.evaluate.evaluate --experiment <id> --release 1.0.1
   ```
6. Steps 2 to 5 can also be done from the page opened in step 1.

## Specs

Listed in build order. Each script depends only on scripts above it.

1. [setup](setup.md): `pyproject.toml`.
2. [config](config.md): `config/` and `src/config.py`.
3. [engine](engine.md): `src/puzzles/engine.py`, the puzzle engine interface.
4. [cube](cube.md): `src/puzzles/cube.py`, the NxN cube engine.
5. [registry](registry.md): `src/puzzles/registry.py`.
6. [generate](generate.md): `src/generate/generate.py`.
7. [prompts](prompts.md): `src/run/prompts.py` and `prompts/`.
8. [release](release.md): `src/release/release.py`.
9. [validator](validator.md): `src/validator.py`.
10. [models](models.md): `src/run/models.py`.
11. [run](run.md): `src/run/run.py`, `src/run/budget.py`, and `src/run/raw.py`.
12. [report](report.md): `src/evaluate/report.py`.
13. [evaluate](evaluate.md): `src/evaluate/evaluate.py` and `src/evaluate/metrics.py`.
14. [ui](ui.md): `ui/`.
15. [site](site.md): `src/site/export.py`, the data for the public results page in `site/`.

The octahedral and tetrahedral engines have no spec yet. They wait on [open item 4](../../AGENTS.md#open).

## End-to-end test

`tests/test_pipeline.py` runs the whole flow in a temporary git repo: a major release of a small 2x2 input set, `run` with the `fake` provider, then `evaluate`. It compares the report with a stored expected file, ignoring the dates. It is the first test to run after any change that touches more than one script.
