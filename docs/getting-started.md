# Getting started

The minimum steps to run an [experiment](definitions.md#releases-and-experiments) from the terminal and get its report. Every option is in the [run](specs/run.md) and [evaluate](specs/evaluate.md) specs. Run every command from the repo root with `.venv` active.

## 1. Install

You need Python 3.11 or later and git.

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest
```

Tests never call a real AI model API.

## 2. Copy an example config

`config/templates/` holds one experiment config per provider: `anthropic`, `openai`, `google`, and `fake`. Copy one to `config/experiments/`. The file name you copy to is the experiment id, and it names the branch `results/<experiment id>` that everyone sees, so make it unique. Name it as the UI does, `<models>_<puzzles>_<yyyymmdd-hhmm>` with dots replaced by `-`, for example `claude-haiku-5-5_2x2_20261103-1200`.

```
cp config/templates/anthropic.toml config/experiments/claude-haiku-5-5_2x2_20261103-1200.toml
export ANTHROPIC_API_KEY=...
```

The other providers read `OPENAI_API_KEY` and `GOOGLE_API_KEY`. To run a model through OpenRouter, give its entry `provider = "openrouter"` and the OpenRouter model id as `api_model_id`, add its price row, and export `OPENROUTER_API_KEY`. The UI doesn't offer OpenRouter, so run such an experiment from the terminal. Set the key before you run, because `--estimate` doesn't check it. The templates set `release = "latest"`, which picks the newest release on the first run, and the experiment keeps it.

The `fake` config needs no key and spends nothing, because the fake provider reports zero tokens. `--estimate` still prices it as a real model. Add `--no-commit` to every `run` command with it, so the smoke test stays out of git, and skip the second command in step 4.

## 3. Check the cost and run

```
python -m src.run.run --experiment <experiment id> --estimate
python -m src.run.run --experiment <experiment id> --limit 3
python -m src.run.run --experiment <experiment id>
```

`--estimate` prints the worst-case cost against each [budget](definitions.md#prices) and calls nothing. `--limit 3` runs three attempts as a smoke test. The last command runs the rest and skips attempts already recorded. `run` commits each attempt to the branch `results/<experiment id>` and pushes it to `origin` at the end.

## 4. Score

```
python -m src.evaluate.evaluate --experiment <experiment id>
python -m src.run.run --experiment <experiment id> --limit 0
```

`evaluate` writes the report to `results/<experiment id>/<release>.md` in the work tree only. Running `run` with `--limit 0` calls no AI model. It commits the report to the results branch and pushes it.
