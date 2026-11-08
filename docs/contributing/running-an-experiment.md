# Running an experiment

Terms are defined in [definitions.md](../definitions.md). Every option is in the [run](../specs/run.md) and [evaluate](../specs/evaluate.md) specs.

## One experiment, one branch

1. An [experiment](../definitions.md#releases-and-experiments) lives on its own branch, `results/<experiment id>`. The branch holds the experiment config, its raw records, and its reports. It never holds code.
2. An experiment runs against one release. The release's inputs and prompts are frozen, and `run` only reads them ([invariant 5](../../AGENTS.md#invariants)). Every AI model and every setup sees the same inputs.
3. The first `run` writes the config to `results/<experiment id>/experiment.toml`, with `release = "latest"` replaced by the version it picked. From then on the experiment keeps that release, even after a newer one appears.
4. The config can't change once the experiment starts. Only `[budget]` can be raised, so a stopped run can resume.
5. Raw records are append-only ([invariant 11](../../AGENTS.md#invariants)). `run` commits each attempt to the branch, so a stopped run resumes and skips attempts already recorded.
6. A different input set, a prompt change, or a different set of AI models is a new experiment with a new id and a new branch.

## Steps in the UI

1. Run `./ui/start.sh`. The first run creates `.venv` and installs the project.
2. On the Models page, add the API key for each provider you use.
3. Click New Experiment. Pick the puzzles and AI models, and set the parameters. The UI names the experiment id from them. Picking an existing branch loads that experiment instead.
4. Run the estimate and check the worst-case cost against each [budget](../definitions.md#prices).
5. Click Run. The experiment page opens and shows every attempt as it is recorded.
6. When every run job has ended, click Evaluate to write the report.
7. Click Commit. It pushes `results/<experiment id>` and opens a pull request to `main` with the release, puzzles, AI models, and a link to the report.

## Steps in the terminal

Run every command from the repo root with `.venv` active.

1. Install, if you haven't:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e '.[test]'
   ```
2. Choose a unique experiment id, `<models>_<puzzles>_<yyyymmdd-hhmm>` with dots replaced by `-`, for example `claude-haiku-5-5_2x2_20261108-1200`. It names the branch everyone sees.
3. Copy a template from `config/templates/` to `config/experiments/<experiment id>.toml`, and set the AI models, puzzles, attempts, and `[budget]`:
   ```
   cp config/templates/anthropic.toml config/experiments/<experiment id>.toml
   ```
4. Export the API key for each provider, for example `export ANTHROPIC_API_KEY=...`.
5. Check the prompts and the cost. Neither command calls an AI model:
   ```
   python -m src.run.run --experiment <experiment id> --dry-run
   python -m src.run.run --experiment <experiment id> --estimate
   ```
6. Run three attempts as a smoke test, then the rest:
   ```
   python -m src.run.run --experiment <experiment id> --limit 3
   python -m src.run.run --experiment <experiment id>
   ```
   `run` commits each attempt to `results/<experiment id>` and pushes the branch at exit. Add `--model <name>` to run one AI model per terminal.
7. If a budget stop ends the run, raise the budget in `[budget]` and run the same command again. It skips the attempts already recorded.
8. Score the experiment, then commit and push the report. `run` with `--limit 0` calls no AI model:
   ```
   python -m src.evaluate.evaluate --experiment <experiment id>
   python -m src.run.run --experiment <experiment id> --limit 0
   ```

## After the run

1. To fix the assessment, change the code on a branch and merge it, then cut a patch release and score the old experiment under it. No AI model is called again, and the old report stays:
   ```
   python -m src.release.release --bump patch --note "Fix: ..."
   python -m src.evaluate.evaluate --experiment <experiment id> --release <new version>
   ```
2. Never edit a raw record, and never rerun an attempt because its answer is wrong ([invariant 10](../../AGENTS.md#invariants)).
